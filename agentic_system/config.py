"""
Configuration for the harness.

`SystemConfig` is a plain dataclass — no implicit env loading. Embedders
that want env-driven config call `SystemConfig.from_env()`; embedders that
want to drive everything from their own settings system construct it
directly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path


@dataclass(frozen=True)
class SystemConfig:
    # ---- Identity ----------------------------------------------------------
    student_id: str = "default-student"
    lab_id: str = "default-lab"
    course_id: str = "CSC580"

    # ---- Storage paths (defaults; overridden when injecting custom stores) -
    participant_db_path: Path = field(default_factory=lambda: Path("data/participant.db"))
    guardian_db_path: Path = field(default_factory=lambda: Path("data/guardian.db"))

    # ---- Azure OpenAI ------------------------------------------------------
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = ""
    azure_openai_api_version: str = "2024-12-01-preview"

    # ---- Knowledge base (Azure AI Search) — optional -----------------------
    azure_search_endpoint: str = ""
    azure_search_api_key: str = ""
    azure_search_index: str = ""

    # ---- Tutoring knobs ----------------------------------------------------
    rag_top_n: int = 3
    rag_max_content_chars: int = 1000
    history_keep_turns: int = 6
    verifier_max_retries: int = 2

    # ---- Properties --------------------------------------------------------
    @property
    def search_enabled(self) -> bool:
        return bool(
            self.azure_search_endpoint
            and self.azure_search_api_key
            and self.azure_search_index
        )

    @property
    def llm_configured(self) -> bool:
        return bool(
            self.azure_openai_endpoint
            and self.azure_openai_api_key
            and self.azure_openai_deployment
        )

    # ---- Constructors ------------------------------------------------------
    @classmethod
    def from_env(cls, **overrides) -> "SystemConfig":
        """Build a config from environment variables. Overrides win.

        Embedders that don't want env-driven config should construct
        `SystemConfig(...)` directly instead of calling this.
        """
        base = cls(
            student_id=os.getenv("STUDENT_ID", "default-student"),
            lab_id=os.getenv("LAB_ID", "default-lab"),
            course_id=os.getenv("COURSE_ID", "CSC580"),
            participant_db_path=Path(
                os.getenv("PARTICIPANT_DB_PATH", "data/participant.db")
            ),
            guardian_db_path=Path(
                os.getenv("GUARDIAN_DB_PATH", "data/guardian.db")
            ),
            azure_openai_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", ""),
            azure_openai_api_key=os.getenv("AZURE_OPENAI_API_KEY", ""),
            azure_openai_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", ""),
            azure_openai_api_version=os.getenv(
                "AZURE_OPENAI_API_VERSION", "2024-12-01-preview"
            ),
            azure_search_endpoint=os.getenv("AZURE_SEARCH_ENDPOINT", ""),
            azure_search_api_key=os.getenv("AZURE_SEARCH_API_KEY", ""),
            azure_search_index=os.getenv("AZURE_SEARCH_INDEX_NAME", ""),
            rag_top_n=int(os.getenv("RAG_TOP_N", "3")),
            rag_max_content_chars=int(os.getenv("RAG_MAX_CONTENT_LENGTH", "1000")),
            history_keep_turns=int(os.getenv("HISTORY_KEEP_TURNS", "6")),
            verifier_max_retries=int(os.getenv("VERIFIER_MAX_RETRIES", "2")),
        )
        return replace(base, **overrides) if overrides else base
