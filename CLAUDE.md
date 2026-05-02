# CLAUDE.md

Project-level guide for Claude Code sessions on this repo. Read the
[README.md](./README.md) first for the *what*; this file is the *how to work
on it*.

## What this project is, in one paragraph

ADFEL is a hint-style tutoring assistant for Cal Poly's CSC 580 lab course.
Three agents collaborate per turn — a **Lab Companion** generates the response,
a **Guardian** classifies the question and verifies the draft for academic-
integrity violations, and a **Participant** logs the interaction and tracks
the student's learning context. All of that lives in the `agentic_system/`
Python package, which is *deliberately* decoupled from any UI. `app.py` is a
thin Chainlit shell that consumes the package's public facade (`LabHarness`).

## Architecture rules of the road

The repo recently went through a "decouple the agentic system" refactor (see
`git log` — commits `34b680a` and `1503ca8`). The shape that came out of
that refactor is the contract; please preserve it.

1. **Chainlit is imported in exactly one file: `app.py`.** Nothing under
   `agentic_system/` should `import chainlit`. If you find yourself wanting
   to, push the abstraction back into the harness's public types instead.

2. **`LabHarness` (in `agentic_system/api.py`) is the only public entry
   point.** The `__init__.py` re-exports a few result types
   (`SessionState`, `TurnResult`, `GuidanceLevel`, etc.) for the embedder's
   convenience. Don't grow that surface casually — extension is supposed to
   happen via injected backends, not new top-level functions.

3. **Backends are `typing.Protocol`s, not subclasses.** `ParticipantStore`,
   `GuardianStore`, `KnowledgeBase`, and `LLMClient` are all duck-typed.
   The default implementations (SQLite stores, AzureSearchKB, NullKB,
   AzureOpenAILLM) live next to the protocol definition. New backends
   should be new files implementing the same Protocol — don't widen the
   protocol to fit a backend.

   **Vendor SDKs are contained per-file.** Only
   `agentic_system/llm/azure_openai.py` may import the `openai` SDK; only
   `agentic_system/llm/claude.py` may import the `anthropic` SDK. Every
   other module in the package talks to the LLM through
   `LLMClient.complete()`. New providers (a self-hosted model, a
   deterministic stub for tests) ship as a new file under
   `agentic_system/llm/` implementing the same one-method protocol — do
   not reach into a vendor SDK from agents or policy code.

4. **`SystemConfig` is the *only* place env vars are read inside the
   package.** Constructed once via `SystemConfig.from_env()` (or built
   directly by an embedder that has its own settings system) and threaded
   through agents via constructor injection. Agents and policy code must
   never call `os.getenv` themselves.

5. **The policy engine is a pure module.** `agentic_system/policy/engine.py`
   contains the classification system prompt, the verification system
   prompt, and `derive_guidance_level` (a pure function from classification
   + counters → guidance). Auditability is the point — the rules are in one
   place, on one screen. Don't fragment policy across agents.

6. **All three agents follow constructor injection.** Each takes
   `(store=, llm=, config=)` (or just `llm=, config=` for Lab Companion,
   which has no store). `llm` is an `LLMClient`, not a raw SDK object.
   No globals, no module-level clients, no lazy singletons inside the
   package.

7. **Fail-safe over fail-loud, by design.** Every external call in the
   orchestrator is wrapped:
   - Classifier error → fall back to `PROCEDURAL` / `MODERATE`.
   - Verifier error → pass the draft through (fail-open).
   - KB error → empty context, proceed.
   - Companion error → return a polite "please rephrase" message.
   - Participant log error → swallow + log a warning.

   When adding new external integrations, match this pattern: log, fall back,
   keep the user-facing turn alive.

## Per-turn flow (you'll be re-deriving this constantly)

`Orchestrator.handle_turn` in `agentic_system/orchestrator.py`, lines ~81–152:

1. `Guardian.validate(question, history)` → `ValidateResult`.
   - Hard short-circuit on `REJECTED` or session-escalated.
2. `KB.search(question)` → format into `rag_context` (or empty block).
3. `LabCompanion.respond(...)` → draft.
4. `Guardian.verify(question, draft, guidance_level)` → pass/fail + feedback.
   - On fail: re-call `respond()` with feedback as `verifier_feedback`,
     up to `VERIFIER_MAX_RETRIES` (default 2).
   - On final retry failing: emit `SAFE_FALLBACK` from
     `agents/lab_companion.py`.
5. `Participant.log_interaction` (best-effort).
6. Append `(user, assistant)` pair to `state.conversation_history`.

`SessionState` is the opaque object the embedder holds across turns. It
carries the session id, the prefetched `StudentContext`, and the running
conversation history. The harness gives it back to the embedder at
`start_session()` and expects it back on every `handle_turn()`.

## Code map

```
app.py                              Chainlit shell. Three callbacks:
                                    on_chat_start / on_message / on_chat_end.
                                    Module-level _harness singleton; per-user
                                    SessionState in cl.user_session.

agentic_system/
  api.py                            LabHarness.build() — wires defaults from
                                    SystemConfig, allows injection of stores,
                                    KB, and llm (LLMClient).
  config.py                         SystemConfig dataclass. .from_env() is the
                                    only env-aware constructor.
  orchestrator.py                   The pipeline. Read this first when
                                    debugging behavior.
  models.py                         Enums (QuestionClassification, GuidanceLevel,
                                    ViolationType/Severity), Pydantic records
                                    (QuestionRecord, ViolationRecord,
                                    VerificationRecord), result dataclasses
                                    (ValidateResult, VerifyResult, TurnResult,
                                    SessionState, StudentContext).

  agents/
    lab_companion.py                Builds the system prompt with the
                                    GUIDANCE_INSTRUCTIONS table, RAG context,
                                    and (on retry) verifier feedback.
                                    SAFE_FALLBACK lives here.
    guardian.py                     validate() + verify(). Owns session
                                    lifecycle on the guardian DB. Records
                                    violations and triggers session escalation
                                    at violation #3.
    participant.py                  classify_question() (per-message LLM tag),
                                    log_interaction(), get_student_context()
                                    (LLM-generated narrative summary with a
                                    rule-based fallback).

  policy/
    engine.py                       CLASSIFICATION_SYSTEM_PROMPT,
                                    VERIFICATION_SYSTEM_PROMPT,
                                    classify_question(),
                                    verify_response(),
                                    derive_guidance_level() (pure mapping).
                                    Takes an LLMClient — no SDK awareness.

  llm/
    base.py                         LLMClient Protocol — one method,
                                    `complete(messages, *, temperature,
                                    max_tokens, json_mode) -> str`.
    azure_openai.py                 AzureOpenAILLM. The ONLY file in the
                                    package that imports `openai`. Lazy-
                                    imported so non-Azure embedders don't
                                    pay the cost.
    claude.py                       ClaudeLLM. The ONLY file in the
                                    package that imports `anthropic`.
                                    Reads ANTHROPIC_API_KEY by default;
                                    accepts api_key= or auth_token= for
                                    explicit auth (the latter for OAuth
                                    bearers, e.g. Pro/Max subscription
                                    tokens). Defaults to claude-opus-4-7,
                                    enables prompt caching on the system
                                    prompt, and drops sampling params on
                                    Opus 4.7 (it 400s if sent).

  kb/
    base.py                         KnowledgeBase Protocol, RetrievedDoc,
                                    format_context() helper.
    azure_search.py                 AzureSearchKB. Lazy-imports the Azure SDK
                                    so NullKB users don't pay the import cost.
                                    Expects index fields: parent_id, chunk_id,
                                    chunk, title.
    null.py                         NullKB. Returns []. Used when the
                                    AZURE_SEARCH_* env vars are blank.

  store/
    base.py                         ParticipantStore + GuardianStore Protocols.
                                    Sync API. dict in / dict out (no Pydantic
                                    leakage across the protocol boundary).
    sqlite.py                       Default impls. Per-agent DB file.
                                    Schemas declared at the top of the file.
```

## Common workflows

### Run it locally
```bash
pixi install
cp .env.example .env  # then fill in AZURE_OPENAI_*
pixi run dev          # auto-reload; http://localhost:8000
```

### Reset state between manual tests
```bash
pixi run reset-db     # rm data/*.db*
```

This is essential when iterating on policy/escalation behavior, because the
3-violation escalation is *persisted* per session and `STUDENT_ID` is by
default a single shared identity in the prototype.

### Add a new backend (e.g. swap SQLite for an HTTP API)

1. Implement `ParticipantStore` (or `GuardianStore`) in a new module under
   `agentic_system/store/`.
2. Inject it: `LabHarness.build(participant_store=MyRemoteStore(...))`.
3. Don't touch the agents — they only see the protocol.

### Swap the LLM

Two implementations ship: `AzureOpenAILLM` (default) and `ClaudeLLM`.
Switching to Claude is one line in `app.py`:

```python
from agentic_system import LabHarness, ClaudeLLM
_harness = LabHarness.build(llm=ClaudeLLM())  # reads ANTHROPIC_API_KEY
```

Adding a new provider (Ollama, a self-hosted endpoint, a deterministic
stub for tests):

1. Implement `LLMClient` in a new module under `agentic_system/llm/`. The
   protocol is one method: `complete(messages, *, temperature, max_tokens,
   json_mode) -> str`. When `json_mode=True`, the implementation must
   return a parseable JSON string (or raise) — callers `json.loads` the
   result.
2. Inject it: `LabHarness.build(llm=MyLLMClient(...))`.
3. Don't touch the agents or `policy/engine.py` — they only see the
   protocol. Don't add a vendor SDK import outside `agentic_system/llm/`.

### Tweak the integrity policy

Almost everything you'd want lives in `agentic_system/policy/engine.py`:
- The wording in `CLASSIFICATION_SYSTEM_PROMPT` controls how the input gate
  thinks about classifications.
- The wording in `VERIFICATION_SYSTEM_PROMPT` controls when the output gate
  rejects a draft.
- `derive_guidance_level` controls the throttling thresholds (Q12 / Q14 / Q16
  and the violation-count → escalation rule).

The Lab Companion's tone-by-guidance-level table is in
`agents/lab_companion.py` (`GUIDANCE_INSTRUCTIONS`).

### Run with Docker
```bash
docker compose up --build
```
The compose file mounts `./data` → `/data` inside the container so SQLite
state persists across restarts.

## Conventions

- **No new env reads outside `config.py`.** Add a field to `SystemConfig` and
  wire it through `from_env()` instead.
- **Result types are dataclasses; persistence rows are dicts.** Pydantic
  `*Record` models exist for the inserts but are immediately `.model_dump()`-ed
  before crossing the store boundary so the protocol stays JSON-shaped.
- **All store/agent methods are sync.** The embedder offloads to a thread
  (`asyncio.to_thread` in `app.py`) when it cares about an event loop.
- **Logging, not print.** `logging.getLogger(__name__)` at the top of every
  module. The embedder configures handlers; the package never does.
- **Lazy-import heavy SDKs.** `AzureSearchKB.search` lazy-imports
  `azure.search.documents` so users running `NullKB` don't pay the cost.
  Follow this pattern for any new optional dependency.
- **Default values where it makes sense.** `SystemConfig` ships with sane
  defaults so tests / one-off scripts can build a harness without juggling 15
  env vars; `LabHarness.build()` will only refuse to start if Azure OpenAI is
  truly unconfigured *and* no `llm` was injected.

## When in doubt

- `agentic_system/orchestrator.py` is the source of truth for runtime behavior.
- `agentic_system/policy/engine.py` is the source of truth for what counts as
  a violation.
- `agentic_system/api.py` is the source of truth for the embedder contract.
- `agentic_system/__init__.py` is the source of truth for the public surface.

If you'd add an export to `__init__.py` that doesn't already live there, stop
and consider whether the embedder really needs it, or whether the harness
should expose the capability through `LabHarness` instead.
