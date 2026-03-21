"""Educational chatbot API."""

from __future__ import annotations

from collections import defaultdict
import re

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.config import get_settings
from backend.app.database import get_db
from backend.app.models.chat import ChatMessage as ChatMessageModel
from backend.app.models.schedule import ScheduleEntry
from backend.app.models.subject import Subject
from backend.app.models.topic import Topic
from backend.app.schemas.chat import ChatAskRequest, ChatAskResponse, ChatHistoryItem, ChatMessage

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _normalize_educational_query(text: str) -> str:
    normalized = f" {_normalize(text)} "
    replacements = {
        " sprinboot ": " spring boot ",
        " springboot ": " spring boot ",
        " exlpain ": " explain ",
        " exlain ": " explain ",
        " complier ": " compiler ",
        " dl ": " deep learning ",
        " languagemodeling ": " language modeling ",
    }
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    return re.sub(r"\s+", " ", normalized).strip()


def _tokenize(text: str) -> set[str]:
    return {tok for tok in _normalize(text).split() if len(tok) >= 2}


def _subject_aliases(name: str) -> set[str]:
    normalized = _normalize(name)
    aliases = {normalized}
    code_match = re.match(r"^([a-z0-9 ]+?)\s+-\s+", normalized)
    if code_match:
        aliases.add(code_match.group(1).strip())
        aliases.add(normalized.split("-", 1)[1].strip())
    return {alias for alias in aliases if alias}


def _format_schedule_line(entry: ScheduleEntry) -> str:
    return (
        f"{entry.scheduled_date} {str(entry.start_time)[:5]}-{str(entry.end_time)[:5]}: "
        f"{entry.subject_name} - {entry.topic_name}"
    )


def _contains_phrase(text: str, phrase: str) -> bool:
    normalized_phrase = _normalize_educational_query(phrase)
    if not normalized_phrase:
        return False
    return f" {normalized_phrase} " in f" {_normalize_educational_query(text)} "


def _is_general_educational_query(message: str) -> bool:
    query = _normalize_educational_query(message)
    if not query:
        return False

    educational_terms = {
        "ai",
        "ml",
        "machine learning",
        "deep learning",
        "dbms",
        "sql",
        "database",
        "normalization",
        "join",
        "joins",
        "indexing",
        "python",
        "java",
        "c programming",
        "programming",
        "algorithm",
        "algorithms",
        "data structure",
        "dsa",
        "operating system",
        "os",
        "linux",
        "network",
        "networking",
        "compiler",
        "cloud",
        "cybersecurity",
        "blockchain",
        "statistics",
        "probability",
        "calculus",
        "economics",
        "nlp",
        "iot",
        "information retrieval",
        "data analytics",
        "data mining",
        "oops",
        "oop",
        "study",
        "exam",
        "revision",
        "quiz",
        "education",
        "geography",
    }
    intent_terms = {
        "explain",
        "what is",
        "what are",
        "define",
        "difference between",
        "compare",
        "how does",
        "how do",
        "types of",
        "why",
        "when",
        "example",
        "examples",
        "advantages",
        "disadvantages",
    }
    return any(_contains_phrase(query, term) for term in educational_terms | intent_terms)


def _needs_educational_clarification(message: str) -> bool:
    query = _normalize_educational_query(message)
    if not query:
        return False

    short_query = len(query.split()) <= 4
    broad_but_ambiguous = {
        "graph",
        "graphs",
        "tree",
        "trees",
        "stack",
        "stacks",
        "queue",
        "queues",
        "model",
        "models",
        "process",
        "procedure",
        "formula",
        "formulas",
        "theory",
        "system",
        "systems",
    }
    return short_query and any(_contains_phrase(query, term) for term in broad_but_ambiguous)


def _is_non_educational_query(message: str) -> bool:
    query = _normalize_educational_query(message)
    if not query:
        return False

    non_educational_terms = {
        "trip",
        "trips",
        "travel",
        "tour",
        "tourism",
        "vacation",
        "holiday",
        "hotel",
        "flight",
        "restaurant",
        "food",
        "cooking",
        "recipe",
        "recipes",
        "movie",
        "song",
        "lyrics",
        "celebrity",
        "actor",
        "actress",
        "cricket score",
        "match score",
        "ipl",
        "football match",
        "prime minister",
        "pm of india",
        "president",
        "politics",
        "party",
        "election",
        "weather",
        "bitcoin price",
        "stock price",
        "shopping",
        "shopping list",
        "buy",
        "amazon",
        "flipkart",
        "motivation",
    }
    return any(_contains_phrase(query, term) for term in non_educational_terms)


def _is_compliment(message: str) -> bool:
    """Detect short appreciative/compliment messages."""
    query = f" {_normalize_educational_query(message)} "
    compliment_terms = [
        "good bot",
        "great",
        "awesome",
        "nice",
        "well done",
        "thanks",
        "thank you",
        "appreciate",
        "helpful",
        "so good",
        "good job",
        "cool",
    ]
    return any(term in query for term in compliment_terms)


def _non_educational_redirect() -> tuple[str, list[str], list[str]]:
    return (
        "I am restricted to educational help only. Ask about concepts, formulas, programming, exam preparation, study methods, or your syllabus and timetable.",
        ["education_only"],
        ["Explain graphs", "What is data mining?", "How do I revise Unit 1?"],
    )


def _educational_clarification_redirect() -> tuple[str, list[str], list[str]]:
    return (
        "Your question looks educational, but it is too broad or ambiguous. Ask with a little more context, such as the subject or exact concept you want.",
        ["education_clarification"],
        ["Explain graphs in data structures", "Explain trees in DSA", "Explain slope formula in maths"],
    )


def _general_educational_answer(message: str) -> tuple[str, list[str], list[str]] | None:
    query = _normalize_educational_query(message)
    expanded_query = f" {query} "
    expanded_query = expanded_query.replace(" da ", " data analytics ")
    if _is_compliment(message):
        return (
            "Thanks! Ask any educational question or tell me a subject/unit to focus on.",
            ["general_education"],
            ["What should I study next?", "Show topics in a subject", "How do I revise this unit?"],
        )
    if any(greeting in expanded_query for greeting in [" hi ", " hello ", " hey "]):
        return (
            "Ask any educational question, concept doubt, exam-prep question, or study-method question. "
            "I can explain topics across programming, CS, analytics, economics, math, and more.",
            ["general_education"],
            ["Explain machine learning types", "What is normalization in DBMS?", "How do I prepare for exams?"],
        )

    explain_like = any(
        phrase in query
        for phrase in [
            "explain",
            "what is",
            "what are",
            "types of",
            "define",
            "difference between",
            "compare",
            "how does",
            "how do",
            "why",
            "advantages",
            "disadvantages",
            "example",
            "examples",
        ]
    )
    if not explain_like and not _is_general_educational_query(message):
        return None

    if "deep learning" in expanded_query:
        return (
            "Deep learning is a subset of machine learning that uses multi-layer neural networks to learn complex patterns from large amounts of data. "
            "It is widely used in image recognition, speech processing, NLP, and recommendation systems.\n"
            "- Uses neural networks with many layers\n"
            "- Learns features automatically from data\n"
            "- Needs more data and computing power than traditional ML",
            ["general_education"],
            ["AI vs ML vs deep learning", "What is a neural network?", "Applications of deep learning"],
        )

    if "linux" in expanded_query:
        return (
            "Linux is an open-source operating system based on Unix. It is widely used in servers, cloud systems, embedded devices, cybersecurity, and development environments.\n"
            "- Multiuser and multitasking\n"
            "- Secure and stable\n"
            "- Uses a command-line shell as well as graphical environments\n"
            "- Popular distributions include Ubuntu, Fedora, Debian, and Arch Linux\n\n"
            "In short: Linux is a powerful, flexible OS widely used in technical and production systems.",
            ["general_education"],
            ["What is the Linux kernel?", "Common Linux commands", "Linux vs Windows"],
        )

    if "spring boot" in expanded_query:
        return (
            "Spring Boot is a Java framework built on top of Spring that makes it easier to create production-ready applications quickly.\n"
            "- Provides auto-configuration\n"
            "- Includes embedded servers like Tomcat\n"
            "- Reduces boilerplate setup\n"
            "- Commonly used for REST APIs and microservices\n\n"
            "In short: Spring Boot simplifies Spring application development.",
            ["general_education"],
            ["What is dependency injection?", "Explain REST API in Spring Boot", "Spring vs Spring Boot"],
        )

    if "iot architecture" in expanded_query:
        return (
            "IoT architecture explains how IoT components are organized to collect, transmit, process, and use data.\n"
            "- Perception layer: sensors and devices collect data\n"
            "- Network layer: transfers data using communication protocols\n"
            "- Processing layer: stores and analyzes data, often in cloud or edge systems\n"
            "- Application layer: delivers user-facing services such as smart health, agriculture, or monitoring\n\n"
            "Some models also include a business layer for management and analytics.",
            ["general_education"],
            ["Explain IoT layers", "Sensors vs actuators", "IoT vs M2M"],
        )

    if "compiler phases" in expanded_query or "phases of compiler" in expanded_query:
        return (
            "The main phases of a compiler are:\n"
            "- Lexical analysis: converts characters into tokens\n"
            "- Syntax analysis: checks grammatical structure using parsing\n"
            "- Semantic analysis: checks meaning, types, and declarations\n"
            "- Intermediate code generation: creates a middle-level representation\n"
            "- Code optimization: improves efficiency\n"
            "- Code generation: produces target machine code\n\n"
            "Symbol table management and error handling support all phases.",
            ["general_education"],
            ["What is lexical analysis?", "What is parsing?", "Explain semantic analysis"],
        )

    if "semiconductor" in expanded_query or "semiconductors" in expanded_query:
        return (
            "A semiconductor is a material whose electrical conductivity lies between that of a conductor and an insulator. "
            "Its conductivity can be controlled by temperature, light, voltage, or impurities.\n"
            "- Common examples: silicon and germanium\n"
            "- Two main types: intrinsic and extrinsic semiconductors\n"
            "- Extrinsic semiconductors are of two types: n-type and p-type\n"
            "- Semiconductors are used in diodes, transistors, ICs, and solar cells",
            ["general_education"],
            ["What is intrinsic vs extrinsic semiconductor?", "Explain p-type and n-type semiconductor", "Applications of semiconductors"],
        )

    if "slope formula" in expanded_query or ("formula" in expanded_query and "slope" in expanded_query):
        return (
            "The slope of a line through two points (x1, y1) and (x2, y2) is:\n"
            "m = (y2 - y1) / (x2 - x1)\n\n"
            "It tells how much y changes for a change in x.\n"
            "- Positive slope: line rises\n"
            "- Negative slope: line falls\n"
            "- Zero slope: horizontal line\n"
            "- Undefined slope: vertical line",
            ["general_education"],
            ["What is slope in coordinate geometry?", "Equation of a straight line", "Point-slope form of a line"],
        )

    if "straight line" in expanded_query or "equation of line" in expanded_query:
        return (
            "Common forms of the equation of a straight line are:\n"
            "- Slope-intercept form: y = mx + c\n"
            "- Point-slope form: y - y1 = m(x - x1)\n"
            "- Two-point form: y - y1 = ((y2 - y1)/(x2 - x1)) (x - x1)\n"
            "- General form: Ax + By + C = 0",
            ["general_education"],
            ["Explain slope formula", "What is point-slope form?", "How to find equation of a line from two points"],
        )

    if "normalization" in expanded_query:
        return (
            "Normalization in DBMS is the process of organizing data to reduce redundancy and improve consistency.\n"
            "- 1NF: remove repeating groups and keep values atomic\n"
            "- 2NF: remove partial dependency on part of a composite key\n"
            "- 3NF: remove transitive dependency\n"
            "- BCNF: every determinant should be a candidate key\n\n"
            "In exams, write the definition, objective, and one line for each normal form.",
            ["general_education"],
            ["Explain 1NF 2NF 3NF", "What is BCNF?", "What are joins in SQL?"],
        )

    if " join " in expanded_query or " joins " in expanded_query:
        return (
            "Joins in SQL are used to combine rows from two or more tables based on a related column.\n"
            "- INNER JOIN: returns matching rows from both tables\n"
            "- LEFT JOIN: all rows from left table and matched rows from right\n"
            "- RIGHT JOIN: all rows from right table and matched rows from left\n"
            "- FULL OUTER JOIN: all matched and unmatched rows from both tables\n"
            "- SELF JOIN: joins a table with itself\n\n"
            "For exams, define join, then explain each type with a simple example.",
            ["general_education"],
            ["Explain INNER JOIN vs LEFT JOIN", "Give SQL join example", "Explain normalization"],
        )

    if "indexing" in expanded_query and ("dbms" in expanded_query or "database" in expanded_query or "sql" in expanded_query):
        return (
            "Indexing in DBMS is a technique used to speed up data retrieval by creating a separate structure that helps the database find rows faster.\n"
            "- Improves search performance\n"
            "- Common types: primary index, secondary index, clustered index, non-clustered index\n"
            "- Uses extra storage and can slow inserts or updates\n\n"
            "In short: indexing improves read speed but adds maintenance cost.",
            ["general_education"],
            ["What is normalization?", "What are joins in SQL?", "Clustered vs non-clustered index"],
        )

    if "types of data analytics" in expanded_query or "data analytics types" in expanded_query:
        return (
            "The main types of Data Analytics are:\n"
            "- Descriptive analytics: what happened\n"
            "- Diagnostic analytics: why it happened\n"
            "- Predictive analytics: what is likely to happen\n"
            "- Prescriptive analytics: what should be done\n\n"
            "A short exam answer is: descriptive, diagnostic, predictive, and prescriptive analytics.",
            ["general_education"],
            ["Explain descriptive vs predictive analytics", "Applications of data analytics", "What is machine learning?"],
        )

    if "types of ml" in expanded_query or "types of machine learning" in expanded_query:
        return (
            "The main types of machine learning are:\n"
            "- Supervised learning: learns from labeled examples\n"
            "- Unsupervised learning: finds hidden patterns in unlabeled data\n"
            "- Reinforcement learning: learns actions using rewards and penalties\n\n"
            "You can also mention semi-supervised learning as a hybrid approach in some answers.",
            ["general_education"],
            ["Explain supervised learning", "Difference between supervised and unsupervised learning", "What is reinforcement learning?"],
        )

    if "types of ai" in expanded_query:
        return (
            "AI is commonly classified in two ways.\n"
            "- By capability: Narrow AI, General AI, Super AI\n"
            "- By functionality: Reactive machines, limited memory, theory of mind, self-aware systems\n\n"
            "In most exams, Narrow AI vs General AI is the most useful distinction.",
            ["general_education"],
            ["AI vs ML", "Applications of AI", "What is deep learning?"],
        )

    if "what is data analytics" in expanded_query or "define data analytics" in expanded_query:
        return (
            "Data analytics is the process of collecting, cleaning, transforming, and analyzing data to discover useful information and support decision-making. "
            "It combines statistics, data processing, visualization, and modeling.",
            ["general_education"],
            ["Types of data analytics", "Data analytics vs data mining", "Applications of data analytics"],
        )

    if "what is machine learning" in expanded_query or "define machine learning" in expanded_query:
        return (
            "Machine learning is a branch of AI in which systems learn patterns from data and improve predictions or decisions without being explicitly programmed for every case.",
            ["general_education"],
            ["Types of ML", "AI vs ML", "What is deep learning?"],
        )

    if "difference between" in expanded_query or "compare" in expanded_query:
        if _contains_phrase(query, "ai") and _contains_phrase(query, "ml"):
            return (
                "AI is the broader field of creating intelligent systems, while ML is a subset of AI that learns patterns from data.\n"
                "- AI aims to simulate intelligent behavior\n"
                "- ML focuses on learning from examples\n"
                "- All ML is AI, but not all AI is ML\n\n"
                "In short: AI is the umbrella term, ML is one approach inside AI.",
                ["general_education"],
                ["Types of AI", "Types of ML", "What is deep learning?"],
            )
        return (
            "For a good comparison answer, write:\n"
            "- definition of both terms\n"
            "- 3 to 5 direct differences\n"
            "- one example for each\n"
            "- a short conclusion about where each is used\n\n"
            "Ask again with the exact two topics if you want a specific comparison.",
            ["general_education"],
            ["Difference between AI and ML", "Compare DBMS and file system", "Difference between TCP and UDP"],
        )

    concept_map: list[tuple[set[str], str, list[str]]] = [
        (
            {"ml", "machine learning"},
            "Machine learning is usually grouped into 3 main types:\n"
            "- Supervised learning: learns from labeled data to predict outputs. Examples: classification and regression.\n"
            "- Unsupervised learning: finds patterns in unlabeled data. Examples: clustering and dimensionality reduction.\n"
            "- Reinforcement learning: an agent learns by trial and error using rewards and penalties.\n\n"
            "A simple exam answer is: supervised uses labeled data, unsupervised uses unlabeled data, and reinforcement learns from feedback.",
            ["Explain supervised vs unsupervised learning", "Give ML examples", "What is reinforcement learning?"],
        ),
        (
            {"dbms", "normalization", "sql", "database"},
            "DBMS is software used to store, manage, and retrieve structured data efficiently.\n"
            "Key topics usually include normalization, SQL queries, joins, indexing, transactions, and concurrency control.",
            ["Explain normalization", "What are joins in SQL?", "What is indexing in DBMS?"],
        ),
        (
            {"oops", "oop", "object oriented"},
            "The main OOP concepts are:\n"
            "- Encapsulation\n- Abstraction\n- Inheritance\n- Polymorphism\n\n"
            "A good answer also explains each with one short example.",
            ["Explain encapsulation", "Difference between inheritance and polymorphism", "OOP with examples"],
        ),
        (
            {"os", "operating system", "deadlock", "scheduling"},
            "Operating system questions often focus on process scheduling, deadlocks, memory management, paging, synchronization, and file systems.",
            ["What is deadlock?", "Explain CPU scheduling", "What is paging?"],
        ),
        (
            {"linux", "unix"},
            "Linux is an open-source operating system widely used in servers, cloud computing, development, and embedded systems. Key topics include the kernel, shell, file system, permissions, processes, and commands.",
            ["What is Linux?", "Common Linux commands", "Linux vs Unix"],
        ),
        (
            {"dsa", "data structure", "algorithm", "algorithms"},
            "For data structures and algorithms, explain the idea first, then give steps, time complexity, space complexity, and one example.",
            ["Explain time complexity", "What is a stack?", "Difference between BFS and DFS"],
        ),
        (
            {"python"},
            "Python is a high-level interpreted language known for readable syntax. Important basics are variables, data types, loops, functions, lists, dictionaries, file handling, and OOP.",
            ["Explain Python lists vs tuples", "What are Python dictionaries?", "Explain functions in Python"],
        ),
        (
            {"nlp", "natural language processing"},
            "NLP is the field that helps computers understand and process human language. Common areas include tokenization, parsing, semantics, language modeling, and text classification.",
            ["What is tokenization?", "Explain language models", "What is parsing in NLP?"],
        ),
        (
            {"iot", "internet of things"},
            "IoT means connecting physical devices to the internet so they can sense, exchange, and act on data. Core ideas are sensors, actuators, communication, edge devices, and analytics.",
            ["Explain sensors and actuators", "What is IoT architecture?", "IoT vs M2M"],
        ),
        (
            {"information retrieval", "ir"},
            "Information Retrieval is about finding relevant information from large collections of documents. Core topics include indexing, ranking, search models, clustering, and multimedia retrieval.",
            ["What is indexing in IR?", "Explain ranking in IR", "Difference between IR and DBMS"],
        ),
        (
            {"artificial intelligence", "ai"},
            "Artificial Intelligence is the field of building systems that can perform tasks requiring human-like intelligence such as reasoning, learning, planning, perception, and language understanding.",
            ["Types of AI", "AI vs ML", "Applications of AI"],
        ),
        (
            {"data mining"},
            "Data mining is the process of discovering useful patterns, trends, and knowledge from large datasets using statistical, machine learning, and database techniques.",
            ["Steps in data mining", "Data mining vs data analytics", "Applications of data mining"],
        ),
        (
            {"data analytics"},
            "Data analytics is the study of data to find patterns, insights, and useful decisions. It usually involves data collection, cleaning, analysis, visualization, and interpretation.",
            ["Types of data analytics", "Data analytics vs data mining", "Applications of data analytics"],
        ),
        (
            {"geography", "physical geography", "human geography"},
            "Geography explores Earth's landscapes, environments, and human activities.\n"
            "- Physical geography covers landforms, climate, ecosystems, and natural hazards.\n"
            "- Human geography studies populations, settlement patterns, agriculture, and urbanization.\n"
            "- Map skills, layers of geography (spatial, environmental, cultural), and fieldwork summaries help for exams.\n\n"
            "Revise by drawing concept maps of regions, comparing physical vs human features, and summarizing key maps in your own words.",
            ["Explain human vs physical geography", "Describe climate zones", "How to revise geography"],
        ),
        (
            {"statistics", "probability"},
            "Probability measures the chance of an event occurring, while statistics deals with collecting, analyzing, and interpreting data. Common topics are mean, median, variance, distributions, hypothesis testing, and correlation.",
            ["What is probability?", "Explain mean median mode", "What is standard deviation?"],
        ),
        (
            {"calculus", "derivative", "integration", "integral"},
            "Calculus studies change and accumulation. Derivatives measure rate of change, while integrals measure accumulation or area under a curve.",
            ["What is a derivative?", "What is integration?", "Derivative vs integral"],
        ),
        (
            {"slope", "coordinate geometry", "line equation"},
            "The slope of a line measures its steepness. For points (x1, y1) and (x2, y2), slope m = (y2 - y1)/(x2 - x1). It is widely used in coordinate geometry and straight line equations.",
            ["Explain slope formula", "Equation of a straight line", "Point-slope form"],
        ),
        (
            {"computer network", "networking", "osi", "tcp ip"},
            "Computer networks connect devices to share data and resources. Common concepts are OSI model, TCP/IP, IP addressing, routing, switching, protocols, and error control.",
            ["Explain OSI model", "What is TCP/IP?", "What is routing?"],
        ),
        (
            {"compiler", "compiler design", "lexical analysis", "parser", "parsing"},
            "Compiler design converts source code into machine code in phases such as lexical analysis, syntax analysis, semantic analysis, optimization, and code generation.",
            ["Phases of compiler", "What is lexical analysis?", "What is parsing?"],
        ),
        (
            {"cloud computing", "cloud"},
            "Cloud computing delivers computing services like servers, storage, and databases over the internet. Main service models are IaaS, PaaS, and SaaS.",
            ["What is cloud computing?", "IaaS vs PaaS vs SaaS", "Advantages of cloud"],
        ),
        (
            {"cyber security", "cybersecurity", "security"},
            "Cybersecurity is the practice of protecting systems, networks, and data from attacks. Core areas include authentication, encryption, malware, firewalls, and network security.",
            ["What is encryption?", "Types of cyber attacks", "What is authentication?"],
        ),
        (
            {"blockchain"},
            "Blockchain is a distributed digital ledger where transactions are grouped into blocks and linked securely using cryptography. It is known for decentralization, transparency, and immutability.",
            ["What is blockchain?", "Blockchain vs database", "Applications of blockchain"],
        ),
        (
            {"software engineering", "sdlc"},
            "Software engineering is the disciplined development of software using planning, design, coding, testing, deployment, and maintenance. SDLC models include waterfall, iterative, spiral, and agile.",
            ["What is SDLC?", "Agile vs waterfall", "Software testing types"],
        ),
        (
            {"java"},
            "Java is an object-oriented programming language known for platform independence through the JVM. Important basics are classes, objects, inheritance, interfaces, exceptions, and collections.",
            ["What is JVM?", "OOP in Java", "Java collections"],
        ),
        (
            {"c programming", "language c", " c "},
            "C is a procedural programming language widely used for system programming. Important topics include variables, pointers, arrays, functions, structures, memory management, and file handling.",
            ["What are pointers in C?", "Arrays vs pointers", "Structures in C"],
        ),
        (
            {"economics", "microeconomics", "macroeconomics"},
            "Economics studies how resources are produced, distributed, and consumed. Microeconomics focuses on individuals and firms, while macroeconomics studies the economy as a whole.",
            ["Micro vs macro economics", "What is demand?", "What is inflation?"],
        ),
        (
            {"semiconductor", "semiconductors", "p type", "n type"},
            "A semiconductor is a material with conductivity between a conductor and an insulator. Silicon and germanium are common examples. Important topics include intrinsic semiconductors, extrinsic semiconductors, p-type, n-type, and PN junction devices.",
            ["Intrinsic vs extrinsic semiconductor", "P-type vs n-type semiconductor", "Applications of semiconductors"],
        ),
    ]

    for keys, answer, suggestions in concept_map:
        if any(_contains_phrase(query, key) for key in keys):
            return answer, ["general_education"], suggestions

    return None


async def _log_chat_message(
    db: AsyncSession,
    user_id: str,
    role: str,
    content: str,
    mode: str | None = None,
) -> None:
    if not user_id or not content:
        return
    db.add(
        ChatMessageModel(
            user_id=user_id,
            role=role,
            content=content[:4000],
            mode=mode[:50] if mode else None,
        )
    )
    await db.commit()


def _rule_based_answer(
    message: str,
    subjects: list[Subject],
    upcoming_entries: list[ScheduleEntry],
) -> tuple[str, list[str], list[str]]:
    query = _normalize(message)
    tokens = _tokenize(message)

    if not query:
        return (
            "Ask about your subjects, topics, timetable, revisions, or study guidance.",
            [],
            ["What should I study next?", "List my subjects", "Show topics in Data Analytics"],
        )

    if _is_non_educational_query(message):
        return _non_educational_redirect()

    general_answer = _general_educational_answer(message)
    if general_answer is not None:
        return general_answer

    if {"today", "now", "next"} & tokens or "study" in tokens or "schedule" in tokens or "timetable" in tokens:
        if not upcoming_entries:
            return (
                "No upcoming study sessions are scheduled right now.",
                ["schedule"],
                ["Generate a timetable", "List my subjects"],
            )
        next_items = upcoming_entries[:5]
        answer = "Your next study sessions are:\n" + "\n".join(
            f"- {_format_schedule_line(entry)}" for entry in next_items
        )
        return answer, ["schedule"], ["Show topics in a subject", "What should I revise this week?"]

    if "subject" in tokens and ("list" in tokens or "what" in tokens or "have" in tokens):
        if not subjects:
            return (
                "No subjects are saved yet.",
                ["subjects"],
                ["Import syllabus", "Add a subject"],
            )
        return (
            "Your subjects are:\n" + "\n".join(f"- {subject.name}" for subject in subjects),
            ["subjects"],
            [f"Show topics in {subjects[0].name}" if subjects else "Show my timetable"],
        )

    matched_subjects: list[Subject] = []
    for subject in subjects:
        aliases = _subject_aliases(subject.name)
        if any(alias in query for alias in aliases) or (_tokenize(subject.name) & tokens):
            matched_subjects.append(subject)

    if matched_subjects:
        subject = matched_subjects[0]
        ordered_topics = sorted(subject.topics, key=lambda topic: (topic.order_index, topic.name))
        if "topic" in tokens or "syllabus" in tokens or "unit" in tokens or "cover" in tokens:
            topic_lines = [f"- {topic.name}" for topic in ordered_topics[:25]]
            if len(ordered_topics) > 25:
                topic_lines.append(f"- ... and {len(ordered_topics) - 25} more topics")
            return (
                f"{subject.name} has {len(ordered_topics)} topics:\n" + "\n".join(topic_lines),
                [subject.name],
                [f"What should I study next in {subject.name}?", f"How do I revise {subject.name}?"],
            )

        completed = sum(1 for topic in ordered_topics if topic.completed)
        weak_topics = [topic.name for topic in ordered_topics if topic.completion_pct < 40][:5]
        answer_lines = [
            f"{subject.name} has {len(ordered_topics)} topics and {completed} completed topics.",
        ]
        if weak_topics:
            answer_lines.append("Focus next on: " + ", ".join(weak_topics))
        next_subject_sessions = [entry for entry in upcoming_entries if entry.subject_name == subject.name][:3]
        if next_subject_sessions:
            answer_lines.append("Upcoming sessions:")
            answer_lines.extend(f"- {_format_schedule_line(entry)}" for entry in next_subject_sessions)
        return (
            "\n".join(answer_lines),
            [subject.name, "schedule"],
            [f"Show topics in {subject.name}", f"Explain {subject.name} study plan"],
        )

    matched_topics: list[tuple[str, str]] = []
    for subject in subjects:
        for topic in subject.topics:
            topic_tokens = _tokenize(topic.name)
            if len(topic_tokens & tokens) >= 2 or _normalize(topic.name) in query:
                matched_topics.append((subject.name, topic.name))

    if matched_topics:
        grouped: dict[str, list[str]] = defaultdict(list)
        for subject_name, topic_name in matched_topics[:10]:
            grouped[subject_name].append(topic_name)
        lines = ["I found these matching topics:"]
        for subject_name, topic_names in grouped.items():
            lines.append(f"- {subject_name}: {', '.join(topic_names)}")
        return "\n".join(lines), ["topics"], ["Show my next sessions", "List my subjects"]

    educational_guidance = {
        "revision": "For revision, use active recall, short unit-wise notes, and quiz practice after each unit.",
        "quiz": "For quizzes, first review the unit summary, then solve 5-10 questions and check explanations.",
        "exam": "For exam prep, prioritize high-weight units, weak topics, and one revision cycle before the exam.",
        "study": "Use 45-60 minute focused sessions, then a short break. End each session with 3 key takeaways.",
        "process": "Explain the topic in your own words, write key points, solve one example, then test yourself without notes.",
        "algorithm": "For algorithm questions, describe the idea first, then steps, time complexity, space complexity, and one example.",
        "python": "For Python learning, start with syntax, functions, lists/dicts, file handling, and small practice problems.",
        "database": "For database topics, focus on ER modeling, normalization, SQL queries, joins, indexing, and transactions.",
    }
    for key, value in educational_guidance.items():
        if key in tokens:
            return value, ["guidance"], ["What should I study next?", "Show weak topics in a subject"]

    return (
        "I can answer educational questions in general, and I can also use your saved subjects, topics, units, "
        "and timetable when relevant. Ask a concept question, exam-prep question, or study-planning question.",
        [],
        [
            "Explain normalization in DBMS",
            "How do I prepare for an exam in one week?",
            "List my subjects",
        ],
    )


async def _llm_answer(
    message: str,
    subjects: list[Subject],
    upcoming_entries: list[ScheduleEntry],
    history: list[ChatMessage],
) -> tuple[str | None, str | None]:
    get_settings.cache_clear()
    settings = get_settings()
    provider = (settings.ai_provider or "").lower()
    if provider == "openai":
        api_key = settings.openai_api_key
        base_url = "https://api.openai.com/v1/chat/completions"
        model = "gpt-4o-mini"
    elif provider == "groq":
        api_key = settings.groq_api_key
        base_url = "https://api.groq.com/openai/v1/chat/completions"
        model = settings.groq_model
    else:
        return None, None

    if not api_key:
        return None, None

    if provider not in {"openai", "groq"}:
        return None, None

    subject_summaries = []
    for subject in subjects[:8]:
        ordered_topics = sorted(subject.topics, key=lambda topic: (topic.order_index, topic.name))
        topic_preview = ", ".join(topic.name for topic in ordered_topics[:12])
        suffix = f", ... (+{len(ordered_topics) - 12} more)" if len(ordered_topics) > 12 else ""
        subject_summaries.append(f"{subject.name}: {topic_preview}{suffix}")

    schedule_preview = "\n".join(_format_schedule_line(entry) for entry in upcoming_entries[:8])
    system_prompt = (
        "You are an education-only assistant for a study planner app. "
        "Answer only educational questions such as academic concepts, formulas, programming, study methods, exam preparation, and syllabus-related guidance. "
        "Use the student's saved subjects, topics, and schedule when relevant, but do not restrict answers only to that data. "
        "If a question is outside education, do not answer it; respond briefly that you are restricted to educational help and suggest an educational alternative. "
        "If a term is ambiguous, unfamiliar, misspelled, or you are not confident about the exact concept, do not guess or invent an expansion. "
        "Instead, say you are not sure which concept the user means and ask for a clearer term or a bit of context. "
        "Do not provide travel, politics, entertainment, shopping, or other non-educational assistance. "
        "Do not mention internal routing, rules, or implementation details."
    )
    context_prompt = (
        "Student context:\n"
        f"Subjects and topics:\n" + ("\n".join(subject_summaries) or "No subjects saved.") + "\n\n"
        f"Upcoming schedule:\n{schedule_preview or 'No upcoming schedule.'}"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "system", "content": context_prompt},
    ]
    for item in history[-10:]:
        messages.append({"role": item.role, "content": item.content})
    messages.append({"role": "user", "content": message})
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                base_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": 0.5,
                },
            )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip(), provider
    except Exception:
        if provider in {"openai", "groq"} and api_key:
            return None, f"{provider}_fallback"
        return None, None


@router.get("/history/{user_id}", response_model=list[ChatHistoryItem])
async def chat_history(user_id: str, db: AsyncSession = Depends(get_db)):
    """Return the recent chat log for a user."""
    result = await db.execute(
        select(ChatMessageModel)
        .where(ChatMessageModel.user_id == user_id)
        .order_by(ChatMessageModel.created_at.desc())
        .limit(100)
    )
    messages = result.scalars().all()
    return [ChatHistoryItem.from_orm(msg) for msg in reversed(messages)]


@router.post("/ask", response_model=ChatAskResponse)
async def ask_chatbot(payload: ChatAskRequest, db: AsyncSession = Depends(get_db)):
    await _log_chat_message(db, payload.user_id, "user", payload.message, "user_query")
    if _is_non_educational_query(payload.message):
        answer, sources, suggestions = _non_educational_redirect()
        await _log_chat_message(db, payload.user_id, "assistant", answer, "education_only")
        return ChatAskResponse(
            answer=answer,
            sources=sources,
            suggestions=suggestions,
            mode="education_only",
        )

    if _needs_educational_clarification(payload.message):
        answer, sources, suggestions = _educational_clarification_redirect()
        await _log_chat_message(
            db, payload.user_id, "assistant", answer, "education_clarification"
        )
        return ChatAskResponse(
            answer=answer,
            sources=sources,
            suggestions=suggestions,
            mode="education_clarification",
        )

    result = await db.execute(
        select(Subject)
        .where(Subject.user_id == payload.user_id)
        .options(selectinload(Subject.topics))
    )
    subjects = list(result.scalars().unique().all())

    schedule_result = await db.execute(
        select(ScheduleEntry)
        .where(ScheduleEntry.user_id == payload.user_id, ScheduleEntry.completed == 0)
        .order_by(ScheduleEntry.scheduled_date, ScheduleEntry.start_time)
    )
    upcoming_entries = list(schedule_result.scalars().all())

    ai_answer, provider = await _llm_answer(
        payload.message,
        subjects,
        upcoming_entries,
        payload.history,
    )
    if ai_answer:
        await _log_chat_message(db, payload.user_id, "assistant", ai_answer, provider or "llm")
        return ChatAskResponse(
            answer=ai_answer,
            sources=["subjects", "topics", "schedule"],
            suggestions=["What should I study next?", "Show topics in a subject", "How do I revise this unit?"],
            mode=provider or "llm",
        )

    answer, sources, suggestions = _rule_based_answer(payload.message, subjects, upcoming_entries)
    await _log_chat_message(db, payload.user_id, "assistant", answer, provider or "rule_based")
    return ChatAskResponse(
        answer=answer,
        sources=sources,
        suggestions=suggestions,
        mode=provider or "rule_based",
    )
