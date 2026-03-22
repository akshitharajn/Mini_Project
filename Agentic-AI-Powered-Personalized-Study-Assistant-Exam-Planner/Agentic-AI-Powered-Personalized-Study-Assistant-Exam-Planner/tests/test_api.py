"""Tests for the FastAPI application endpoints."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.main import app
from backend.app.database import engine, Base
from backend.app.api.syllabus import _split_topic_candidates as syllabus_split_topic_candidates
from backend.app.api.schedule import _split_topic_candidates as schedule_split_topic_candidates
from backend.app.api.syllabus import _is_strong_subject_name as syllabus_is_strong_subject_name
from backend.app.api.schedule import _is_strong_subject_name as schedule_is_strong_subject_name
from backend.app.services.topic_text import topic_dedupe_key
from backend.app.services.topic_text import humanize_topic_text


@pytest.fixture(autouse=True)
async def setup_db():
    """Create and tear down tables for each test."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def client():
    """Async test client using ASGI transport."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestHealthEndpoints:
    async def test_root(self, client: AsyncClient):
        resp = await client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    async def test_health(self, client: AsyncClient):
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"


class TestUserCRUD:
    async def test_create_user(self, client: AsyncClient):
        resp = await client.post("/api/users", json={
            "name": "Alice",
            "email": "alice@example.com",
            "daily_study_hours": 5,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Alice"
        assert "id" in data

    async def test_get_user(self, client: AsyncClient):
        # Create
        resp = await client.post("/api/users", json={
            "name": "Bob", "email": "bob@example.com"
        })
        uid = resp.json()["id"]
        # Get
        resp = await client.get(f"/api/users/{uid}")
        assert resp.status_code == 200
        assert resp.json()["email"] == "bob@example.com"

    async def test_duplicate_email(self, client: AsyncClient):
        payload = {"name": "C", "email": "dup@example.com"}
        await client.post("/api/users", json=payload)
        resp = await client.post("/api/users", json=payload)
        assert resp.status_code == 400


class TestUserRegistrationEmailNotifications:
    async def test_create_user_triggers_signup_email(self, client: AsyncClient, monkeypatch):
        calls: list[dict] = []

        async def fake_send_auth_event_email(*, to_email: str, name: str, event: str):
            calls.append({"to_email": to_email, "name": name, "event": event})
            return True

        monkeypatch.setattr(
            "backend.app.api.users.send_auth_event_email",
            fake_send_auth_event_email,
        )

        resp = await client.post(
            "/api/users",
            json={
                "name": "User Route Signup",
                "email": "user-route-signup@example.com",
                "daily_study_hours": 4,
            },
        )
        assert resp.status_code == 201
        assert calls == [
            {
                "to_email": "user-route-signup@example.com",
                "name": "User Route Signup",
                "event": "signup",
            }
        ]

    async def test_create_user_succeeds_if_email_send_fails(self, client: AsyncClient, monkeypatch):
        async def failing_sender(*args, **kwargs):
            raise RuntimeError("smtp unavailable")

        monkeypatch.setattr("backend.app.api.users.send_auth_event_email", failing_sender)

        resp = await client.post(
            "/api/users",
            json={
                "name": "NoFail Route",
                "email": "nofail-route@example.com",
                "daily_study_hours": 3,
            },
        )
        assert resp.status_code == 201


class TestDatabaseRecovery:
    async def test_register_recovers_from_missing_tables(self, client: AsyncClient):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

        resp = await client.post("/api/auth/register", json={
            "name": "Recovery User",
            "email": "recovery@example.com",
            "password": "secret123",
            "daily_study_hours": 4,
            "learning_preference": "balanced",
            "difficulty_level": "medium",
        })

        assert resp.status_code == 201
        assert resp.json()["user"]["email"] == "recovery@example.com"

    async def test_progress_dashboard_recovers_from_missing_tables(self, client: AsyncClient):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

        resp = await client.get("/api/progress/test-user-id")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["user_id"] == "test-user-id"
        assert payload["total_topics"] == 0
        assert payload["overall_completion_pct"] == 0.0


class TestAuthEmailNotifications:
    async def test_register_and_login_trigger_email_events(self, client: AsyncClient, monkeypatch):
        events: list[str] = []

        async def fake_send_auth_event_email(*, to_email: str, name: str, event: str):
            events.append(event)
            return True

        monkeypatch.setattr(
            "backend.app.api.auth.send_auth_event_email",
            fake_send_auth_event_email,
        )

        register_payload = {
            "name": "Mailer User",
            "email": "mailer@example.com",
            "password": "secret123",
            "daily_study_hours": 4,
            "learning_preference": "balanced",
            "difficulty_level": "medium",
        }
        register_resp = await client.post("/api/auth/register", json=register_payload)
        assert register_resp.status_code == 201

        login_resp = await client.post(
            "/api/auth/login",
            json={"email": register_payload["email"], "password": register_payload["password"]},
        )
        assert login_resp.status_code == 200
        assert events == ["signup", "login"]

    async def test_auth_still_succeeds_when_email_sender_errors(self, client: AsyncClient, monkeypatch):
        async def failing_sender(*args, **kwargs):
            raise RuntimeError("smtp unavailable")

        monkeypatch.setattr("backend.app.api.auth.send_auth_event_email", failing_sender)

        register_payload = {
            "name": "NoFail User",
            "email": "nofail@example.com",
            "password": "secret123",
            "daily_study_hours": 3,
            "learning_preference": "balanced",
            "difficulty_level": "medium",
        }
        register_resp = await client.post("/api/auth/register", json=register_payload)
        assert register_resp.status_code == 201

        login_resp = await client.post(
            "/api/auth/login",
            json={"email": register_payload["email"], "password": register_payload["password"]},
        )
        assert login_resp.status_code == 200


class TestSubjectsAndTopics:
    async def test_subject_lifecycle(self, client: AsyncClient):
        # Create user
        user = (await client.post("/api/users", json={
            "name": "Dan", "email": "dan@example.com"
        })).json()

        # Create subject
        resp = await client.post("/api/subjects", json={
            "user_id": user["id"],
            "name": "Mathematics",
            "exam_date": "2026-03-15",
            "priority": 4.0,
        })
        assert resp.status_code == 201
        subj = resp.json()

        # List subjects
        resp = await client.get(f"/api/subjects/{user['id']}")
        assert len(resp.json()) == 1

        # Add topic
        resp = await client.post("/api/topics", json={
            "subject_id": subj["id"],
            "name": "Calculus",
            "difficulty": 0.7,
            "estimated_hours": 10,
        })
        assert resp.status_code == 201

        # List topics
        resp = await client.get(f"/api/topics/subject/{subj['id']}")
        assert len(resp.json()) == 1

    async def test_mind_map_graph_infers_relationships(self, client: AsyncClient):
        user = (await client.post("/api/users", json={
            "name": "Mind Mapper", "email": "mindmap@example.com"
        })).json()

        subject = (
            await client.post(
                "/api/subjects",
                json={
                    "user_id": user["id"],
                    "name": "Computer Networks",
                    "priority": 4.0,
                    "color": "#1499d6",
                },
            )
        ).json()

        topics = [
            "Unit 1: Networking Basics",
            "Unit 1: Networking Basics -> OSI Model",
            "Unit 2: Routing Protocols",
            "Unit 2: Routing Protocols -> Link State Routing",
        ]

        for idx, topic_name in enumerate(topics):
            resp = await client.post(
                "/api/topics",
                json={
                    "subject_id": subject["id"],
                    "name": topic_name,
                    "difficulty": 0.5,
                    "estimated_hours": 2.0,
                    "order_index": idx,
                },
            )
            assert resp.status_code == 201

        resp = await client.get(f"/api/topics/mind-map/{user['id']}")
        assert resp.status_code == 200

        graph = resp.json()
        assert graph["subject_count"] == 1
        assert graph["topic_count"] == 4
        assert any(node["node_type"] == "subject" for node in graph["nodes"])
        assert any(node["node_type"] == "unit" and node["label"] == "Unit 1" for node in graph["nodes"])
        assert any(node["node_type"] == "topic" and node["label"] == "OSI Model" for node in graph["nodes"])
        assert any(edge["relationship_type"] == "contains" for edge in graph["edges"])
        assert any(edge["relationship_type"] == "prerequisite" for edge in graph["edges"])


class TestScheduleGeneration:
    def test_topic_splitters_filter_noisy_fragments(self):
        raw = (
            "Unit 2: Application of, Databases & amp, Information, "
            "Data Modeling Techniques"
        )

        expected = ["Unit 2: Data Modeling Techniques"]

        assert syllabus_split_topic_candidates(raw) == expected
        assert schedule_split_topic_candidates(raw) == expected

    def test_topic_splitters_split_period_joined_topic_lists(self):
        raw = (
            "Unit 1: Characteristics of IoT.Physical design of IoT."
            "Functional blocks of IoT.Sensing.Actuation"
        )

        expected = [
            "Unit 1: Characteristics of IoT",
            "Unit 1: Physical design of IoT",
            "Unit 1: Functional blocks of IoT",
            "Unit 1: Sensing",
            "Unit 1: Actuation",
        ]

        assert syllabus_split_topic_candidates(raw) == expected
        assert schedule_split_topic_candidates(raw) == expected

    def test_topic_dedupe_key_normalizes_roman_and_numeric_units(self):
        assert (
            topic_dedupe_key("Unit I: Structure of Words & Documents")
            == topic_dedupe_key("Unit 1: Structure of Words & Documents")
        )

    def test_humanize_topic_text_collapses_repeated_words(self):
        assert (
            humanize_topic_text(
                "C 601 OE - Software Software Software Software defined Networking(SDN)"
            )
            == "C 601 OE - Software defined Networking (SDN)"
        )

    def test_topic_splitters_split_single_word_period_joined_topics(self):
        raw = "Unit 4: Agriculture.Healthcare"
        expected = ["Unit 4: Agriculture", "Unit 4: Healthcare"]

        assert syllabus_split_topic_candidates(raw) == expected
        assert schedule_split_topic_candidates(raw) == expected

    def test_topic_splitters_drop_short_garbage_fragments(self):
        raw = "Unit IV: Tech"

        assert syllabus_split_topic_candidates(raw) == []
        assert schedule_split_topic_candidates(raw) == []

    def test_topic_splitters_drop_syllabus_and_reference_noise(self):
        assert syllabus_split_topic_candidates("Unit IV: CSE (AI & ML) Syllabus") == []
        assert schedule_split_topic_candidates("Unit IV: CSE (AI & ML) Syllabus") == []
        assert syllabus_split_topic_candidates("Unit 5: Pre - Requisite") == []
        assert schedule_split_topic_candidates("Unit 5: Pre - Requisite") == []
        assert syllabus_split_topic_candidates(
            "Unit V: Ricardo Baeza - Yates: Information Retrieval Data Structures and Algorithms"
        ) == []
        assert schedule_split_topic_candidates(
            "Unit V: Ricardo Baeza - Yates: Information Retrieval Data Structures and Algorithms"
        ) == []

    def test_topic_splitters_drop_bookish_and_course_metadata_fragments(self):
        noisy_topics = [
            "Unit V: Course Title",
            "Unit V: Graw Hill Education Pvt",
            "Unit V: Book House Pvt",
            "Unit V: Jure Leskovec Stan ford Univ",
            "Unit V: II Year I Sem",
            "Unit 5: Open Elective - I",
            "Unit 5: LT PCredits",
            "Unit 5: ①ovrithyderabad",
            "Unit 5: edu",
            "Unit V: Prentice Hall",
            "Unit V: Gerald J",
            "Unit V: Mark T",
            "Unit V: Paresh Shah",
        ]

        for raw in noisy_topics:
            assert syllabus_split_topic_candidates(raw) == []
            assert schedule_split_topic_candidates(raw) == []

    def test_topic_splitters_drop_leading_fragment_topics(self):
        noisy_topics = [
            "Unit 1: of IoT with Raspberry Pi",
            "Unit 3: fromgeneratedmodel as Height",
            "Unit 5: and toprovide Knowledgeaboutdatnh and ling andanalytics in SDN",
            "Unit V: Aftercompletion of thiscourse",
            "Unit V: the studentswill be ableto",
            "Unit V: Theobjectives of thecourseare to underst and the concepts of Intemet",
            "Unit V: 1 Devclopaclcarcomprehcnsion oflo Tand M 2 Mconccpts",
        ]

        for raw in noisy_topics:
            assert syllabus_split_topic_candidates(raw) == []
            assert schedule_split_topic_candidates(raw) == []

    def test_topic_splitters_clean_or_drop_remaining_ocr_noise(self):
        assert syllabus_split_topic_candidates("Unit II: ataloging & Indexing") == [
            "Unit II: Cataloging & Indexing"
        ]
        assert schedule_split_topic_candidates("Unit II: ataloging & Indexing") == [
            "Unit II: Cataloging & Indexing"
        ]

        cleaned_topics = {
            "Unit 2: Multidiscipl inary nature of Business Economics":
                "Unit 2: Multidisciplinary nature of Business Economics",
            "Unit 3: Features and Price Determ ination":
                "Unit 3: Features and Price Determination",
            "Unit 5: concepts ofsyntax":
                "Unit 5: concepts of syntax",
            "Unit 5: semantics andlanguagemodels":
                "Unit 5: semantics and language models",
            "Unit 5: Applyregression techniques todata and evaluateper formance":
                "Unit 5: Apply regression techniques to data and evaluate performance",
            "Unit 5: Buildsupervised andunsupervised learn ingmodels forobjectivesegmentation":
                "Unit 5: Build supervised and unsupervised learning models for objective segmentation",
            "Unit 5: Buildmodels fortimeseries and evaluateitsper formance":
                "Unit 5: Build models for time series and evaluate its performance",
        }

        for raw, expected in cleaned_topics.items():
            assert syllabus_split_topic_candidates(raw) == [expected]
            assert schedule_split_topic_candidates(raw) == [expected]

        noisy_topics = [
            "Unit 2: Money Supply and Inlationus iness Cycle Featuresand",
            "Unit III: Markttuctureaturfometi ine tomet in Monolyligopolyonplist",
            "Unit V: Ste inbach and Kumar",
            "Unit V: Zaki and W",
            "Unit V: Multilingual natural Language Processing Applications: From Theory to Practice - Daniel",
            "Unit V: Il Year Il Semester",
            "Unit V: construction of lo Tapplications",
        ]

        for raw in noisy_topics:
            assert syllabus_split_topic_candidates(raw) == []
            assert schedule_split_topic_candidates(raw) == []

    def test_topic_splitters_keep_legit_single_word_topics(self):
        expected = ["Unit 4: Agriculture"]
        assert syllabus_split_topic_candidates("Unit 4: Agriculture") == expected
        assert schedule_split_topic_candidates("Unit 4: Agriculture") == expected

    def test_subject_strength_rejects_truncated_course_code_subject(self):
        assert syllabus_is_strong_subject_name("C 601 O") is False
        assert schedule_is_strong_subject_name("C 601 O") is False

    async def test_generate_and_list(self, client: AsyncClient):
        # Setup user + subject + topic
        user = (await client.post("/api/users", json={
            "name": "Eve", "email": "eve@example.com", "daily_study_hours": 3
        })).json()
        subj = (await client.post("/api/subjects", json={
            "user_id": user["id"], "name": "Physics", "exam_date": "2026-03-20"
        })).json()
        await client.post("/api/topics", json={
            "subject_id": subj["id"], "name": "Mechanics", "estimated_hours": 5
        })

        # Generate schedule
        resp = await client.post("/api/schedule/generate", json={
            "user_id": user["id"],
            "start_date": "2026-02-10",
            "end_date": "2026-02-14",
        })
        assert resp.status_code == 201
        entries = resp.json()
        assert len(entries) > 0

        # List
        resp = await client.get(f"/api/schedule/{user['id']}")
        assert resp.status_code == 200

    async def test_generate_from_syllabus_pdf_units(self, client: AsyncClient, monkeypatch):
        user = (await client.post("/api/users", json={
            "name": "Unit User", "email": "unit-user@example.com", "daily_study_hours": 4
        })).json()

        def fake_extract(_: bytes, *, unit_start: int, unit_end: int, **kwargs):
            assert unit_start == 1
            assert unit_end == 5
            assert kwargs.get("max_topics_per_unit") == 120
            return {
                1: ["Introduction", "Basics"],
                2: ["Advanced Concepts"],
                5: ["Revision Topics"],
            }

        monkeypatch.setattr(
            "backend.app.api.schedule.extract_unit_topics_from_pdf_with_langchain",
            fake_extract,
        )

        resp = await client.post(
            "/api/schedule/generate-from-syllabus-pdf",
            data={
                "user_id": user["id"],
                "start_date": "2026-02-10",
                "end_date": "2026-02-15",
                "subject_name": "Operating Systems",
                "unit_start": "1",
                "unit_end": "5",
            },
            files={"file": ("syllabus.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )
        assert resp.status_code == 201
        payload = resp.json()
        assert payload["subject_name"] == "Operating Systems"
        assert payload["unit_range"] == "Unit 1 to Unit 5"
        assert payload["units_detected"] == [1, 2, 5]
        assert payload["topics_created"] == 4
        assert len(payload["schedule_entries"]) > 0

    async def test_generate_from_syllabus_pdf_detects_roman_units_for_imported_subjects(
        self,
        client: AsyncClient,
        monkeypatch,
    ):
        user = (await client.post("/api/users", json={
            "name": "Roman User", "email": "roman-user@example.com", "daily_study_hours": 2
        })).json()

        async def fake_create_quiz(*args, **kwargs):
            return {"id": "quiz-1"}

        monkeypatch.setattr(
            "backend.app.api.schedule.extract_pdf_text_robust",
            lambda _: "Operating Systems syllabus",
        )
        monkeypatch.setattr(
            "backend.app.api.schedule.parse_subjects_and_topics_robust",
            lambda *args, **kwargs: {
                "Operating Systems": [
                    "Unit I: Introduction",
                    "Unit II: Processes and Threads",
                ]
            },
        )
        monkeypatch.setattr(
            "backend.app.api.schedule.parse_subjects_and_topics",
            lambda *args, **kwargs: [],
        )
        monkeypatch.setattr("backend.app.api.schedule.create_quiz", fake_create_quiz)

        resp = await client.post(
            "/api/schedule/generate-from-syllabus-pdf",
            data={
                "user_id": user["id"],
                "start_date": "2026-02-10",
                "end_date": "2026-02-11",
                "subject_name": "Operating Systems",
                "unit_start": "1",
                "unit_end": "5",
                "include_revisions": "false",
            },
            files={"file": ("syllabus.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )

        assert resp.status_code == 201
        payload = resp.json()
        assert payload["units_detected"] == [1, 2]
        assert payload["quizzes_generated"] == 2
        assert payload["topics_created"] == 2

    async def test_generate_manual_creates_split_chronological_schedule(self, client: AsyncClient):
        user = (await client.post("/api/users", json={
            "name": "Manual User", "email": "manual-user@example.com", "daily_study_hours": 2
        })).json()

        resp = await client.post("/api/schedule/generate-manual", json={
            "user_id": user["id"],
            "start_date": "2026-02-10",
            "daily_study_hours": 2,
            "daily_start_time": "08:00:00",
            "session_duration_mins": 60,
            "break_duration_mins": 15,
            "topics": [
                {
                    "subject": "Operating Systems",
                    "unit_or_chapter": "Unit 1",
                    "topic": "Process Management",
                    "estimated_duration_mins": 180,
                },
                {
                    "subject": "Operating Systems",
                    "unit_or_chapter": "Unit 1",
                    "topic": "Process Management",
                    "estimated_duration_mins": 180,
                },
                {
                    "subject": "Operating Systems",
                    "unit_or_chapter": "Unit 2",
                    "topic": "Threads and Scheduling 90 mins",
                },
            ],
        })

        assert resp.status_code == 201
        entries = resp.json()
        assert len(entries) >= 4

        # Duplicate manual topic should not create duplicate topic rows in one subject.
        topics_resp = await client.get(f"/api/subjects/{user['id']}")
        assert topics_resp.status_code == 200
        subjects = topics_resp.json()
        assert len(subjects) == 1

        schedule_resp = await client.get(f"/api/schedule/{user['id']}")
        assert schedule_resp.status_code == 200
        schedule_entries = schedule_resp.json()

        # Entries are expected in chronological order and non-overlapping.
        for idx in range(1, len(schedule_entries)):
            prev = schedule_entries[idx - 1]
            curr = schedule_entries[idx]
            prev_key = (prev["scheduled_date"], prev["end_time"])
            curr_key = (curr["scheduled_date"], curr["start_time"])
            assert curr_key >= prev_key


class TestSyllabusConfirmScheduling:
    async def test_confirm_and_generate_returns_coverage_and_plan(self, client: AsyncClient):
        user = (await client.post("/api/users", json={
            "name": "Coverage User", "email": "coverage-user@example.com", "daily_study_hours": 2
        })).json()

        payload = {
            "user_id": user["id"],
            "start_date": "2026-02-10",
            "end_date": "2026-02-11",
            "daily_start_time": "08:00:00",
            "daily_study_hours": 2,
            "session_duration_mins": 60,
            "break_duration_mins": 15,
            "max_topics_per_day": 3,
            "no_ai_mode": False,
            "clear_existing": True,
            "subjects": [
                {
                    "name": "Object Oriented Programming Through Java",
                    "topics": [
                        "Unit I: Classes and Objects (basics + examples)",
                        "Unit II: Inheritance (types + examples)",
                        "Unit III: Polymorphism and Method Overriding",
                    ],
                }
            ],
        }

        resp = await client.post("/api/syllabus/confirm-and-generate", json=payload)
        assert resp.status_code == 201
        data = resp.json()

        assert data["topics_created"] == 3
        assert data["total_topics"] == 3
        assert data["scheduled_topics"] >= 2
        assert data["coverage_percentage"] >= 60.0
        assert len(data["schedule_plan"]) > 0

        plan_topics = [item["topic"] for item in data["schedule_plan"]]
        assert len(plan_topics) == len(set(plan_topics))
        first_plan = data["schedule_plan"][0]
        assert set(first_plan.keys()) == {"date", "time", "subject", "topic", "unit"}
        assert first_plan["unit"].startswith("UNIT-")

    async def test_confirm_and_generate_auto_extends_when_coverage_is_low(self, client: AsyncClient):
        user = (await client.post("/api/users", json={
            "name": "Auto Extend User", "email": "auto-extend@example.com", "daily_study_hours": 1
        })).json()

        payload = {
            "user_id": user["id"],
            "start_date": "2026-02-10",
            "end_date": "2026-02-10",
            "daily_start_time": "08:00:00",
            "daily_study_hours": 1,
            "session_duration_mins": 60,
            "break_duration_mins": 15,
            "max_topics_per_day": 1,
            "no_ai_mode": False,
            "clear_existing": True,
            "subjects": [
                {
                    "name": "Data Structures",
                    "topics": [
                        "Unit I: Arrays and Strings",
                        "Unit II: Linked List Operations",
                        "Unit III: Stacks and Queues",
                        "Unit IV: Binary Search Trees",
                        "Unit V: Graph Traversal Algorithms",
                    ],
                }
            ],
        }

        resp = await client.post("/api/syllabus/confirm-and-generate", json=payload)
        assert resp.status_code == 201
        data = resp.json()

        assert data["total_topics"] == 5
        assert data["scheduled_topics"] >= 3
        assert data["coverage_percentage"] >= 60.0

        generated_dates = [entry["scheduled_date"] for entry in data["schedule_entries"]]
        assert any(scheduled_date > payload["end_date"] for scheduled_date in generated_dates)


class TestQuizFlow:
    async def test_generate_and_submit(self, client: AsyncClient):
        # Setup
        user = (await client.post("/api/users", json={
            "name": "Frank", "email": "frank@example.com"
        })).json()
        subj = (await client.post("/api/subjects", json={
            "user_id": user["id"], "name": "Chemistry"
        })).json()
        topic = (await client.post("/api/topics", json={
            "subject_id": subj["id"], "name": "Organic Chem"
        })).json()

        # Generate quiz
        resp = await client.post("/api/quiz/generate", json={
            "user_id": user["id"],
            "topic_id": topic["id"],
            "difficulty": "easy",
            "num_questions": 3,
        })
        assert resp.status_code == 201
        quiz = resp.json()
        assert len(quiz["questions"]) == 3

        # Submit answers
        answers = [{"question_id": q["id"], "answer": "A"} for q in quiz["questions"]]
        resp = await client.post("/api/quiz/submit", json={
            "quiz_id": quiz["id"],
            "user_id": user["id"],
            "answers": answers,
        })
        assert resp.status_code == 200
        result = resp.json()
        assert result["total_questions"] == 3
        assert "score_pct" in result
