"""
Quiz Generation & Evaluation Engine
====================================
Generates level-wise quizzes for topics and evaluates student responses.

For the rule-based provider the engine uses a template-based approach with
pre-defined question banks. When an LLM provider is configured it can
delegate to an external API.
"""

from __future__ import annotations

import json
import logging
import random
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.app.config import get_settings
from backend.app.models.quiz import Quiz, QuizQuestion, QuizAttempt
from backend.app.models.quiz_performance import QuizPerformance
from backend.app.models.topic import Topic
from backend.app.models.subject import Subject
from backend.app.models.progress import ProgressRecord
from backend.app.models.schedule import ScheduleEntry
from backend.app.schemas.quiz import (
    QuizGenerateRequest,
    QuizSubmitRequest,
    QuizResult,
)


_UNIT_PREFIX_RE = re.compile(r"^\s*(Unit\s+[IVXLC\d]+)\s*:\s*(.+)$", re.IGNORECASE)
_PART_SPLIT_RE = re.compile(r"\s*(?:,|;|\||/|&|\band\b)\s*", re.IGNORECASE)
_GENERIC_DISTRACTORS = [
    "Unrelated historical timeline",
    "Random memorization without concept understanding",
    "General exam instructions only",
    "An unrelated field outside this subject",
    "Skipping core definitions and models",
    "A topic from a different unit context",
]

PASS_THRESHOLDS = {
    "easy": 75.0,
    "medium": 75.0,
    "hard": 75.0,
}
logger = logging.getLogger(__name__)
settings = get_settings()


def _strip_unit_prefix(topic_name: str) -> tuple[str, str | None]:
    match = _UNIT_PREFIX_RE.match(topic_name or "")
    if not match:
        return (str(topic_name or "").strip(), None)
    return (match.group(2).strip(), match.group(1).strip())


def _normalize_phrase(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "").strip())
    return cleaned.strip(" .,-:")


def _normalize_question_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip()).lower()


def _split_topic_parts(topic_name: str) -> list[str]:
    body, _ = _strip_unit_prefix(topic_name)
    parts: list[str] = []
    for candidate in _PART_SPLIT_RE.split(body):
        phrase = _normalize_phrase(candidate)
        if not phrase:
            continue
        if len(phrase.split()) < 2:
            continue
        parts.append(phrase)
    if not parts and body:
        parts = [body]
    seen: set[str] = set()
    deduped: list[str] = []
    for part in parts:
        key = re.sub(r"[^a-z0-9]+", "", part.lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(part)
    return deduped


def _build_options(correct: str, distractors: list[str]) -> tuple[dict[str, str], str]:
    unique_distractors: list[str] = []
    seen = {re.sub(r"[^a-z0-9]+", "", correct.lower())}
    for item in distractors:
        text = _normalize_phrase(item)
        if not text:
            continue
        key = re.sub(r"[^a-z0-9]+", "", text.lower())
        if key in seen:
            continue
        seen.add(key)
        unique_distractors.append(text)
    for fallback in _GENERIC_DISTRACTORS:
        if len(unique_distractors) >= 3:
            break
        key = re.sub(r"[^a-z0-9]+", "", fallback.lower())
        if key not in seen:
            seen.add(key)
            unique_distractors.append(fallback)

    options = [correct] + unique_distractors[:3]
    random.shuffle(options)
    labels = ["A", "B", "C", "D"]
    option_map = {labels[idx]: options[idx] for idx in range(4)}
    correct_letter = next(label for label, value in option_map.items() if value == correct)
    return option_map, correct_letter


def _topic_grounded_mcq(
    *,
    stem: str,
    correct: str,
    distractors: list[str],
    explanation: str,
    order_index: int,
) -> dict[str, Any]:
    option_map, answer = _build_options(correct, distractors)
    return {
        "question_text": stem,
        "option_a": option_map["A"],
        "option_b": option_map["B"],
        "option_c": option_map["C"],
        "option_d": option_map["D"],
        "correct_answer": answer,
        "explanation": explanation,
        "order_index": order_index,
    }


def _generate_questions(topic_name: str, difficulty: str, count: int) -> list[dict]:
    """Utility for synchronous rule-based question generation."""
    return _generate_contextual_rule_based_questions(
        topic_name, difficulty, count, []
    )


def _generate_contextual_rule_based_questions(
    topic_name: str,
    difficulty: str,
    count: int,
    related_topics: list[str],
    used_questions: set[str] | None = None,
) -> list[dict]:
    """Generate topic-grounded MCQs without an LLM."""
    body, unit_label = _strip_unit_prefix(topic_name)
    topic_parts = _split_topic_parts(topic_name)
    related_clean = [_strip_unit_prefix(t)[0] for t in related_topics if t]
    related_parts: list[str] = []
    for related in related_topics:
        related_parts.extend(_split_topic_parts(related))

    if not topic_parts:
        topic_parts = [body or topic_name]

    generators: list[dict[str, Any]] = []

    core = topic_parts[0]
    generators.append(
        {
            "stem": f"In the context of '{body}', which concept is explicitly part of this topic?",
            "correct": core,
            "distractors": related_parts + related_clean + _GENERIC_DISTRACTORS,
            "explanation": f"'{core}' sits inside the scope of '{body}'.",
        }
    )

    # Difficulty-tuned stems added to avoid repetition across levels and better align rigor
    difficulty_profiles = {
        "easy": [
            {
                "stem": f"What is the primary definition associated with '{core}'?",
                "correct": f"The standard meaning of {core}",
                "distractors": [
                    "A tangential fun fact",
                    "An unrelated advanced theorem",
                    "A broad study strategy",
                ],
                "explanation": "Easy level checks core definition recall.",
            },
            {
                "stem": f"Select the most basic example of '{core}'.",
                "correct": f"A textbook example illustrating {core}",
                "distractors": related_clean[:2] + _GENERIC_DISTRACTORS,
                "explanation": "Examples anchor basic understanding.",
            },
        ],
        "medium": [
            {
                "stem": f"How would you apply '{core}' to solve a standard problem?",
                "correct": f"Use {core} directly following its usual steps",
                "distractors": [
                    "Use an unrelated topic",
                    "Skip prerequisites",
                    "Memorize without working the steps",
                ],
                "explanation": "Medium level checks application of known steps.",
            },
            {
                "stem": f"Which mistake is common when using '{core}'?",
                "correct": f"Forgetting a key condition when applying {core}",
                "distractors": [
                    "Citing a different subject",
                    "Writing only the answer without method",
                    "Ignoring the question prompt",
                ],
                "explanation": "Targets misconception detection.",
            },
        ],
        "hard": [
            {
                "stem": f"When analyzing a complex case, how does '{core}' interact with related topics?",
                "correct": f"It must be combined with {related_clean[0] if related_clean else 'its prerequisites'} under given constraints",
                "distractors": [
                    "It replaces all other methods automatically",
                    "It is irrelevant to advanced cases",
                    "It works without checking assumptions",
                ],
                "explanation": "Hard level checks integration and assumptions.",
            },
            {
                "stem": f"Given a failure scenario using '{core}', what is the best remediation?",
                "correct": f"Review the boundary conditions and adjust {core} accordingly",
                "distractors": [
                    "Abandon the topic entirely",
                    "Guess new values randomly",
                    "Switch to unrelated subjects",
                ],
                "explanation": "Hard level focuses on troubleshooting and refinement.",
            },
        ],
    }

    if unit_label:
        unit_token = unit_label.split()[-1]
        generators.append(
            {
                "stem": f"'{body}' is mapped to which unit in your syllabus?",
                "correct": unit_label,
                "distractors": [
                    f"Unit {int(unit_token) + 1}" if unit_token.isdigit() else "Unit II",
                    f"Unit {max(int(unit_token) - 1, 1)}" if unit_token.isdigit() else "Unit III",
                    "Unit X",
                ],
                "explanation": f"The syllabus tags this topic under {unit_label}.",
            }
        )

    focus_phrase = topic_parts[min(1, len(topic_parts) - 1)]
    mastery_verb = {
        "easy": "identify",
        "medium": "apply",
        "hard": "analyze",
    }.get(difficulty.lower(), "apply")
    generators.append(
        {
            "stem": f"Best learning outcome after studying '{body}' is to ______.",
            "correct": f"{mastery_verb} {focus_phrase} correctly in real problems",
            "distractors": [
                "Memorize only headings without understanding",
                "Ignore links to nearby topics",
                "Guess answers without revising",
            ],
            "explanation": f"Mastery means you can {mastery_verb} '{focus_phrase}', not just recall headings.",
        }
    )

    if related_clean:
        related_pick = related_clean[0]
        generators.append(
            {
                "stem": f"During revision of '{body}', which related topic should you connect for better retention?",
                "correct": related_pick,
                "distractors": topic_parts + _GENERIC_DISTRACTORS,
                "explanation": f"Linking to '{related_pick}' reinforces conceptual context.",
            }
        )

    generators.append(
        {
            "stem": f"What is the most effective way to revise '{body}' before an exam?",
            "correct": f"Break it into key parts ({', '.join(topic_parts[:2])}) and do active recall",
            "distractors": [
                "Skim once and avoid self-testing",
                "Only read solved answers from other subjects",
                "Skip it because it feels familiar",
            ],
            "explanation": "Chunking plus self-testing yields higher retention.",
        }
    )

    # Broader stem pool to reduce fallback/fill usage when many prior questions exist
    extra_generators = [
        {
            "stem": f"Which option directly belongs under '{body}'?",
            "correct": core,
            "distractors": related_clean[:2] + _GENERIC_DISTRACTORS,
            "explanation": f"'{core}' is central to '{body}'.",
        },
        {
            "stem": f"What is the first step when approaching a practice problem on '{body}'?",
            "correct": f"Identify the relevant concept: {core}",
            "distractors": [
                "Guess without reading the question",
                "Start with an unrelated topic",
                "Skip to the solution key immediately",
            ],
            "explanation": "Locating the core concept is the right starting point.",
        },
        {
            "stem": f"A common pitfall when revising '{body}' is:",
            "correct": "Memorizing steps without understanding conditions",
            "distractors": [
                "Checking worked examples",
                "Practicing spaced repetition",
                "Reviewing past mistakes",
            ],
            "explanation": "Shallow memorization leads to errors under variation.",
        },
        {
            "stem": f"To boost retention for '{body}', you should:",
            "correct": f"Connect it with {related_clean[0] if related_clean else 'its prerequisites'} and quiz yourself",
            "distractors": [
                "Avoid all practice questions",
                "Rely only on highlights",
                "Study unrelated chapters first",
            ],
            "explanation": "Linking related ideas plus self-testing improves recall.",
        },
        {
            "stem": f"In assessments, '{body}' is most likely evaluated by asking you to:",
            "correct": f"Apply {core} to a short scenario",
            "distractors": [
                "List unrelated trivia",
                "Describe an unrelated field",
                "Ignore given constraints",
            ],
            "explanation": "Assessments test applied understanding, not trivia.",
        },
    ]
    generators.extend(extra_generators)

    # Difficulty-flavored scenario/item
    generators.append(
        {
            "stem": f"You need to apply '{body}' in a real case study. What should you focus on first?",
            "correct": core,
            "distractors": related_clean[:2] + _GENERIC_DISTRACTORS,
            "explanation": f"Start with the core element '{core}' to structure the solution.",
        }
    )

    # Append difficulty-specific generators so they rotate into the selection loop
    generators.extend(difficulty_profiles.get(difficulty.lower(), []))

    questions: list[dict[str, Any]] = []
    used_norm = set(used_questions or set())
    seen_stems: set[str] = set()
    idx = 0
    attempts = 0
    max_attempts = max(count * 6, 15)

    while len(questions) < count and attempts < max_attempts:
        attempts += 1
        template = generators[idx % len(generators)]
        idx += 1
        stem = template["stem"]
        norm = _normalize_question_text(stem)
        if norm in used_norm:
            continue
        used_norm.add(norm)
        questions.append(
            _topic_grounded_mcq(
                stem=stem,
                correct=template["correct"],
                distractors=template["distractors"],
                explanation=template["explanation"],
                order_index=len(questions),
            )
        )

    # Guaranteed fill: if deduping exhausted the template pool (e.g., many prior quizzes), generate
    # numbered variants so the caller always receives the requested count.
    while len(questions) < count:
        suffix = len(questions) + 1
        stem = f"Key concept check {suffix} for '{body}'"
        questions.append(
            _topic_grounded_mcq(
                stem=stem,
                correct=core,
                distractors=related_clean[:2] + _GENERIC_DISTRACTORS,
                explanation="Additional variant generated to avoid repeating prior questions.",
                order_index=len(questions),
            )
        )

    return questions


async def _generate_questions_with_llm(
    topic_name: str,
    difficulty: str,
    count: int,
    related_topics: list[str],
    used_questions: set[str] | None = None,
) -> list[dict]:
    """Generate quiz items with an LLM provider if configured."""
    try:
        if settings.ai_provider == "openai" and settings.openai_api_key:
            return await _generate_questions_with_openai(
                topic_name, difficulty, count, related_topics, used_questions
            )

        if settings.ai_provider == "groq" and settings.groq_api_key:
            return await _generate_questions_with_groq(
                topic_name, difficulty, count, related_topics, used_questions
            )
    except Exception:
        logger.exception("LLM quiz generation failed; falling back to rule-based")

    return _generate_contextual_rule_based_questions(
        topic_name, difficulty, count, related_topics, used_questions
    )


async def _generate_questions_with_openai(
    topic_name: str,
    difficulty: str,
    count: int,
    related_topics: list[str],
    used_questions: set[str] | None = None,
) -> list[dict]:
    system_prompt = (
        "You generate high-quality, topic-grounded multiple-choice quiz questions for exam prep. "
        "Questions must verify true understanding of the exact topic, with plausible distractors and clear explanations. "
        "Return strict JSON only."
    )
    user_prompt = (
        f"Generate {count} {difficulty} multiple-choice questions for topic '{topic_name}'. "
        f"Related syllabus topics: {', '.join(related_topics[:6]) if related_topics else 'None'}. "
        "Questions must be specific to this topic from syllabus context and should test core concept recall, "
        "application, and misconception detection. "
        "Return JSON array where each item has keys: "
        "question_text, option_a, option_b, option_c, option_d, correct_answer, explanation. "
        "correct_answer must be one of A/B/C/D."
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-mini",
                    "temperature": 0.4,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                },
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
    except Exception:
        return _generate_contextual_rule_based_questions(
            topic_name, difficulty, count, related_topics
        )

    match = re.search(r"\[.*\]", content, re.DOTALL)
    if not match:
        return _generate_contextual_rule_based_questions(
            topic_name, difficulty, count, related_topics
        )

    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return _generate_contextual_rule_based_questions(
            topic_name, difficulty, count, related_topics
        )

    formatted: list[dict] = []
    seen_questions: set[str] = set()
    used = used_questions or set()
    for idx, item in enumerate(parsed):
        answer = str(item.get("correct_answer", "A")).upper()
        if answer not in {"A", "B", "C", "D"}:
            answer = "A"
        qtext = str(item.get("question_text", f"Question on {topic_name}")).strip()
        key = _normalize_question_text(qtext)
        if key in seen_questions or key in used:
            continue
        seen_questions.add(key)
        used.add(key)
        formatted.append(
            {
                "question_text": qtext,
                "option_a": str(item.get("option_a", "Option A")),
                "option_b": str(item.get("option_b", "Option B")),
                "option_c": str(item.get("option_c", "Option C")),
                "option_d": str(item.get("option_d", "Option D")),
                "correct_answer": answer,
                "explanation": str(item.get("explanation", "")),
                "order_index": len(formatted),
            }
        )
        if len(formatted) >= count:
            break

    if len(formatted) < count:
        fallback = _generate_contextual_rule_based_questions(
            topic_name, difficulty, count - len(formatted), related_topics, used
        )
        for item in fallback:
            item["order_index"] = len(formatted)
            formatted.append(item)

    return formatted


async def _generate_questions_with_groq(
    topic_name: str,
    difficulty: str,
    count: int,
    related_topics: list[str],
    used_questions: set[str] | None = None,
) -> list[dict]:
    """Generate questions through Groq's OpenAI-compatible chat completions API."""
    logger.info(
        "Groq quiz generation start topic=%s difficulty=%s count=%d",
        topic_name,
        difficulty,
        count,
    )
    system_prompt = (
        "You generate high-quality, topic-grounded multiple-choice quiz questions for exam prep. "
        "Questions must verify true understanding of the exact topic, with plausible distractors and clear explanations. "
        "Return strict JSON only."
    )
    user_prompt = (
        f"Generate {count} {difficulty} multiple-choice questions for topic '{topic_name}'. "
        f"Related syllabus topics: {', '.join(related_topics[:6]) if related_topics else 'None'}. "
        "Each item should include question_text, option_a, option_b, option_c, option_d, correct_answer, explanation. "
        "correct_answer must be one of A/B/C/D."
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.groq_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.groq_model,
                    "temperature": 0.4,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("choices"):
                logger.error("Groq response missing choices: %s", data)
                raise ValueError("Groq response missing choices array")
            content = data["choices"][0]["message"]["content"]
            logger.info("Groq response received length=%d", len(content or ""))
    except Exception as exc:
        body = None
        try:
            body = resp.text  # type: ignore[name-defined]
        except Exception:
            pass
        logger.exception("Groq quiz generation failed. Response body: %s", body)
        raise RuntimeError("Groq quiz generation failed") from exc

    match = re.search(r"\[.*\]", content, re.DOTALL)
    if not match:
        logger.warning("Groq content missing JSON array")
        raise ValueError("Groq response missing JSON array of questions")

    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        logger.warning("Groq JSON parse failed")
        raise ValueError("Groq response JSON parse failed")

    formatted: list[dict] = []
    seen_questions: set[str] = set()
    used = used_questions or set()
    for idx, item in enumerate(parsed):
        answer = str(item.get("correct_answer", "A")).upper()
        if answer not in {"A", "B", "C", "D"}:
            answer = "A"
        qtext = str(item.get("question_text", f"Question on {topic_name}")).strip()
        key = _normalize_question_text(qtext)
        if key in seen_questions or key in used:
            continue
        seen_questions.add(key)
        used.add(key)
        formatted.append(
            {
                "question_text": qtext,
                "option_a": str(item.get("option_a", "Option A")),
                "option_b": str(item.get("option_b", "Option B")),
                "option_c": str(item.get("option_c", "Option C")),
                "option_d": str(item.get("option_d", "Option D")),
                "correct_answer": answer,
                "explanation": str(item.get("explanation", "")),
                "order_index": len(formatted),
            }
        )
        if len(formatted) >= count:
            break

    if len(formatted) < count:
        fallback = _generate_contextual_rule_based_questions(
            topic_name, difficulty, count - len(formatted), related_topics, used
        )
        for item in fallback:
            item["order_index"] = len(formatted)
            formatted.append(item)

    return formatted


async def _create_review_session(
    db: AsyncSession,
    *,
    user_id: str,
    topic: Topic | None,
) -> bool:
    """Create a single revision schedule block on the next available day."""
    if not topic:
        return False

    subject = await db.get(Subject, topic.subject_id)
    subject_name = subject.name if subject else "General"
    base_start = time(19, 0)
    duration_mins = 60.0
    start_day = date.today() + timedelta(days=1)

    for day_offset in range(0, 14):
        proposed_day = start_day + timedelta(days=day_offset)
        start_dt = datetime.combine(proposed_day, base_start)
        end_dt = start_dt + timedelta(minutes=duration_mins)
        proposed_start = start_dt.time()
        proposed_end = end_dt.time()

        existing_q = (
            select(ScheduleEntry)
            .where(
                ScheduleEntry.user_id == user_id,
                ScheduleEntry.scheduled_date == proposed_day,
            )
            .order_by(ScheduleEntry.start_time)
        )
        existing_result = await db.execute(existing_q)
        existing = list(existing_result.scalars().all())

        overlaps = any(
            proposed_start < e.end_time and proposed_end > e.start_time for e in existing
        )
        if overlaps:
            continue

        review_entry = ScheduleEntry(
            user_id=user_id,
            topic_id=topic.id,
            subject_name=subject_name,
            topic_name=topic.name,
            scheduled_date=proposed_day,
            start_time=proposed_start,
            end_time=proposed_end,
            duration_mins=duration_mins,
            priority_score=1.2,
            is_revision=1,
            completed=0,
        )
        db.add(review_entry)
        return True

    return False


async def create_quiz(db: AsyncSession, req: QuizGenerateRequest) -> Quiz:
    """Generate a quiz for a given topic and difficulty."""
    topic = await db.get(Topic, req.topic_id)
    topic_name = topic.name if topic else "General"
    related_topics: list[str] = []
    if topic:
        related_q = (
            select(Topic.name)
            .where(Topic.subject_id == topic.subject_id, Topic.id != topic.id)
            .limit(10)
        )
        related_result = await db.execute(related_q)
        related_topics = [name for name in related_result.scalars().all() if name]

    # Avoid reusing recent questions for this user/topic
    existing_q = (
        select(QuizQuestion.question_text)
        .join(Quiz, QuizQuestion.quiz_id == Quiz.id)
        .where(Quiz.user_id == req.user_id, Quiz.topic_id == req.topic_id)
    )
    existing_result = await db.execute(existing_q)
    used_questions = {_normalize_question_text(q) for q in existing_result.scalars().all() if q}

    quiz = Quiz(
        user_id=req.user_id,
        topic_id=req.topic_id,
        difficulty=req.difficulty,
        total_questions=req.num_questions,
    )
    db.add(quiz)
    await db.flush()  # get quiz.id

    try:
        questions_data = await _generate_questions_with_llm(
            topic_name, req.difficulty, req.num_questions, related_topics, used_questions
        )
    except Exception:
        logger.exception("LLM + fallback generation failed; using minimal stub quiz")
        questions_data = [
            _topic_grounded_mcq(
                stem=f"Key idea from {topic_name}: pick the correct statement.",
                correct=topic_name,
                distractors=["Unrelated fact", "Another distractor", "Yet another"],
                explanation="Fallback question because quiz generation failed.",
                order_index=0,
            )
        ]

    for qd in questions_data:
        q = QuizQuestion(quiz_id=quiz.id, **qd)
        db.add(q)

    await db.flush()

    # Reload with questions
    result = await db.execute(
        select(Quiz).where(Quiz.id == quiz.id).options(selectinload(Quiz.questions))
    )
    return result.scalar_one()


async def evaluate_quiz(db: AsyncSession, req: QuizSubmitRequest) -> QuizResult:
    """Score submitted quiz answers and persist attempts."""
    quiz = await db.get(Quiz, req.quiz_id)
    assert quiz is not None, "Quiz not found"

    # Load questions
    q = select(QuizQuestion).where(QuizQuestion.quiz_id == quiz.id)
    result = await db.execute(q)
    questions = {qq.id: qq for qq in result.scalars().all()}

    correct = 0
    details: list[dict] = []

    for ans in req.answers:
        qq = questions.get(ans.question_id)
        if qq is None:
            continue
        is_correct = ans.answer.upper() == qq.correct_answer.upper()
        if is_correct:
            correct += 1

        attempt = QuizAttempt(
            quiz_id=quiz.id,
            question_id=ans.question_id,
            user_answer=ans.answer.upper(),
            is_correct=1 if is_correct else 0,
        )
        db.add(attempt)

        details.append({
            "question_id": ans.question_id,
            "your_answer": ans.answer,
            "correct_answer": qq.correct_answer,
            "is_correct": is_correct,
            "explanation": qq.explanation,
        })

    total = quiz.total_questions
    score_pct = (correct / total * 100) if total else 0.0
    quiz.score = score_pct
    difficulty = (quiz.difficulty or "medium").lower()
    threshold = PASS_THRESHOLDS.get(difficulty, PASS_THRESHOLDS["medium"])
    passed = score_pct >= threshold
    await _record_quiz_performance(db, req.user_id, difficulty, score_pct)

    topic = await db.get(Topic, quiz.topic_id)
    review_created = False
    recommendation = "Good work. Continue with the next topic."

    # Also record in progress
    progress = ProgressRecord(
        user_id=req.user_id,
        topic_id=quiz.topic_id,
        quiz_score=score_pct,
        time_spent_mins=0,
        completion_pct=topic.completion_pct if topic else 0,
        notes=f"Quiz {difficulty} score: {round(score_pct, 1)}%",
    )
    db.add(progress)

    if topic:
        topic.last_reviewed = datetime.now(timezone.utc)

    if not passed:
        recommendation = (
            "Score below target. Read this topic again, then retake a quiz."
        )
        review_created = await _create_review_session(
            db, user_id=req.user_id, topic=topic
        )
        if topic:
            topic.completed = 0
            topic.completion_pct = max(topic.completion_pct - 10.0, 0.0)
    elif topic and topic.completion_pct < 100:
        topic.completion_pct = min(topic.completion_pct + 5.0, 100.0)
        if topic.completion_pct >= 100:
            topic.completed = 1

    await db.flush()

    return QuizResult(
        quiz_id=quiz.id,
        total_questions=total,
        correct_count=correct,
        score_pct=round(score_pct, 1),
        passed=passed,
        pass_threshold=threshold,
        recommendation=recommendation,
        review_session_created=review_created,
        details=details,
    )


async def _record_quiz_performance(
    db: AsyncSession, user_id: str, difficulty: str, score_pct: float
) -> None:
    stmt = (
        select(QuizPerformance)
        .where(
            QuizPerformance.user_id == user_id,
            QuizPerformance.difficulty == difficulty,
        )
        .with_for_update()
    )
    result = await db.execute(stmt)
    perf = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if perf:
        prev_attempts = perf.attempts or 0
        perf.attempts = prev_attempts + 1
        perf.last_score = score_pct
        perf.best_score = max(perf.best_score or 0.0, score_pct)
        prev_avg = perf.average_score or 0.0
        perf.average_score = (
            (prev_avg * prev_attempts + score_pct) / perf.attempts
            if perf.attempts
            else score_pct
        )
        perf.last_attempted = now
    else:
        perf = QuizPerformance(
            user_id=user_id,
            difficulty=difficulty,
            attempts=1,
            best_score=score_pct,
            average_score=score_pct,
            last_score=score_pct,
            last_attempted=now,
        )
        db.add(perf)
