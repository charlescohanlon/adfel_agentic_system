"""
Chainlit prototype shell.

This file is the ONLY place Chainlit is imported. The agentic system lives
in `agentic_system/` and knows nothing about Chainlit; replacing this file with a
different UI (a custom web frontend, a CLI, a Slack bot, ...) requires no
changes inside the `agentic_system` package.

Public API used:
    LabHarness.build()
    harness.start_session()  -> SessionState
    harness.handle_turn(state, question) -> TurnResult
    harness.end_session(state)
"""

from __future__ import annotations

import asyncio
import logging
import os

import chainlit as cl
from dotenv import load_dotenv

from agentic_system import LabHarness, SessionState

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# Single harness for the whole process. Chainlit's user_session can't reuse
# objects across reloads anyway, so a module-level singleton is fine and
# avoids re-initializing SQLite + the OpenAI client on every chat.
_harness: LabHarness | None = None


def _get_harness() -> LabHarness:
    global _harness
    if _harness is None:
        _harness = LabHarness.build()
    return _harness


@cl.on_chat_start
async def on_start() -> None:
    harness = _get_harness()
    state: SessionState = await asyncio.to_thread(harness.start_session)
    cl.user_session.set("session_state", state)

    intro = (
        "Welcome to the CSC 580 Lab Companion. I'll help you work through "
        "your assignments by giving hints — not answers. Ask me about the "
        "lab manual, concepts you want to understand, or errors you're "
        "running into."
    )
    if state.student_context.total_questions > 0:
        intro += (
            f"\n\n*(Picking up where we left off — "
            f"{state.student_context.total_questions} prior questions on file.)*"
        )
    await cl.Message(content=intro).send()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    harness = _get_harness()
    state: SessionState | None = cl.user_session.get("session_state")
    if state is None:
        state = await asyncio.to_thread(harness.start_session)
        cl.user_session.set("session_state", state)

    msg = await cl.Message(content="").send()

    try:
        result = await asyncio.to_thread(harness.handle_turn, state, message.content)
    except Exception:
        logger.exception("handle_turn failed")
        msg.content = "Sorry — something went wrong on my side. Please try again."
        await msg.update()
        return

    msg.content = result.response

    if logger.isEnabledFor(logging.DEBUG):
        msg.content += (
            f"\n\n---\n*debug: classification={result.classification} "
            f"guidance={result.guidance_level} retries={result.retries} "
            f"verifier_passes={result.verifier_passes} "
            f"fallback={result.fallback}*"
        )
    await msg.update()


@cl.on_chat_end
async def on_end() -> None:
    harness = _get_harness()
    state: SessionState | None = cl.user_session.get("session_state")
    if state is not None:
        try:
            await asyncio.to_thread(harness.end_session, state)
        except Exception:
            logger.exception("end_session failed")
