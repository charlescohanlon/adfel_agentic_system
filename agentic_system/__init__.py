"""
AIEIC — student-facing agentic tutoring harness.

Public API:

    from agentic_system import LabHarness, AieicConfig

    harness = LabHarness.build()
    state   = harness.start_session()
    result  = harness.handle_turn(state, "explain Thevenin equivalents")
    print(result.response, result.guidance_level)
    harness.end_session(state)

Custom backends (swap SQLite for a remote API, or KB for a different
retriever) can be injected:

    harness = LabHarness.build(
        config=AieicConfig.from_env(),
        participant_store=MyRemoteStore(...),
        guardian_store=MyRemoteStore(...),
        knowledge_base=MyKB(...),
    )
"""

from .api import LabHarness
from .config import AieicConfig
from .kb import AzureSearchKB, KnowledgeBase, NullKB, RetrievedDoc
from .models import (
    GuidanceLevel,
    QuestionClassification,
    SessionState,
    TurnResult,
    ValidateResult,
    VerifyResult,
)
from .store import (
    GuardianStore,
    ParticipantStore,
    SqliteGuardianStore,
    SqliteParticipantStore,
)

__all__ = [
    # facade
    "LabHarness",
    "AieicConfig",
    # types the embedder reads
    "SessionState",
    "TurnResult",
    "GuidanceLevel",
    "QuestionClassification",
    "ValidateResult",
    "VerifyResult",
    # extension points
    "ParticipantStore",
    "GuardianStore",
    "SqliteParticipantStore",
    "SqliteGuardianStore",
    "KnowledgeBase",
    "RetrievedDoc",
    "AzureSearchKB",
    "NullKB",
]
