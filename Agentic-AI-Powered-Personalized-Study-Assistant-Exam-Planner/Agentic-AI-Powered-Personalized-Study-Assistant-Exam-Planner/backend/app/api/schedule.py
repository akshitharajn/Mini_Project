"""Schedule API routes."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
import random
import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.database import get_db
from backend.app.models.user import User
from backend.app.models.subject import Subject
from backend.app.models.topic import Topic
from backend.app.models.schedule import ScheduleEntry
from backend.app.schemas.schedule import (
    ScheduleGenerateRequest,
    ScheduleEntryOut,
    ScheduleFromSyllabusPdfOut,
    ScheduleRescheduleOut,
    ManualScheduleGenerateRequest,
)
from backend.app.schemas.quiz import QuizGenerateRequest
from backend.app.schemas.progress import ProgressUpdate
from backend.app.services.progress import record_progress
from backend.app.services.scheduler import (
    generate_schedule,
    generate_schedule_rule_based,
    blocks_to_entries,
)
from backend.app.services.syllabus_langchain import (
    extract_unit_topics_from_pdf_with_langchain,
)
from backend.app.services.quiz_engine import create_quiz
from backend.app.services.syllabus_parser import extract_text_from_pdf, parse_subjects_and_topics
from backend.app.services.robust_syllabus import (
    extract_pdf_text_robust,
    parse_subjects_and_topics_robust,
)
from backend.app.services.topic_text import (
    humanize_topic_text,
    split_period_topic_list,
    topic_dedupe_key,
    strip_duration_from_topic,
    estimate_topic_duration_hours,
)

router = APIRouter(prefix="/api/schedule", tags=["schedule"])

_UNIT_WITH_SUFFIX_PATTERN = re.compile(
    r"^\s*(Unit\s*[IVXLC\d]+)\s*:\s*(.+)$",
    re.IGNORECASE,
)
_TOPIC_SEP_PATTERN = re.compile(r"\s*(?:;|\||\u2022)\s*")
_COURSE_CODE_TOKEN_PATTERN = re.compile(r"\b[A-Z]{1,4}\d{3}[A-Z]{0,4}\b", re.IGNORECASE)
_COURSE_CODE_PREFIX_PATTERN = re.compile(r"^\s*[A-Z]{1,4}\d{3}[A-Z]{0,4}\s*[-:]\s*", re.IGNORECASE)
_NOISE_TOPIC_EXACT = {"nit02"}
_NOISE_TOPIC_BODY_EXACT = {"a", "j", "np", "11 x", "802", "0/1"}
_NOISE_SINGLE_WORD_BODIES = {
    "information",
    "application",
    "applications",
    "database",
    "databases",
    "item",
    "items",
    "structure",
    "structures",
    "tech",
    "education",
    "title",
    "ltd",
    "conventional",
    "international",
    "julia",
    "julie",
    "meira",
    "tan",
    "tiwary",
    "kowalski",
    "maybury",
    "manning",
    "raghavan",
    "schutze",
    "maheshwari",
    "mithani",
    "solvency",
    "algorithms",
}
_ALLOWED_SINGLE_WORD_BODIES = {
    "introduction",
    "basics",
    "sensing",
    "actuation",
    "hypertext",
    "agriculture",
    "healthcare",
    "retrieval",
    "classification",
    "overfitting",
    "regression",
    "logistic",
    "production",
    "cost",
    "solvency",
}
_FRAGMENT_ENDINGS = {"and", "of", "to", "for", "with", "or", "amp", "etc", "application", "applications"}
_NOISE_TOPIC_PHRASES = {
    "pre requisite",
    "pre - requisite",
    "prerequisite",
    "syllabus",
    "course outcome",
    "course outcomes",
    "course description",
    "cse ai ml syllabus",
    "reference books",
    "text books",
    "text book",
    "reference book",
    "student s handbook",
    "course title",
    "lt pcredits",
    "ltpcredits",
    "open elective",
    "professional elective",
    "book house",
    "himalaya publishing",
    "stan ford",
    "univ",
    "after completion of this course",
    "after completion of thiscourse",
    "students will be able to",
    "studentswill be ableto",
    "objectives of the course",
    "the objectives of the course",
    "objectives of thecourse",
    "course are to understand",
    "courseare to understand",
    "be able to",
    "students will be ableto",
    "be ableto",
    "develop a clear comprehension",
    "gain expertise",
    "understanding of data handling",
    "understanding of datahandling",
    "software defined networking",
    "fundamentals of iot",
    "introduction to information retrieval",
    "construction of iot applications",
    "ii year ii semester",
    "il year il semester",
    "contains supervised and unsupervised models",
    "search methods and visualization techniques",
    "language processing applications",
    "inlationus",
    "markttucture",
    "monolyligopolyonplist",
}
_BOOKISH_HINTS = {
    "mc graw",
    "mcgraw",
    "wiley",
    "pearson",
    "cambridge",
    "oxford",
    "press",
    "publication",
    "publications",
    "publishers",
    "edition",
    "tata",
    "morgan kaufmann",
    "oreilly",
    "geethika",
    "ghosh",
    "piyali",
    "roy choudhury",
    "chaturvedi",
    "gupta",
    "frakes",
    "baeza",
    "leskovec",
    "ullman",
    "maheswaran",
    "maheshwaran",
    "rajaraman",
    "ilinsky",
    "dhanesh",
    "khatri",
    "maheshwari",
    "mithani",
    "siddiqui",
    "zitouni",
    "bikel",
    "manning",
    "raghavan",
    "schutze",
    "kowalski",
    "maybury",
    "prentice hall",
    "gerald",
    "mark t",
    "paresh shah",
    "kumar",
    "zaki",
    "daniel",
    "steinbach",
    "ste inbach",
}
_NOISE_TOPIC_PREFIXES = (
    "course title",
    "ii year",
    "iii year",
    "lt pcredits",
    "ltpcredits",
    "open elective",
    "professional elective",
)
_FRAGMENT_STARTERS = {"of", "and", "to", "for", "in", "with", "by", "on", "from"}
_SAFE_TITLE_WORDS = {
    "advanced",
    "analytics",
    "basics",
    "concepts",
    "concept",
    "design",
    "economics",
    "hypertext",
    "indexing",
    "introduction",
    "language",
    "linkages",
    "management",
    "modeling",
    "processing",
    "retrieval",
    "revision",
    "structures",
    "systems",
    "techniques",
    "themes",
    "topics",
    "visualization",
}
_BROKEN_COURSE_CODE_PATTERN = re.compile(r"\b[a-z]\s*\d{2,3}\s*[a-z](?:\s*[a-z])?\b", re.IGNORECASE)
_OUTCOME_VERB_PATTERN = re.compile(
    r"\b(?:apply|analyze|build|develop|explore|evaluate|gain|demonstrate|understand|construct|carry out|comprehend|examine|achieve)\b",
    re.IGNORECASE,
)
_TECHNICAL_TOPIC_HINTS = {
    "regression",
    "time series",
    "learning models",
    "objective segmentation",
    "language models",
    "performance",
    "probability",
    "statistics",
    "pricing",
    "economics",
}

_UNICODE_ROMAN_MAP = str.maketrans({
    "\u2160": "I",
    "\u2161": "II",
    "\u2162": "III",
    "\u2163": "IV",
    "\u2164": "V",
    "\u2165": "VI",
    "\u2166": "VII",
    "\u2167": "VIII",
    "\u2168": "IX",
    "\u2169": "X",
})
_UNIT_ONLY_PATTERN = re.compile(r"^\s*Unit\s*-?\s*([IVXLC\d]+)\s*$", re.IGNORECASE)
_UNIT_PREFIX_PATTERN = re.compile(r"^\s*Unit\s*-?\s*([IVXLC\d]+)\b", re.IGNORECASE)


def _humanize_topic_text(text: str) -> str:
    cleaned = humanize_topic_text(text)
    cleaned = (
        cleaned.replace("．", ".")
        .replace("。", ".")
        .replace("｡", ".")
        .replace("：", ":")
        .replace("（", "(")
        .replace("）", ")")
        .replace("•", ".")
        .replace("·", ".")
    )
    substitutions = (
        (r"\bBayesiantopicbased\b", "Bayesian topic based"),
        (r"\bofword senses\b", "of word senses"),
        (r"\bforprediction\b", "for prediction"),
        (r"\bConcep\s+tof\b", "Concept of"),
        (r"SDN\)\s*SDN", "SDN) SDN"),
    )
    for pattern, replacement in substitutions:
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" .,-")


def _split_period_topic_list(text: str) -> list[str]:
    return split_period_topic_list(text)


def _topic_dedupe_key(text: str) -> str:
    return topic_dedupe_key(text)


def _sanitize_schedule_entries(entries: list[ScheduleEntry]) -> list[ScheduleEntry]:
    for entry in entries:
        entry.subject_name = _humanize_topic_text(entry.subject_name or "")
        entry.topic_name = _humanize_topic_text(entry.topic_name or "")
    return entries


def _topic_name_and_estimated_hours(raw_topic: str, default_hours: float) -> tuple[str, float]:
    cleaned_topic, explicit_duration_mins = strip_duration_from_topic(raw_topic)
    if explicit_duration_mins is not None:
        estimated_hours = max(0.25, round(explicit_duration_mins / 60.0, 2))
    else:
        estimated_hours = estimate_topic_duration_hours(cleaned_topic, fallback_hours=default_hours)
    return cleaned_topic, estimated_hours


def _expand_unit_only_topics(raw_topics: list[str]) -> list[str]:
    expanded: list[str] = []
    idx = 0
    while idx < len(raw_topics):
        current = _humanize_topic_text(raw_topics[idx])
        if not current:
            idx += 1
            continue
        unit_only = _UNIT_ONLY_PATTERN.match(current)
        if unit_only and idx + 1 < len(raw_topics):
            nxt = _humanize_topic_text(raw_topics[idx + 1])
            if nxt and not _UNIT_ONLY_PATTERN.match(nxt):
                expanded.append(f"Unit {unit_only.group(1)}: {nxt}")
                idx += 2
                continue
        expanded.append(current)
        idx += 1
    return expanded


def _split_topic_candidates(raw_topic: str) -> list[str]:
    cleaned = _humanize_topic_text(raw_topic)
    if not cleaned:
        return []
    if _UNIT_ONLY_PATTERN.match(cleaned):
        return []
    cleaned = re.sub(r"\btopicbased\b", "topic based", cleaned, flags=re.IGNORECASE)

    unit_prefix = ""
    topic_body = cleaned
    unit_match = _UNIT_WITH_SUFFIX_PATTERN.match(cleaned)
    if unit_match:
        unit_prefix = unit_match.group(1).strip()
        topic_body = unit_match.group(2).strip()

    split_parts: list[str] = []
    for part in _TOPIC_SEP_PATTERN.split(topic_body):
        p = part.strip(" .,-")
        if not p:
            continue
        if ":" in p:
            head, tail = p.split(":", 1)
            normalized_head = re.sub(r"[^a-z0-9]+", " ", head.lower()).strip()
            if any(hint in normalized_head for hint in _BOOKISH_HINTS):
                continue
            if len(head.split()) <= 4 and len(tail.split()) >= 2:
                p = tail.strip()
        comma_parts = [s.strip(" .,-") for s in p.split(",") if s.strip(" .,-")]
        first_part = comma_parts[0] if len(comma_parts) >= 1 else ""
        second_part = comma_parts[1] if len(comma_parts) >= 2 else ""
        short_comma_list = (
            2 <= len(comma_parts) <= 5
            and all(len(x.split()) <= 8 for x in comma_parts)
            and any(len(x.split()) >= 2 for x in comma_parts)
        )
        # Split by comma only when it looks like a topic list, not prose.
        protected_two_part_phrase = (
            (
                len(comma_parts) >= 1
                and re.search(r"\bwords?\s+and\s+their\s+components\b", first_part, re.IGNORECASE)
            )
            or (
                len(comma_parts) >= 2
                and re.search(r"\bprogramming\b", first_part, re.IGNORECASE)
                and re.search(r"\bintegration\b", second_part, re.IGNORECASE)
            )
            or (
                len(comma_parts) >= 2
                and re.search(r"\bissues?\b|\bchallenges?\b", second_part, re.IGNORECASE)
            )
        )
        should_split_two = (
            len(comma_parts) == 2
            and all(len(x.split()) <= 10 for x in comma_parts)
            and not comma_parts[1].lower().startswith(("and ", "or "))
            and not protected_two_part_phrase
        )
        if (
            len(comma_parts) == 2
            and len(comma_parts[1].split()) <= 5
            and _is_valid_topic_text(
                f"{unit_prefix}: {comma_parts[1]}" if unit_prefix else comma_parts[1]
            )
        ):
            should_split_two = True
        if (short_comma_list and len(comma_parts) >= 3) or should_split_two:
            for comma_part in comma_parts:
                split_parts.extend(_split_period_topic_list(comma_part))
        else:
            split_parts.extend(_split_period_topic_list(p))

    seen: set[str] = set()
    finalized: list[str] = []
    for part in split_parts:
        item = _humanize_topic_text(part)
        if not item:
            continue
        if _UNIT_ONLY_PATTERN.match(item):
            continue
        full = f"{unit_prefix}: {item}" if unit_prefix else item
        if re.match(r"^\s*Unit\s*[IVXLC\d]+\s*:\s*Unit\s*[IVXLC\d]+\s*$", full, re.IGNORECASE):
            continue
        if not _is_valid_topic_text(full):
            continue
        key = _topic_dedupe_key(full)
        if key in seen:
            continue
        seen.add(key)
        finalized.append(full[:300])
    return finalized


def _normalize_subject_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def _strip_course_code_prefix(name: str) -> str:
    return _COURSE_CODE_PREFIX_PATTERN.sub("", _clean_subject_name(name)).strip()


def _subject_alias_key(name: str) -> str:
    return _normalize_subject_key(_strip_course_code_prefix(name))


def _clean_subject_name(name: str) -> str:
    cleaned = _humanize_topic_text(name)
    cleaned = cleaned.translate(_UNICODE_ROMAN_MAP)
    cleaned = re.sub(r"\bUnit\s*-\s*([IVXLC]+)\b", r"Unit \1", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bUnit\s+VL\b", "Unit V", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bUnit\s+V1\b", "Unit VI", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"([a-z])([A-Z])", r"\1 \2", cleaned)
    cleaned = re.sub(r"^\s*ntroduction\b", "Introduction", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace("&", " & ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" .,-")


def _roman_to_int(token: str) -> int | None:
    t = token.strip().upper()
    if not t:
        return None
    if t.isdigit():
        return int(t)
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    prev = 0
    for ch in reversed(t):
        score = values.get(ch)
        if score is None:
            return None
        if score < prev:
            total -= score
        else:
            total += score
            prev = score
    return total if total > 0 else None


def _topic_unit_number(name: str) -> int | None:
    match = _UNIT_PREFIX_PATTERN.match(_humanize_topic_text(name))
    return _roman_to_int(match.group(1)) if match else None


def _normalize_topic_items(raw_topics: list[str], subject_name: str) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_topic in _expand_unit_only_topics([str(topic or "") for topic in raw_topics]):
        split_candidates = _split_topic_candidates(str(raw_topic))
        if not split_candidates:
            candidate = _humanize_topic_text(str(raw_topic)).strip()
            split_candidates = [candidate] if candidate else []
        for topic_name in split_candidates:
            if not _is_valid_topic_text(topic_name, subject_name):
                continue
            topic_key = _topic_dedupe_key(topic_name)
            if topic_key in seen:
                continue
            seen.add(topic_key)
            normalized.append(topic_name[:300])
    return normalized


def _is_strong_subject_name(name: str) -> bool:
    text = _clean_subject_name(name)
    if not text:
        return False
    lower = text.lower()
    if lower.startswith("introduction to "):
        return False
    if re.match(r"^[A-Z]{1,4}\d{3}[A-Z]{1,4}\s*[-:]", text):
        return True
    if re.match(r"^[A-Z]\s*\d{3}\s*[A-Z]{0,2}$", text):
        return False
    if ":" in text or lower.startswith("unit "):
        return False
    if re.search(r"\d", text) and "-" not in text and len(re.findall(r"[A-Za-z][A-Za-z&-]*", text)) <= 3:
        return False
    words = re.findall(r"[A-Za-z][A-Za-z&-]*", text)
    return 2 <= len(words) <= 14


def _is_valid_topic_text(topic_name: str, subject_name: str | None = None) -> bool:
    text = _humanize_topic_text(topic_name)
    if not text:
        return False
    lower = text.lower()
    if _UNIT_ONLY_PATTERN.match(text):
        return False
    if lower in _NOISE_TOPIC_EXACT:
        return False
    if _COURSE_CODE_TOKEN_PATTERN.search(text) or re.search(r"\bnit\s*\d+\b", lower):
        return False
    body_text = re.sub(r"^\s*Unit\s*[IVXLC\d]+\s*:\s*", "", text, flags=re.IGNORECASE).strip()
    if re.match(r"^unit\s+[ivxlcdm\d]+\b$", body_text, re.IGNORECASE):
        return False
    title_words = re.findall(r"[A-Za-z]+", body_text)
    if (
        re.fullmatch(r"[A-Z][a-z]+(?:\s+[A-Z])?(?:\s+[A-Z][a-z]+)", body_text)
        and not any(word.lower() in _SAFE_TITLE_WORDS for word in title_words)
    ):
        return False
    body = body_text.lower()
    if body in _NOISE_TOPIC_BODY_EXACT:
        return False
    normalized_body = re.sub(r"[^a-z0-9]+", " ", body).strip()
    if any(phrase in normalized_body for phrase in _NOISE_TOPIC_PHRASES):
        return False
    if re.search(r"(?:https?://|www\.|\.edu\b|@)", lower):
        return False
    if re.search(r"\bb\s*tech\b|\bsyllahus\b|\bsyllabus\b", normalized_body):
        return False
    if re.match(r"^bh\s*\d+", normalized_body):
        return False
    if re.match(r"^\d+\s+[a-z]", body):
        return False
    if _BROKEN_COURSE_CODE_PATTERN.search(text):
        return False
    if body.startswith(_NOISE_TOPIC_PREFIXES):
        return False
    if re.search(r"\btextbooks?\b|\breference books?\b", body):
        return False
    if any(hint in normalized_body for hint in _BOOKISH_HINTS):
        return False
    if re.search(r"\b(?:pvt|ltd|edition|isbn|publishers?|university|college|hyderabad)\b", normalized_body):
        return False
    if re.search(r"\b(?:19|20)\d{2}\b", normalized_body):
        return False
    if (
        len(body_words := [w for w in re.split(r"\s+", re.sub(r"[^A-Za-z0-9 ]", " ", body)) if w]) >= 7
        and _OUTCOME_VERB_PATTERN.search(normalized_body)
        and not any(hint in normalized_body for hint in _TECHNICAL_TOPIC_HINTS)
    ):
        return False
    if (
        3 <= len(body_words) <= 5
        and "and" in {word.lower() for word in body_words}
        and all(word.lower() == "and" or word[:1].isupper() for word in body_words)
        and not any(word.lower() in _SAFE_TITLE_WORDS for word in body_words)
    ):
        return False
    if re.fullmatch(r"[\d\W_]+", body):
        return False
    if len(re.findall(r"[A-Za-z]{3,}", body)) == 0:
        return False
    if subject_name and (
        _normalize_subject_key(text) == _normalize_subject_key(subject_name)
        or _normalize_subject_key(text) == _subject_alias_key(subject_name)
    ):
        return False
    if not body_words:
        return False
    if len(body_words) == 1:
        word = body_words[0].lower()
        if word in _NOISE_SINGLE_WORD_BODIES:
            return False
        if word not in _ALLOWED_SINGLE_WORD_BODIES:
            return False
    if len(body_words) < 2 and body_words[0].lower() in _NOISE_SINGLE_WORD_BODIES:
        return False
    if body_words[0].lower() in _FRAGMENT_STARTERS:
        return False
    if body_words[0].lower() in {"of", "and", "to", "for", "in", "with", "by", "on"} and len(body_words) < 4:
        return False
    if body_words[-1].lower() in _FRAGMENT_ENDINGS and len(body_words) <= 6:
        return False
    if len(body_words) >= 12 and re.search(
        r"\b(this|also|covers|apply|analyze|develop|examine|comprehend|explore|build|evaluate|carry out)\b",
        normalized_body,
    ):
        return False
    return True


def _merge_subject_topic_sources(
    robust_subjects: dict[str, list[str]],
    parser_subjects: list[dict[str, object]],
    *,
    max_topics_per_subject: int,
) -> list[dict[str, list[str]]]:
    merged: dict[str, list[str]] = {
        _clean_subject_name(name): _normalize_topic_items(list(topics), _clean_subject_name(name))
        for name, topics in robust_subjects.items()
        if _clean_subject_name(name) and _is_strong_subject_name(name)
    }
    key_to_name = {_normalize_subject_key(name): name for name in merged.keys()}
    alias_to_name = {_subject_alias_key(name): name for name in merged.keys() if _subject_alias_key(name)}

    for subject in parser_subjects:
        raw_name = _clean_subject_name(subject.get("name") or "")
        if not raw_name:
            continue
        raw_topics = [str(topic or "").strip() for topic in list(subject.get("topics") or [])]
        expanded_topics = _normalize_topic_items(raw_topics, raw_name)
        if not expanded_topics:
            continue

        key = _normalize_subject_key(raw_name)
        alias_key = _subject_alias_key(raw_name)
        target_name = key_to_name.get(key) or alias_to_name.get(alias_key)
        if target_name is None:
            # If robust parser already found subjects, do not create new subjects from classic parser.
            if merged:
                continue
            if not _is_strong_subject_name(raw_name):
                continue
            merged[raw_name] = []
            key_to_name[key] = raw_name
            if alias_key:
                alias_to_name[alias_key] = raw_name
            target_name = raw_name

        seen = {_topic_dedupe_key(topic) for topic in merged[target_name]}
        for topic in expanded_topics:
            if not _is_valid_topic_text(topic, target_name):
                continue
            topic_key = _topic_dedupe_key(topic)
            if topic_key in seen:
                continue
            seen.add(topic_key)
            merged[target_name].append(topic)
            if len(merged[target_name]) >= max_topics_per_subject:
                break

    return [{"name": name, "topics": topics} for name, topics in merged.items()]


def _should_prefer_classic_subjects(
    robust_subjects: dict[str, list[str]],
    parser_subjects: list[dict[str, object]],
) -> bool:
    if not parser_subjects:
        return False
    classic_with_codes = [
        item for item in parser_subjects if _COURSE_CODE_TOKEN_PATTERN.search(str(item.get("name") or ""))
    ]
    if not classic_with_codes:
        return False
    robust_count = sum(len(topics) for topics in robust_subjects.values())
    classic_count = sum(len(list(item.get("topics") or [])) for item in parser_subjects)
    if robust_count == 0:
        return True
    return robust_count >= max(classic_count * 2, classic_count + 20)


def _build_revision_entries_between(
    *,
    user_id: str,
    start_date: date,
    end_date: date,
    session_duration_mins: int,
    topics: list[Topic],
    subject_name_by_id: dict[str, str],
    study_entries: list[ScheduleEntry] | None = None,
) -> list[ScheduleEntry]:
    total_days = (end_date - start_date).days + 1
    if total_days < 4 or not topics:
        return []

    candidate_days = [
        start_date + timedelta(days=offset)
        for offset in range(6, total_days - 1, 7)
    ]
    if not candidate_days:
        candidate_days = [start_date + timedelta(days=max(1, total_days // 2))]

    topics_by_id = {topic.id: topic for topic in topics}
    ordered_review: list[tuple[Topic, int, date]] = []
    seen_units: set[tuple[str, int]] = set()
    if study_entries:
        sorted_entries = sorted(
            (entry for entry in study_entries if not entry.is_revision),
            key=lambda entry: (entry.scheduled_date, entry.start_time),
        )
        first_seen_by_unit: dict[tuple[str, int], tuple[Topic, date]] = {}
        for entry in sorted_entries:
            topic = topics_by_id.get(entry.topic_id)
            if not topic:
                continue
            unit_no = _topic_unit_number(topic.name)
            if unit_no is None:
                continue
            unit_key = (topic.subject_id, unit_no)
            if unit_key in first_seen_by_unit:
                continue
            first_seen_by_unit[unit_key] = (topic, entry.scheduled_date)
        for (subject_id, unit_no), (topic, first_day) in sorted(
            first_seen_by_unit.items(),
            key=lambda item: item[1][1],
        ):
            unit_key = (subject_id, unit_no)
            if unit_key in seen_units:
                continue
            seen_units.add(unit_key)
            ordered_review.append((topic, unit_no, first_day))
    else:
        review_topics = topics[:]
        random.shuffle(review_topics)
        for topic in review_topics:
            unit_no = _topic_unit_number(topic.name)
            if unit_no is None:
                continue
            unit_key = (topic.subject_id, unit_no)
            if unit_key in seen_units:
                continue
            seen_units.add(unit_key)
            ordered_review.append((topic, unit_no, start_date))

    slots = min(len(ordered_review), len(candidate_days))
    revision_entries: list[ScheduleEntry] = []
    topic_idx = 0
    for target_day in candidate_days:
        while topic_idx < len(ordered_review) and ordered_review[topic_idx][2] >= target_day:
            topic_idx += 1
        if topic_idx >= len(ordered_review):
            break
        topic, unit_no, _ = ordered_review[topic_idx]
        topic_idx += 1
        start_dt = datetime.combine(target_day, time(18, 0))
        end_dt = start_dt + timedelta(minutes=session_duration_mins)
        revision_entries.append(
            ScheduleEntry(
                user_id=user_id,
                topic_id=topic.id,
                subject_name=subject_name_by_id.get(topic.subject_id, "General"),
                topic_name=f"Revision: Unit {unit_no}",
                scheduled_date=target_day,
                start_time=start_dt.time(),
                end_time=end_dt.time(),
                duration_mins=session_duration_mins,
                priority_score=1.25,
                is_revision=1,
                completed=0,
            )
        )
        if len(revision_entries) >= slots:
            break

    return revision_entries


def _ics_escape(value: str) -> str:
    escaped = (value or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return escaped.replace("\n", "\\n")


def _ics_datetime(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%S")


def _schedule_entries_to_ics(entries: list[ScheduleEntry]) -> str:
    created_utc = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//StudyAssistant//Schedule Export//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Study Schedule",
    ]

    for entry in entries:
        start_dt = datetime.combine(entry.scheduled_date, entry.start_time)
        end_dt = datetime.combine(entry.scheduled_date, entry.end_time)
        status = "COMPLETED" if entry.completed else "CONFIRMED"
        summary = _ics_escape(f"{entry.subject_name}: {entry.topic_name}")
        description = _ics_escape(
            "Study Assistant session\\n"
            f"Subject: {entry.subject_name}\\n"
            f"Topic: {entry.topic_name}\\n"
            f"Duration: {int(entry.duration_mins)} mins"
        )

        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:schedule-{entry.id}@studyassistant.local",
                f"DTSTAMP:{created_utc}",
                f"DTSTART:{_ics_datetime(start_dt)}",
                f"DTEND:{_ics_datetime(end_dt)}",
                f"SUMMARY:{summary}",
                f"DESCRIPTION:{description}",
                f"STATUS:{status}",
                "END:VEVENT",
            ]
        )

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


@router.post("/generate", response_model=list[ScheduleEntryOut], status_code=201)
async def generate(payload: ScheduleGenerateRequest, db: AsyncSession = Depends(get_db)):
    """Generate (or regenerate) a study schedule for the date range."""
    user = await db.get(User, payload.user_id)
    if not user:
        raise HTTPException(404, "User not found")

    # Load subjects with topics
    result = await db.execute(
        select(Subject)
        .where(Subject.user_id == payload.user_id)
        .options(selectinload(Subject.topics))
    )
    subjects = list(result.scalars().unique().all())
    if not subjects:
        raise HTTPException(400, "No subjects found — add subjects and topics first.")

    if payload.no_ai_mode:
        blocks = generate_schedule_rule_based(
            user_id=payload.user_id,
            subjects=subjects,
            start_date=payload.start_date,
            end_date=payload.end_date,
            daily_hours=payload.daily_study_hours or user.daily_study_hours,
            daily_start=payload.daily_start_time,
            session_mins=payload.session_duration_mins,
            break_mins=payload.break_duration_mins,
            max_topics_per_day=payload.max_topics_per_day,
            distribute_across_range=False,
            ensure_full_coverage=True,
        )
    else:
        blocks = generate_schedule(
            user_id=payload.user_id,
            subjects=subjects,
            start_date=payload.start_date,
            end_date=payload.end_date,
            daily_hours=payload.daily_study_hours or user.daily_study_hours,
            daily_start=payload.daily_start_time,
            session_mins=payload.session_duration_mins,
            break_mins=payload.break_duration_mins,
            max_topics_per_day=payload.max_topics_per_day,
            avoid_topic_repeats=True,
            enforce_unit_sequence=True,
            distribute_across_range=True,
            ensure_full_coverage=True,
        )

    # Regeneration replaces the user's future plan so every pending topic can be rescheduled cleanly.
    await db.execute(
        delete(ScheduleEntry).where(
            ScheduleEntry.user_id == payload.user_id,
            ScheduleEntry.scheduled_date >= payload.start_date,
        )
    )
    entries = blocks_to_entries(payload.user_id, blocks)
    db.add_all(entries)
    await db.flush()

    # Reload to get server defaults
    generated_end_date = max(
        (entry.scheduled_date for entry in entries),
        default=payload.end_date,
    )
    q = (
        select(ScheduleEntry)
        .where(
            ScheduleEntry.user_id == payload.user_id,
            ScheduleEntry.scheduled_date >= payload.start_date,
            ScheduleEntry.scheduled_date <= generated_end_date,
        )
        .order_by(ScheduleEntry.scheduled_date, ScheduleEntry.start_time)
    )
    reloaded = await db.execute(q)
    return _sanitize_schedule_entries(list(reloaded.scalars().all()))


@router.post("/generate-manual", response_model=list[ScheduleEntryOut], status_code=201)
async def generate_manual(payload: ManualScheduleGenerateRequest, db: AsyncSession = Depends(get_db)):
    """Create/update topics from manual input and generate a chronological schedule."""
    user = await db.get(User, payload.user_id)
    if not user:
        raise HTTPException(404, "User not found")
    if not payload.topics:
        raise HTTPException(400, "topics list cannot be empty")

    if payload.clear_existing:
        await db.execute(delete(ScheduleEntry).where(ScheduleEntry.user_id == payload.user_id))

    subject_result = await db.execute(
        select(Subject)
        .where(Subject.user_id == payload.user_id)
        .options(selectinload(Subject.topics))
    )
    existing_subjects = list(subject_result.scalars().unique().all())
    subject_by_key = {
        _normalize_subject_key(subject.name): subject
        for subject in existing_subjects
    }

    used_topic_keys: set[tuple[str, str]] = set()
    topic_order = 0

    for item in payload.topics:
        subject_name = _clean_subject_name(item.subject)
        topic_name = _humanize_topic_text(item.topic)
        if not subject_name or not topic_name:
            continue

        if item.unit_or_chapter:
            unit_text = _humanize_topic_text(item.unit_or_chapter)
            if unit_text and not topic_name.lower().startswith(unit_text.lower()):
                topic_name = f"{unit_text}: {topic_name}"

        cleaned_topic_name, estimated_hours = _topic_name_and_estimated_hours(
            topic_name,
            default_hours=max((item.estimated_duration_mins or 0) / 60.0, 1.0),
        )
        if item.estimated_duration_mins is not None:
            estimated_hours = max(0.25, round(item.estimated_duration_mins / 60.0, 2))

        subject_key = _normalize_subject_key(subject_name)
        topic_key = _topic_dedupe_key(cleaned_topic_name)
        unique_key = (subject_key, topic_key)
        if unique_key in used_topic_keys:
            continue
        used_topic_keys.add(unique_key)

        subject = subject_by_key.get(subject_key)
        if subject is None:
            subject = Subject(
                user_id=payload.user_id,
                name=subject_name[:200],
                exam_date=None,
                priority=3.0,
                color="#4A90D9",
            )
            db.add(subject)
            await db.flush()
            subject_by_key[subject_key] = subject

        if any(_topic_dedupe_key(topic.name) == topic_key for topic in subject.topics):
            continue

        topic = Topic(
            subject_id=subject.id,
            name=cleaned_topic_name[:300],
            difficulty=0.5,
            estimated_hours=estimated_hours,
            order_index=topic_order,
        )
        db.add(topic)
        subject.topics.append(topic)
        topic_order += 1

    await db.flush()

    refreshed_subject_result = await db.execute(
        select(Subject)
        .where(Subject.user_id == payload.user_id)
        .options(selectinload(Subject.topics))
    )
    subjects = [subject for subject in refreshed_subject_result.scalars().unique().all() if subject.topics]
    if not subjects:
        raise HTTPException(400, "No valid manual topics found")

    # Use a long horizon and force coverage so all entered topics are scheduled.
    planning_end = payload.start_date + timedelta(days=365)
    blocks = generate_schedule_rule_based(
        user_id=payload.user_id,
        subjects=subjects,
        start_date=payload.start_date,
        end_date=planning_end,
        daily_hours=payload.daily_study_hours or user.daily_study_hours,
        daily_start=payload.daily_start_time,
        session_mins=payload.session_duration_mins,
        break_mins=payload.break_duration_mins,
        max_topics_per_day=payload.max_topics_per_day,
        distribute_across_range=False,
        split_long_topics=True,
        ensure_full_coverage=True,
    )

    await db.execute(
        delete(ScheduleEntry).where(
            ScheduleEntry.user_id == payload.user_id,
            ScheduleEntry.scheduled_date >= payload.start_date,
        )
    )
    entries = blocks_to_entries(payload.user_id, blocks)
    db.add_all(entries)
    await db.flush()

    if entries:
        generated_end_date = max(entry.scheduled_date for entry in entries)
    else:
        generated_end_date = payload.start_date

    generated = await db.execute(
        select(ScheduleEntry)
        .where(
            ScheduleEntry.user_id == payload.user_id,
            ScheduleEntry.scheduled_date >= payload.start_date,
            ScheduleEntry.scheduled_date <= generated_end_date,
        )
        .order_by(ScheduleEntry.scheduled_date, ScheduleEntry.start_time)
    )
    return _sanitize_schedule_entries(list(generated.scalars().all()))


@router.post(
    "/generate-from-syllabus-pdf",
    response_model=ScheduleFromSyllabusPdfOut,
    status_code=201,
)
async def generate_from_syllabus_pdf(
    user_id: str = Form(...),
    start_date: date = Form(...),
    end_date: date = Form(...),
    subject_name: str | None = Form(None),
    exam_date: date | None = Form(None),
    daily_start_time: time = Form(time(8, 0)),
    daily_study_hours: float | None = Form(None),
    session_duration_mins: int = Form(60),
    break_duration_mins: int = Form(15),
    default_topic_hours: float = Form(2.0),
    default_topic_difficulty: float = Form(0.5),
    unit_start: int = Form(1),
    unit_end: int = Form(5),
    max_topics_per_unit: int = Form(120),
    max_topics_per_day: int = Form(5),
    include_revisions: bool = Form(True),
    revision_days: int = Form(3),
    auto_generate_quizzes: bool = Form(True),
    quiz_difficulty: str = Form("medium"),
    quiz_questions: int = Form(5),
    no_ai_mode: bool = Form(False),
    import_all_subjects: bool = Form(True),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload syllabus PDF, extract Unit topics via LangChain chunking, and generate a timetable.
    """
    if start_date > end_date:
        raise HTTPException(400, "start_date must be on or before end_date")
    if unit_start < 1 or unit_end < unit_start:
        raise HTTPException(400, "Invalid unit range")
    if revision_days < 1 or revision_days > 14:
        raise HTTPException(400, "revision_days must be between 1 and 14")
    if max_topics_per_unit < 5 or max_topics_per_unit > 200:
        raise HTTPException(400, "max_topics_per_unit must be between 5 and 200")
    if max_topics_per_day < 1 or max_topics_per_day > 12:
        raise HTTPException(400, "max_topics_per_day must be between 1 and 12")
    if quiz_difficulty not in {"easy", "medium", "hard"}:
        raise HTTPException(400, "quiz_difficulty must be easy, medium, or hard")
    if quiz_questions < 1 or quiz_questions > 20:
        raise HTTPException(400, "quiz_questions must be between 1 and 20")

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Please upload a PDF file")

    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(400, "Uploaded PDF is empty")

    topics_by_unit: dict[int, list[str]] = {}
    topics_created_records: list[Topic] = []
    created_subject_ids: list[str] = []
    created_subject_names: list[str] = []
    topic_index = 0

    if import_all_subjects:
        # Prefer robust parser for better subject/topic reconstruction.
        text = extract_pdf_text_robust(raw_bytes)
        robust_subjects = parse_subjects_and_topics_robust(
            text,
            unit_start=unit_start,
            unit_end=unit_end,
            max_topics_per_subject=max_topics_per_unit,
        )
        parser_subjects = parse_subjects_and_topics(text)
        if _should_prefer_classic_subjects(robust_subjects, parser_subjects):
            parsed_subjects = parser_subjects
        else:
            parsed_subjects = _merge_subject_topic_sources(
                robust_subjects,
                parser_subjects,
                max_topics_per_subject=max_topics_per_unit,
            )
        if parsed_subjects:
            for parsed_idx, parsed_subject in enumerate(parsed_subjects):
                parsed_name = _clean_subject_name(parsed_subject.get("name") or "")
                if not parsed_name:
                    parsed_name = f"Subject {parsed_idx + 1}"
                subject = Subject(
                    user_id=user_id,
                    name=parsed_name[:200],
                    exam_date=exam_date,
                    priority=3.0,
                    color="#4A90D9",
                )
                db.add(subject)
                await db.flush()
                created_subject_ids.append(subject.id)
                created_subject_names.append(subject.name)

                seen_topics: set[str] = set()
                per_subject_count = 0
                topic_candidates = _expand_unit_only_topics(
                    [str(topic) for topic in parsed_subject.get("topics", [])]
                )
                for raw_topic in topic_candidates:
                    for topic_clean in _split_topic_candidates(raw_topic):
                        normalized_topic_name, estimated_hours = _topic_name_and_estimated_hours(
                            topic_clean,
                            max(default_topic_hours, 0.25),
                        )
                        topic_key = _topic_dedupe_key(normalized_topic_name)
                        if topic_key in seen_topics:
                            continue
                        seen_topics.add(topic_key)
                        topic_record = Topic(
                            subject_id=subject.id,
                            name=normalized_topic_name[:300],
                            difficulty=min(max(default_topic_difficulty, 0.0), 1.0),
                            estimated_hours=estimated_hours,
                            order_index=topic_index,
                        )
                        db.add(topic_record)
                        topics_created_records.append(topic_record)
                        topic_index += 1
                        per_subject_count += 1
                        if per_subject_count >= max_topics_per_unit:
                            break
                    if per_subject_count >= max_topics_per_unit:
                        break

            await db.flush()

    # Fallback to Unit-based import when subject parser doesn't yield usable data.
    if not topics_created_records:
        try:
            topics_by_unit = extract_unit_topics_from_pdf_with_langchain(
                raw_bytes,
                unit_start=unit_start,
                unit_end=unit_end,
                max_topics_per_unit=max_topics_per_unit,
            )
        except RuntimeError as exc:
            raise HTTPException(500, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(400, f"Could not parse syllabus PDF: {exc}") from exc

        if not topics_by_unit:
            raise HTTPException(
                400,
                f"No topics found between Unit {unit_start} and Unit {unit_end}.",
            )

        label = (subject_name or "").strip()
        if not label:
            label = (file.filename.rsplit(".", 1)[0] if file.filename else "").strip()
        if not label:
            label = "Uploaded Syllabus"

        subject = Subject(
            user_id=user_id,
            name=label[:200],
            exam_date=exam_date,
            priority=3.0,
            color="#4A90D9",
        )
        db.add(subject)
        await db.flush()
        created_subject_ids.append(subject.id)
        created_subject_names.append(subject.name)

        for unit in sorted(topics_by_unit.keys()):
            for topic in topics_by_unit[unit]:
                raw_topic_name = f"Unit {unit}: {topic}".strip()
                for topic_name in _split_topic_candidates(raw_topic_name):
                    normalized_topic_name, estimated_hours = _topic_name_and_estimated_hours(
                        topic_name,
                        max(default_topic_hours, 0.25),
                    )
                    topic_record = Topic(
                        subject_id=subject.id,
                        name=normalized_topic_name[:300],
                        difficulty=min(max(default_topic_difficulty, 0.0), 1.0),
                        estimated_hours=estimated_hours,
                        order_index=topic_index,
                    )
                    db.add(topic_record)
                    topics_created_records.append(topic_record)
                    topic_index += 1

        await db.flush()

    subject_scope = (
        select(Subject).where(Subject.id.in_(created_subject_ids))
        if created_subject_ids
        else select(Subject).where(Subject.user_id == user_id)
    )
    all_subjects_result = await db.execute(
        subject_scope.options(selectinload(Subject.topics))
    )
    all_subjects = list(all_subjects_result.scalars().unique().all())
    if not all_subjects:
        raise HTTPException(400, "No subjects found for schedule generation")
    subject_name_by_id = {subject.id: subject.name for subject in all_subjects}

    if no_ai_mode:
        blocks = generate_schedule_rule_based(
            user_id=user_id,
            subjects=all_subjects,
            start_date=start_date,
            end_date=end_date,
            daily_hours=daily_study_hours or user.daily_study_hours,
            daily_start=daily_start_time,
            session_mins=session_duration_mins,
            break_mins=break_duration_mins,
            max_topics_per_day=max_topics_per_day,
            distribute_across_range=False,
            ensure_full_coverage=True,
        )
    else:
        blocks = generate_schedule(
            user_id=user_id,
            subjects=all_subjects,
            start_date=start_date,
            end_date=end_date,
            daily_hours=daily_study_hours or user.daily_study_hours,
            daily_start=daily_start_time,
            session_mins=session_duration_mins,
            break_mins=break_duration_mins,
            max_topics_per_day=max_topics_per_day,
            avoid_topic_repeats=True,
            enforce_unit_sequence=True,
            distribute_across_range=True,
            ensure_full_coverage=True,
        )

    await db.execute(
        delete(ScheduleEntry).where(
            ScheduleEntry.user_id == user_id,
            ScheduleEntry.scheduled_date >= start_date,
        )
    )
    entries = blocks_to_entries(user_id, blocks)
    db.add_all(entries)
    await db.flush()

    revision_entries_added = 0
    if include_revisions and entries:
        revision_entries = _build_revision_entries_between(
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
            session_duration_mins=session_duration_mins,
            topics=topics_created_records,
            subject_name_by_id=subject_name_by_id,
            study_entries=entries,
        )
        if revision_entries:
            db.add_all(revision_entries)
            await db.flush()
            revision_entries_added = len(revision_entries)

    quizzes_generated = 0
    if auto_generate_quizzes and topics_created_records:
        topics_by_unit_bucket: dict[int, list[Topic]] = {}
        for topic in topics_created_records:
            unit_no = _topic_unit_number(topic.name)
            if unit_no is None or unit_no < unit_start or unit_no > unit_end:
                unit_no = unit_start
            topics_by_unit_bucket.setdefault(unit_no, []).append(topic)

        for unit_no in sorted(topics_by_unit_bucket.keys()):
            selected_topic = topics_by_unit_bucket[unit_no][0]
            await create_quiz(
                db,
                QuizGenerateRequest(
                    user_id=user_id,
                    topic_id=selected_topic.id,
                    difficulty=quiz_difficulty,
                    num_questions=quiz_questions,
                ),
            )
            quizzes_generated += 1

        await db.flush()

    generated_result = await db.execute(
        select(ScheduleEntry)
        .where(
            ScheduleEntry.user_id == user_id,
            ScheduleEntry.scheduled_date >= start_date,
            ScheduleEntry.scheduled_date <= end_date,
        )
        .order_by(ScheduleEntry.scheduled_date, ScheduleEntry.start_time)
    )
    generated_entries = list(generated_result.scalars().all())

    subject_name_out = (
        created_subject_names[0]
        if len(created_subject_names) == 1
        else f"Imported {len(created_subject_names)} subjects"
    )
    units_detected_out = sorted(topics_by_unit.keys()) if topics_by_unit else sorted(
        {
            unit_no
            for topic in topics_created_records
            for unit_no in [_topic_unit_number(topic.name)]
            if unit_no is not None and unit_start <= unit_no <= unit_end
        }
    )

    return {
        "subject_id": created_subject_ids[0] if created_subject_ids else "",
        "subject_name": subject_name_out,
        "unit_range": f"Unit {unit_start} to Unit {unit_end}",
        "units_detected": units_detected_out,
        "topics_created": topic_index,
        "revision_entries_added": revision_entries_added,
        "quizzes_generated": quizzes_generated,
        "schedule_entries": _sanitize_schedule_entries(generated_entries),
    }


@router.get("/{user_id}", response_model=list[ScheduleEntryOut])
async def get_schedule(user_id: str, db: AsyncSession = Depends(get_db)):
    """Get the full schedule for a user."""
    q = (
        select(ScheduleEntry)
        .where(ScheduleEntry.user_id == user_id)
        .order_by(ScheduleEntry.scheduled_date, ScheduleEntry.start_time)
    )
    result = await db.execute(q)
    return _sanitize_schedule_entries(list(result.scalars().all()))


@router.get("/export/{user_id}")
async def export_schedule_calendar(user_id: str, db: AsyncSession = Depends(get_db)):
    """Export user schedule as an iCalendar (.ics) file for Google/Outlook import."""
    q = (
        select(ScheduleEntry)
        .where(ScheduleEntry.user_id == user_id)
        .order_by(ScheduleEntry.scheduled_date, ScheduleEntry.start_time)
    )
    result = await db.execute(q)
    entries = _sanitize_schedule_entries(list(result.scalars().all()))
    if not entries:
        raise HTTPException(404, "No schedule found to export")

    ics_content = _schedule_entries_to_ics(entries)
    safe_user_id = re.sub(r"[^a-zA-Z0-9_-]", "_", user_id)
    filename = f"study_schedule_{safe_user_id}.ics"
    return Response(
        content=ics_content,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.patch("/complete/{entry_id}")
async def complete_entry(entry_id: str, db: AsyncSession = Depends(get_db)):
    """Mark a schedule entry as completed."""
    entry = await db.get(ScheduleEntry, entry_id)
    if not entry:
        raise HTTPException(404, "Schedule entry not found")
    entry.completed = 1
    # Log progress for the topic if present
    if entry.topic_id:
        topic = await db.get(Topic, entry.topic_id)
        if topic:
            session_mins = entry.duration_mins or 60
            # Mark topic as fully completed when the scheduled study session is done
            new_completion = 100.0
            topic.completed = 1
            await record_progress(
                db,
                ProgressUpdate(
                    user_id=entry.user_id,
                    topic_id=entry.topic_id,
                    completion_pct=new_completion,
                    time_spent_mins=session_mins,
                    notes="Session completed via schedule",
                ),
            )
    await db.flush()
    return {"status": "completed", "entry_id": entry_id}


@router.post("/skip/{entry_id}", response_model=ScheduleRescheduleOut)
async def skip_and_reschedule(entry_id: str, db: AsyncSession = Depends(get_db)):
    """Skip a schedule entry and move it to the next available day/time slot."""
    entry = await db.get(ScheduleEntry, entry_id)
    if not entry:
        raise HTTPException(404, "Schedule entry not found")

    if entry.completed:
        raise HTTPException(400, "Completed session cannot be skipped")

    base_start = datetime.combine(entry.scheduled_date, entry.start_time)
    base_end = datetime.combine(entry.scheduled_date, entry.end_time)
    duration = base_end - base_start
    if duration.total_seconds() <= 0:
        duration = timedelta(minutes=int(entry.duration_mins or 60))

    new_day = entry.scheduled_date + timedelta(days=1)

    while True:
        existing_q = (
            select(ScheduleEntry)
            .where(
                ScheduleEntry.user_id == entry.user_id,
                ScheduleEntry.scheduled_date == new_day,
            )
            .order_by(ScheduleEntry.start_time)
        )
        existing_result = await db.execute(existing_q)
        existing = list(existing_result.scalars().all())

        chosen_start = entry.start_time
        chosen_end = (datetime.combine(new_day, chosen_start) + duration).time()

        overlaps = any(
            chosen_start < e.end_time and chosen_end > e.start_time
            for e in existing
        )
        if not overlaps:
            break

        if existing:
            last_end = existing[-1].end_time
            chosen_start = (
                datetime.combine(new_day, last_end) + timedelta(minutes=10)
            ).time()
            chosen_end = (datetime.combine(new_day, chosen_start) + duration).time()
            overlaps = any(
                chosen_start < e.end_time and chosen_end > e.start_time
                for e in existing
            )
            if not overlaps:
                break

        new_day += timedelta(days=1)

    new_entry = ScheduleEntry(
        user_id=entry.user_id,
        topic_id=entry.topic_id,
        subject_name=entry.subject_name,
        topic_name=entry.topic_name,
        scheduled_date=new_day,
        start_time=chosen_start,
        end_time=chosen_end,
        duration_mins=entry.duration_mins,
        priority_score=min((entry.priority_score or 0) + 0.1, 1.5),
        is_revision=1,
        completed=0,
    )
    db.add(new_entry)

    await db.delete(entry)
    await db.flush()
    await db.refresh(new_entry)

    return {
        "status": "skipped_rescheduled",
        "skipped_entry_id": entry_id,
        "rescheduled_entry": new_entry,
    }
