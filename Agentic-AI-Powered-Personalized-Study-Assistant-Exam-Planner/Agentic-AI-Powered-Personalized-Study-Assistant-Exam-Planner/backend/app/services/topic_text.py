"""Shared text normalization helpers for OCR-derived topic strings."""

from __future__ import annotations

import re

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

_SUBS: list[tuple[str, str, int]] = [
    (r"\bUnit\s*-\s*([IVXLC]+)\b", r"Unit \1", re.IGNORECASE),
    (r"\bUnit\s+VL\b", "Unit V", re.IGNORECASE),
    (r"\bUnit\s+V1\b", "Unit VI", re.IGNORECASE),
    (r"\bUnit\s+Ill\b", "Unit III", re.IGNORECASE),
    (r"\bUnit\s+IIC\b", "Unit II", re.IGNORECASE),
    (r"\bUnit\s+I[VXLC]+C\b", "Unit II", re.IGNORECASE),
    (r"([a-z])([A-Z])", r"\1 \2", 0),
    (r"^\s*ntroduction\b", "Introduction", re.IGNORECASE),
    (r"([A-Za-z])(\d)", r"\1 \2", 0),
    (r"(\d)([A-Za-z])", r"\1 \2", 0),
    (r"([A-Za-z]{3,})(of|for|in|to|and|with|from|into|over|under|between)(?=[A-Z])", r"\1 \2", re.IGNORECASE),
    (r"([A-Za-z]{3,})(of|for|in|to|and|with|from|into|over|under|between)(?=\s+[A-Z])", r"\1 \2", re.IGNORECASE),
    (r"([a-z])([A-Z][a-z])", r"\1 \2", 0),
    (r"\b[Il]o\s*T\b", "IoT", re.IGNORECASE),
    (r"\blmplementation\b", "Implementation", 0),
    (r"\bScnsors\b", "Sensors", re.IGNORECASE),
    (r"\bRaspherry\b", "Raspberry", re.IGNORECASE),
    (r"\bAnalytis\b", "Analytics", re.IGNORECASE),
    (r"\banguage\b", "Language", re.IGNORECASE),
    (r"ataloging", "Cataloging", re.IGNORECASE),
    (r"Iflation", "Inflation", re.IGNORECASE),
    (r"andstatistics", "and statistics", re.IGNORECASE),
    (r"andcompiler", "and compiler", re.IGNORECASE),
    (r"andanalytics", "and analytics", re.IGNORECASE),
    (r"andvisualization", "and visualization", re.IGNORECASE),
    (r"datavisualization", "data visualization", re.IGNORECASE),
    (r"anduse", "and use", re.IGNORECASE),
    (r"Piboards", "Pi boards", re.IGNORECASE),
    (r"Multidiscipl\s+inary", "Multidisciplinary", re.IGNORECASE),
    (r"Determ\s+ination", "Determination", re.IGNORECASE),
    (r"ofsyntax", "of syntax", re.IGNORECASE),
    (r"andlanguagemodels", "and language models", re.IGNORECASE),
    (r"Applyregression", "Apply regression", re.IGNORECASE),
    (r"todata", "to data", re.IGNORECASE),
    (r"evaluateper\s*formance", "evaluate performance", re.IGNORECASE),
    (r"Buildsupervised", "Build supervised", re.IGNORECASE),
    (r"andunsupervised", "and unsupervised", re.IGNORECASE),
    (r"ingmodels", "ing models", re.IGNORECASE),
    (r"forobjectivesegmentation", "for objective segmentation", re.IGNORECASE),
    (r"Buildmodels", "Build models", re.IGNORECASE),
    (r"fortimeseries", "for time series", re.IGNORECASE),
    (r"evaluateitsper\s*formance", "evaluate its performance", re.IGNORECASE),
    (r"lo\s*Tapplications", "IoT applications", re.IGNORECASE),
    (r"\bDem\s+and\s+And\b", "Demand And", re.IGNORECASE),
    (r"\bDat\s+Handling\b", "Data Handling", re.IGNORECASE),
    (r"\bLogisti\b", "Logistic", re.IGNORECASE),
    (r"\bIo\s*Twith\b", "IoT with", re.IGNORECASE),
    (r"\bSDNforIo\s*T\b", "SDN for IoT", re.IGNORECASE),
    (r"\bofIo\s*T\b", "of IoT", re.IGNORECASE),
    (r"\bfromgeneratedmodel\b", "from generated model", re.IGNORECASE),
    (r"\btoprovide\b", "to provide", re.IGNORECASE),
    (r"\bAftercompletion\b", "After completion", re.IGNORECASE),
    (r"\bstudentswill\b", "students will", re.IGNORECASE),
    (r"\bthecourseare\b", "the course are", re.IGNORECASE),
    (r"\bthecourse\b", "the course", re.IGNORECASE),
    (r"\bDevclopaclcarcomprehcnsion\b", "Develop a clear comprehension", re.IGNORECASE),
    (r"conta\s+ins", "contains", re.IGNORECASE),
    (r"unsupervisedmodels", "unsupervised models", re.IGNORECASE),
    (r"differentmorphological", "different morphological", re.IGNORECASE),
    (r"Knowledgeaboutdatnh", "Knowledge about data", re.IGNORECASE),
    (r"Ste\s+inbach", "Steinbach", re.IGNORECASE),
    (r"\bPiwith\b", "Pi with", re.IGNORECASE),
    (r"\bwithbasic\b", "with basic", re.IGNORECASE),
    (r"\bbasicperipherals\b", "basic peripherals", re.IGNORECASE),
    (r"\btovarious\b", "to various", re.IGNORECASE),
    (r"\bRulesfor\b", "Rules for", re.IGNORECASE),
    (r"\bPer\s+for\s+mances\b", "Performances", re.IGNORECASE),
    (r"\bper\s+for\s+mance\b", "performance", re.IGNORECASE),
    (r"\bPro\s+to\s+cols\b", "Protocols", re.IGNORECASE),
    (r"\bMoni\s+to\s+ring\b", "Monitoring", re.IGNORECASE),
    (r"\bAnalyticsapplications\b", "Analytics applications", re.IGNORECASE),
    (r"\bBluepropertyassumptions\b", "BLUE property assumptions", re.IGNORECASE),
    (r"\bLastquare\b", "Least Square", re.IGNORECASE),
    (r"\bnon\s*-\s*linearregression\b", "Non-linear regression", re.IGNORECASE),
    (r"\bSDNfor[Il]o\s*T\b", "SDN for IoT", re.IGNORECASE),
    (r"\bof[Il]o\s*Twith\b", "of IoT with", re.IGNORECASE),
    (r"\bof[Il]o\s*T\b", "of IoT", re.IGNORECASE),
    (r"([a-z]{3,})(with|for|to|and|of)([a-z]{3,})", r"\1 \2 \3", re.IGNORECASE),
]

_OCR_JOIN_SUBS: list[tuple[str, str]] = [
    (r"\bProcess\s+ing\b", "Processing"),
    (r"\bFind\s+ing\b", "Finding"),
    (r"\bSens\s+ing\b", "Sensing"),
    (r"\bPars\s+ing\b", "Parsing"),
    (r"\bLearn\s+ing\b", "Learning"),
    (r"\bNetwork\s+ing\b", "Networking"),
    (r"\bprogramm\s+ing\b", "programming"),
    (r"\bComput\s+ing\b", "Computing"),
    (r"\bAccount\s+ing\b", "Accounting"),
    (r"\bDef\s+inition\b", "Definition"),
    (r"\bMach\s+ine\b", "Machine"),
    (r"\bRein\s+forcement\b", "Reinforcement"),
    (r"\bArdu\s+ino\b", "Arduino"),
    (r"\bActua\s+tors\b", "Actuators"),
    (r"\bInterfac\s+ing\b", "Interfacing"),
    (r"\bDisjo\s+int\b", "Disjoint"),
    (r"\bAsymp\s+totic\b", "Asymptotic"),
    (r"\bVec\s+tor\b", "Vector"),
    (r"\bDoma\s+in\b", "Domain"),
    (r"\bColor\s+ing\b", "Coloring"),
    (r"\bschedul\s+ing\b", "scheduling"),
    (r"\bhami\s+ltonian\b", "hamiltonian"),
    (r"\bmainta\s+in\s+ing\b", "maintaining"),
    (r"\bPost\s+ing\b", "Posting"),
    (r"\bBus\s+iness\b", "Business"),
    (r"\bDoma\s+ins\b", "Domains"),
    (r"\bMultil\s+ingual\b", "Multilingual"),
    (r"\bSoftwaredef\s+ined\b", "Software defined"),
    (r"\bdef\s+ined\b", "defined"),
    (r"\bHandl\s+ing\b", "Handling"),
    (r"\bMoni\s+tor\s+ing\b", "Monitoring"),
    (r"\bPer\s+formances\b", "Performances"),
    (r"\bPro\s+tocols\b", "Protocols"),
    (r"\bforlo\s*T\b", "for IoT"),
    (r"\bPiwithbasicperipherals\b", "Pi with basic peripherals"),
    (r"\bUser Search Techniques\b", "Text Search Techniques"),
    (r"\bDat Handling\b", "Data Handling"),
    (r"\bdefined Networking\s*\(SDN\)", "Software defined Networking (SDN)"),
    (r"\bDatalike\b", "Data like"),
    (r"\bHis\s+tory\b", "History"),
    (r"\bMethods\s*of\b", "Methods of"),
    (r"\bETL\s*approach\b", "ETL approach"),
    (r"\bExtract\s*features\b", "Extract features"),
    (r"\bAverage\s*Energy\s*etc\b", "Average Energy etc"),
]

_DIRECT_REPLACEMENTS: list[tuple[str, str]] = [
    ("ataloging", "Cataloging"),
    ("Iflation", "Inflation"),
    ("Featuresand", "Features and"),
    ("per for mance", "performance"),
    ("per formance", "performance"),
]


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


def _normalize_unit_prefixes(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        value = _roman_to_int(match.group(1))
        if value is None:
            return match.group(0)
        return f"Unit {value}"

    return re.sub(r"\bUnit\s+([IVXLC\d]+)\b", repl, text, flags=re.IGNORECASE)


def humanize_topic_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "").strip())
    cleaned = cleaned.translate(_UNICODE_ROMAN_MAP)
    cleaned = cleaned.replace("，", ",")
    for pattern, replacement, flags in _SUBS:
        cleaned = re.sub(pattern, replacement, cleaned, flags=flags)
    for pattern, replacement in _OCR_JOIN_SUBS:
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
    # Generic OCR split joins such as "def inition" -> "definition".
    cleaned = re.sub(
        r"\b([A-Za-z]{3,})\s+(ing|ion|ions|ive|ity|ment|ments|able|ance|ances|ness|tor|tors|tive|tic|ical)\b",
        r"\1\2",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s*&\s*", " & ", cleaned)
    cleaned = re.sub(r"\s*\(\s*", " (", cleaned)
    cleaned = re.sub(r"\s*\)\s*", ") ", cleaned)
    cleaned = re.sub(r"\s*,\s*", ", ", cleaned)
    cleaned = re.sub(r"\s*:\s*", ": ", cleaned)
    cleaned = re.sub(r"\s*-\s*", " - ", cleaned)
    for source, target in _DIRECT_REPLACEMENTS:
        cleaned = re.sub(
            rf"(?<![A-Za-z]){re.escape(source)}(?![A-Za-z])",
            target,
            cleaned,
            flags=re.IGNORECASE,
        )
    cleaned = re.sub(r"\bLearning models\b", "learning models", cleaned)
    cleaned = re.sub(r"\b(\w+)(?:\s+\1\b)+", r"\1", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" .,-")


def split_period_topic_list(text: str) -> list[str]:
    candidate = text.strip(" .,-")
    if not candidate or candidate.count(".") < 1:
        return [candidate] if candidate else []

    parts = [p.strip(" .,-") for p in re.split(r"\s*\.\s*", candidate) if p.strip(" .,-")]
    if len(parts) <= 1:
        return [candidate]
    joined_without_spaces = bool(re.search(r"[A-Za-z]\.[A-Za-z]", candidate))
    if joined_without_spaces and len(parts) <= 8 and all(1 <= len(part.split()) <= 10 for part in parts):
        return parts
    if (
        len(parts) <= 8
        and all(1 <= len(part.split()) <= 10 for part in parts)
        and any(len(part.split()) >= 2 for part in parts)
    ):
        return parts
    return [candidate]


def topic_dedupe_key(text: str) -> str:
    normalized = _normalize_unit_prefixes(humanize_topic_text(text))
    return re.sub(r"[^a-z0-9]+", "", normalized.lower())


_DURATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(\d{1,3})\s*(?:h|hr|hrs|hour|hours)\b", re.IGNORECASE),
    re.compile(r"\b(\d{1,3})\s*(?:m|min|mins|minute|minutes)\b", re.IGNORECASE),
)


def strip_duration_from_topic(text: str) -> tuple[str, int | None]:
    """Extract explicit duration from topic text and return cleaned topic text + minutes."""
    candidate = humanize_topic_text(text)
    found_hours: int | None = None
    found_mins: int | None = None

    hour_match = _DURATION_PATTERNS[0].search(candidate)
    if hour_match:
        found_hours = int(hour_match.group(1))

    minute_match = _DURATION_PATTERNS[1].search(candidate)
    if minute_match:
        found_mins = int(minute_match.group(1))

    total_minutes: int | None = None
    if found_hours is not None or found_mins is not None:
        total_minutes = (found_hours or 0) * 60 + (found_mins or 0)
        total_minutes = max(total_minutes, 10)
        candidate = re.sub(
            r"[\[(]?\s*\d{1,3}\s*(?:h|hr|hrs|hour|hours|m|min|mins|minute|minutes)\s*[\])]?",
            " ",
            candidate,
            flags=re.IGNORECASE,
        )
        candidate = re.sub(r"\s*[-:,]\s*$", "", candidate).strip()

    return humanize_topic_text(candidate), total_minutes


def estimate_topic_duration_hours(topic_name: str, fallback_hours: float = 2.0) -> float:
    """Estimate study duration from topic complexity if explicit duration is unavailable."""
    cleaned = humanize_topic_text(topic_name)
    words = [w for w in re.findall(r"[A-Za-z0-9]+", cleaned) if len(w) > 1]
    word_count = len(words)

    if word_count <= 4:
        estimate = 1.0
    elif word_count <= 9:
        estimate = 1.5
    elif word_count <= 15:
        estimate = 2.0
    elif word_count <= 22:
        estimate = 2.5
    else:
        estimate = 3.0

    if fallback_hours > 0:
        estimate = max(estimate, min(fallback_hours, 4.0) * 0.75)

    return max(0.5, round(estimate, 2))
