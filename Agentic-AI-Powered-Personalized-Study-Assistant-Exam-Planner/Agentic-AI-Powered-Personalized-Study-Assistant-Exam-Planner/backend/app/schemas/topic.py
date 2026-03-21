"""Topic schemas."""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


class TopicCreate(BaseModel):
    subject_id: str
    name: str = Field(..., min_length=1, max_length=300)
    difficulty: float = Field(0.5, ge=0, le=1)
    estimated_hours: float = Field(2.0, ge=0.25, le=100)
    order_index: int = 0


class TopicUpdate(BaseModel):
    name: str | None = None
    difficulty: float | None = None
    estimated_hours: float | None = None
    completed: int | None = None
    completion_pct: float | None = None
    time_spent_mins: float | None = None


class TopicOut(BaseModel):
    id: str
    subject_id: str
    name: str
    difficulty: float
    estimated_hours: float
    completed: int
    completion_pct: float
    time_spent_mins: float
    revision_count: int
    last_reviewed: datetime | None
    order_index: int
    created_at: datetime

    model_config = {"from_attributes": True}


class MindMapNodeOut(BaseModel):
    id: str
    label: str
    node_type: str
    subject_id: str
    subject_name: str
    parent_id: str | None = None
    topic_id: str | None = None
    full_name: str | None = None
    unit_name: str | None = None
    summary: str
    color: str
    depth: int = 0
    estimated_hours: float | None = None
    completion_pct: float | None = None
    order_index: int | None = None


class MindMapEdgeOut(BaseModel):
    id: str
    source: str
    target: str
    relationship_type: str
    label: str


class MindMapGraphOut(BaseModel):
    generated_at: datetime
    subject_count: int
    topic_count: int
    node_count: int
    edge_count: int
    nodes: list[MindMapNodeOut]
    edges: list[MindMapEdgeOut]
