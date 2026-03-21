"""Mind map graph construction from subjects and topics."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import re

from backend.app.models.subject import Subject
from backend.app.models.topic import Topic
from backend.app.services.topic_text import humanize_topic_text

UNIT_PATTERN = re.compile(
    r"^(unit|module|chapter|part|section)\s+([a-z0-9ivxlcdm]+)\s*[:\-–—]\s*(.+)$",
    re.IGNORECASE,
)
HIERARCHY_PATTERN = re.compile(r"\s(?:->|→|—|–|-|/|\|)\s")
TOKEN_PATTERN = re.compile(r"[a-z0-9]{3,}")
STOPWORDS = {
    "about",
    "after",
    "analysis",
    "basic",
    "basics",
    "concept",
    "concepts",
    "data",
    "introduction",
    "overview",
    "study",
    "subject",
    "system",
    "topic",
    "topics",
    "unit",
}


@dataclass(slots=True)
class ParsedTopic:
    unit_name: str | None
    path_segments: list[str]


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "item"


def _clean_segment(value: str) -> str:
    cleaned = humanize_topic_text(value).strip(" :-–—>|/")
    return cleaned or "Untitled"


def _parse_topic_name(topic_name: str) -> ParsedTopic:
    cleaned = _clean_segment(topic_name)
    unit_name = None
    remainder = cleaned

    match = UNIT_PATTERN.match(cleaned)
    if match:
        unit_label = match.group(1).title()
        unit_number = match.group(2).upper()
        unit_name = f"{unit_label} {unit_number}"
        remainder = _clean_segment(match.group(3))

    segments = [_clean_segment(segment) for segment in HIERARCHY_PATTERN.split(remainder) if segment.strip()]
    if not segments:
        segments = [remainder]

    return ParsedTopic(unit_name=unit_name, path_segments=segments)


def _tokenize(value: str) -> set[str]:
    tokens = {token for token in TOKEN_PATTERN.findall(value.lower()) if token not in STOPWORDS}
    return tokens


def _topic_summary(topic: Topic, subject: Subject, parsed: ParsedTopic) -> str:
    unit_text = f" in {parsed.unit_name}" if parsed.unit_name else ""
    return (
        f"{topic.name} belongs to {subject.name}{unit_text}. "
        f"Estimated study time is {topic.estimated_hours:.1f} hours and completion is {topic.completion_pct:.0f}%."
    )


def build_mind_map(subjects: list[Subject], topics: list[Topic]) -> dict:
    topics_by_subject: dict[str, list[Topic]] = defaultdict(list)
    for topic in topics:
        topics_by_subject[topic.subject_id].append(topic)

    nodes: dict[str, dict] = {}
    edges: dict[str, dict] = {}

    def add_node(node: dict) -> None:
        nodes.setdefault(node["id"], node)

    def add_edge(source: str, target: str, relationship_type: str, label: str) -> None:
        edge_id = f"{relationship_type}:{source}:{target}"
        edges.setdefault(
            edge_id,
            {
                "id": edge_id,
                "source": source,
                "target": target,
                "relationship_type": relationship_type,
                "label": label,
            },
        )

    for subject in subjects:
        subject_node_id = f"subject:{subject.id}"
        subject_topics = sorted(
            topics_by_subject.get(subject.id, []),
            key=lambda item: (item.order_index, item.created_at, item.name.lower()),
        )
        add_node(
            {
                "id": subject_node_id,
                "label": subject.name,
                "node_type": "subject",
                "subject_id": subject.id,
                "subject_name": subject.name,
                "parent_id": None,
                "topic_id": None,
                "full_name": subject.name,
                "unit_name": None,
                "summary": f"{subject.name} contains {len(subject_topics)} mapped topics.",
                "color": subject.color,
                "depth": 0,
                "estimated_hours": None,
                "completion_pct": None,
                "order_index": None,
            }
        )

        previous_leaf_id: str | None = None
        leaf_meta: list[dict] = []

        for topic in subject_topics:
            parsed = _parse_topic_name(topic.name)
            parent_id = subject_node_id
            depth = 1

            if parsed.unit_name:
                unit_id = f"unit:{subject.id}:{_slugify(parsed.unit_name)}"
                add_node(
                    {
                        "id": unit_id,
                        "label": parsed.unit_name,
                        "node_type": "unit",
                        "subject_id": subject.id,
                        "subject_name": subject.name,
                        "parent_id": subject_node_id,
                        "topic_id": None,
                        "full_name": parsed.unit_name,
                        "unit_name": parsed.unit_name,
                        "summary": f"Inferred unit grouping inside {subject.name}.",
                        "color": subject.color,
                        "depth": 1,
                        "estimated_hours": None,
                        "completion_pct": None,
                        "order_index": None,
                    }
                )
                add_edge(subject_node_id, unit_id, "contains", "Contains")
                parent_id = unit_id
                depth = 2

            path_so_far: list[str] = []
            for segment in parsed.path_segments[:-1]:
                path_so_far.append(_slugify(segment))
                group_id = f"group:{subject.id}:{':'.join(path_so_far)}"
                add_node(
                    {
                        "id": group_id,
                        "label": segment,
                        "node_type": "group",
                        "subject_id": subject.id,
                        "subject_name": subject.name,
                        "parent_id": parent_id,
                        "topic_id": None,
                        "full_name": segment,
                        "unit_name": parsed.unit_name,
                        "summary": f"Parent concept inferred from the topic naming inside {subject.name}.",
                        "color": subject.color,
                        "depth": depth,
                        "estimated_hours": None,
                        "completion_pct": None,
                        "order_index": None,
                    }
                )
                add_edge(parent_id, group_id, "contains", "Contains")
                parent_id = group_id
                depth += 1

            leaf_label = parsed.path_segments[-1] if parsed.path_segments else topic.name
            leaf_id = f"topic:{topic.id}"
            add_node(
                {
                    "id": leaf_id,
                    "label": leaf_label,
                    "node_type": "topic",
                    "subject_id": subject.id,
                    "subject_name": subject.name,
                    "parent_id": parent_id,
                    "topic_id": topic.id,
                    "full_name": topic.name,
                    "unit_name": parsed.unit_name,
                    "summary": _topic_summary(topic, subject, parsed),
                    "color": subject.color,
                    "depth": depth,
                    "estimated_hours": topic.estimated_hours,
                    "completion_pct": topic.completion_pct,
                    "order_index": topic.order_index,
                }
            )
            add_edge(parent_id, leaf_id, "contains", "Contains")

            if previous_leaf_id is not None:
                add_edge(previous_leaf_id, leaf_id, "prerequisite", "Builds on")
            previous_leaf_id = leaf_id

            leaf_meta.append(
                {
                    "id": leaf_id,
                    "order_index": topic.order_index,
                    "tokens": _tokenize(f"{leaf_label} {topic.name}"),
                }
            )

        token_index: dict[str, list[int]] = defaultdict(list)
        for idx, meta in enumerate(leaf_meta):
            for token in meta["tokens"]:
                token_index[token].append(idx)

        for idx, meta in enumerate(leaf_meta):
            candidate_indices: set[int] = set()
            for token in meta["tokens"]:
                candidate_indices.update(token_index[token])

            best_match_idx: int | None = None
            best_score = 0.0
            for candidate_idx in candidate_indices:
                if candidate_idx == idx or abs(candidate_idx - idx) <= 1:
                    continue
                candidate = leaf_meta[candidate_idx]
                union = meta["tokens"] | candidate["tokens"]
                if not union:
                    continue
                overlap = meta["tokens"] & candidate["tokens"]
                score = len(overlap) / len(union)
                if len(overlap) < 2 or score < 0.34:
                    continue
                if score > best_score:
                    best_score = score
                    best_match_idx = candidate_idx

            if best_match_idx is not None:
                related_target = leaf_meta[best_match_idx]["id"]
                source, target = sorted([meta["id"], related_target])
                add_edge(source, target, "related", "Related")

    graph = {
        "generated_at": datetime.now(timezone.utc),
        "subject_count": len(subjects),
        "topic_count": len(topics),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": list(nodes.values()),
        "edges": list(edges.values()),
    }
    return graph