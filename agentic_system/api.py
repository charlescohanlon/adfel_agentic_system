"""
Public facade for the ADFEL student-facing harness.

Embedders only need this class:

    from agentic_system import LabHarness

    harness = LabHarness.build()                   # env defaults + SQLite + AzureSearch
    state   = harness.start_session()
    result  = harness.handle_turn(state, "what does KVL mean?")
    print(result.response)
    harness.end_session(state)

To inject custom backends (e.g. an HTTP-API store later):

    harness = LabHarness.build(
        config=SystemConfig(...),
        participant_store=MyRemoteParticipantStore(...),
        guardian_store=MyRemoteGuardianStore(...),
        knowledge_base=MyKB(...),
        openai_client=my_preconfigured_client,
    )

This module is the ONLY place a UI shell should import from `agentic_system` for
day-to-day operation. (It re-exports the result types via `agentic_system` itself.)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from .agents import GuardianAgent, LabCompanion, ParticipantAgent
from .config import SystemConfig
from .kb import AzureSearchKB, KnowledgeBase, NullKB
from .models import SessionState, TurnResult
from .orchestrator import Orchestrator
from .store import (
    GuardianStore,
    ParticipantStore,
    SqliteGuardianStore,
    SqliteParticipantStore,
)

logger = logging.getLogger(__name__)


@dataclass
class LabHarness:
    """The single public entry point of the ADFEL system.

    Construct with `LabHarness.build()`. The returned instance is safe to
    cache for the lifetime of the embedder process.
    """

    config: SystemConfig
    participant: ParticipantAgent
    guardian: GuardianAgent
    companion: LabCompanion
    knowledge_base: KnowledgeBase
    _orchestrator: Orchestrator

    # -------------------------------------------------------- construction
    @classmethod
    def build(
        cls,
        *,
        config: Optional[SystemConfig] = None,
        participant_store: Optional[ParticipantStore] = None,
        guardian_store: Optional[GuardianStore] = None,
        knowledge_base: Optional[KnowledgeBase] = None,
        openai_client: Optional[Any] = None,
    ) -> "LabHarness":
        cfg = config or SystemConfig.from_env()

        if not cfg.llm_configured and openai_client is None:
            raise RuntimeError(
                "Azure OpenAI is not configured. Set AZURE_OPENAI_ENDPOINT, "
                "AZURE_OPENAI_API_KEY, AZURE_OPENAI_DEPLOYMENT_NAME — or pass "
                "an openai_client to LabHarness.build()."
            )

        llm = openai_client or _build_default_llm(cfg)
        p_store = participant_store or SqliteParticipantStore(cfg.participant_db_path)
        g_store = guardian_store or SqliteGuardianStore(cfg.guardian_db_path)
        kb = knowledge_base or _build_default_kb(cfg)

        participant = ParticipantAgent(store=p_store, openai_client=llm, config=cfg)
        guardian = GuardianAgent(store=g_store, openai_client=llm, config=cfg)
        companion = LabCompanion(openai_client=llm, config=cfg)

        orchestrator = Orchestrator(
            config=cfg,
            participant=participant,
            guardian=guardian,
            companion=companion,
            knowledge_base=kb,
        )

        logger.info(
            "LabHarness built: student_id=%s lab_id=%s kb=%s",
            cfg.student_id, cfg.lab_id, type(kb).__name__,
        )
        return cls(
            config=cfg,
            participant=participant,
            guardian=guardian,
            companion=companion,
            knowledge_base=kb,
            _orchestrator=orchestrator,
        )

    # -------------------------------------------------------- public API
    def start_session(self) -> SessionState:
        return self._orchestrator.start_session()

    def handle_turn(self, state: SessionState, question: str) -> TurnResult:
        return self._orchestrator.handle_turn(state, question)

    def end_session(self, state: SessionState) -> None:
        self._orchestrator.end_session(state)


# --------------------------------------------------------------- defaults
def _build_default_llm(config: SystemConfig) -> Any:
    """Build a sync `AzureOpenAI` client from config. Lazy import."""
    from openai import AzureOpenAI

    return AzureOpenAI(
        azure_endpoint=config.azure_openai_endpoint,
        api_key=config.azure_openai_api_key,
        api_version=config.azure_openai_api_version,
    )


def _build_default_kb(config: SystemConfig) -> KnowledgeBase:
    if not config.search_enabled:
        return NullKB()
    return AzureSearchKB(
        endpoint=config.azure_search_endpoint,
        api_key=config.azure_search_api_key,
        index_name=config.azure_search_index,
        default_top=config.rag_top_n,
    )
