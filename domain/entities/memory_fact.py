from dataclasses import dataclass

PROFILE = "profile"
TASK    = "task"
STUDY   = "study"
CONTACT = "contact"
GOAL    = "goal"
EVENT   = "event"

CATEGORIES = {PROFILE, TASK, STUDY, CONTACT, GOAL, EVENT}


@dataclass(slots=True)
class MemoryFact:
    category: str
    content: str
    key: str | None = None
    id: int | None = None
    source: str = "agent_detection"
    confidence: float = 1.0
    access_count: int = 0
    reinforcement_count: int = 0
    contradiction_count: int = 0
    retrieval_score_last: float | None = None
    last_accessed_at: float | None = None
    valid_at: float | None = None
    invalid_at: float | None = None
    created_at: float | None = None
    updated_at: float | None = None

@dataclass(slots=True)
class FactLink:
    from_id: int
    to_id: int
    relation: str
    strength: float = 1.0
    origin: str = "inferred"
    co_activation_count: int = 0
    id: int | None = None
    valid_at: float | None = None
    invalid_at: float | None = None