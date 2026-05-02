"""Storage abstraction for the AIEIC harness.

Two protocols — `ParticipantStore` and `GuardianStore` — define the entire
persistence surface. The default implementations are SQLite-backed
(`SqliteParticipantStore`, `SqliteGuardianStore`); a future remote-API
implementation only has to satisfy the same protocols.
"""

from .base import GuardianStore, ParticipantStore
from .sqlite import SqliteGuardianStore, SqliteParticipantStore

__all__ = [
    "ParticipantStore",
    "GuardianStore",
    "SqliteParticipantStore",
    "SqliteGuardianStore",
]
