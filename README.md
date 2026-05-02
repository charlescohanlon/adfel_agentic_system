# ADFEL — CSC 580 Lab Companion

A student-facing agentic tutoring system for Cal Poly's CSC 580 lab course. The
assistant helps students work through assignments by giving **hints, not
answers**, while a separate Guardian agent enforces academic integrity by
classifying every question and verifying every draft response before it reaches
the student.

The repo is split in two:

- **`agentic_system/`** — a UI-agnostic Python package that owns all the agents,
  policy, storage, and retrieval logic. It exposes a single facade,
  `LabHarness`, and knows nothing about the web framework hosting it.
- **`app.py`** — a thin [Chainlit](https://chainlit.io) shell that wires the
  harness into a chat UI. It is the *only* place Chainlit is imported;
  swapping it for a CLI, a custom frontend, or a Slack bot requires no changes
  inside the package.

## How it works

Every student turn runs through this pipeline (`agentic_system/orchestrator.py`):

```
question
    │
    ▼
Guardian.validate ──► classify (CONCEPTUAL / PROCEDURAL / DIRECT_SOLUTION / …)
    │                 derive guidance level (FULL / MODERATE / MINIMAL / REJECTED)
    │                 escalate session after 3 violations
    │
    ▼
KnowledgeBase.search ──► RAG context (Azure AI Search; optional)
    │
    ▼
LabCompanion.respond ──► draft (constrained by guidance level)
    │
    ▼
Guardian.verify ──► pass / fail with feedback
    │           (on fail: retry up to VERIFIER_MAX_RETRIES; then safe fallback)
    │
    ▼
Participant.log_interaction (best-effort telemetry)
    │
    ▼
response to student
```

### The three agents

| Agent | Role | Backed by |
|---|---|---|
| **Lab Companion** | The only student-facing agent. Generates hint-style responses constrained by the per-turn guidance level. | `LLMClient` |
| **Guardian** | Two gates: input classification (academic-integrity policy) and output verification (does the draft give away the answer?). Tracks violations and escalates the session at the 3rd violation. | `LLMClient` + SQLite (`guardian.db`) |
| **Participant** | Learning-context tracker. Classifies each question's type/hint-level/difficulty and builds a narrative summary of the student's history that the Lab Companion uses as context. | `LLMClient` + SQLite (`participant.db`) |

The model is reached only through the `LLMClient` protocol
(`agentic_system/llm/base.py`). Two implementations ship in-package:

- `AzureOpenAILLM` — default; talks to Azure OpenAI via the `openai` SDK.
- `ClaudeLLM` — talks to Anthropic via the `anthropic` SDK
  (`ANTHROPIC_API_KEY` by default; pass `auth_token=` for an OAuth bearer).

Any object exposing a `complete(messages, *, temperature, max_tokens, json_mode)`
method can be injected at build time. Nothing under `agentic_system/` outside
the `llm/` package imports a vendor SDK.

### Public API

The embedder (`app.py` today; anything else tomorrow) only needs the `LabHarness` facade:

```python
from agentic_system import LabHarness

harness = LabHarness.build()              # env-driven defaults
state   = harness.start_session()
result  = harness.handle_turn(state, "what does KVL mean?")
print(result.response)
harness.end_session(state)
```

To swap backends (custom KB, remote-API store, a different LLM):

```python
from agentic_system import LabHarness, ClaudeLLM

# Use Claude via the Anthropic SDK (reads ANTHROPIC_API_KEY by default):
harness = LabHarness.build(llm=ClaudeLLM())

# Or compose multiple swaps:
harness = LabHarness.build(
    config=SystemConfig(...),
    participant_store=MyRemoteStore(...),
    guardian_store=MyRemoteStore(...),
    knowledge_base=MyKB(...),
    llm=MyLLMClient(...),
)
```

`ParticipantStore`, `GuardianStore`, `KnowledgeBase`, and `LLMClient` are
all `typing.Protocol`s — implement the methods, pass the instance in. The
LLM protocol is one method:

```python
class MyLLMClient:
    def complete(
        self,
        messages: list[dict],
        *,
        temperature: float = 0.4,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> str: ...
```

## Repository layout

```
adfel_agentic_system/
├── app.py                       Chainlit UI shell (only place chainlit is imported)
├── agentic_system/              UI-agnostic package
│   ├── __init__.py              Public re-exports
│   ├── api.py                   LabHarness facade — single public entry point
│   ├── config.py                SystemConfig dataclass + from_env()
│   ├── orchestrator.py          Per-turn pipeline (validate → RAG → draft → verify)
│   ├── models.py                Enums, Pydantic records, result dataclasses
│   ├── agents/
│   │   ├── lab_companion.py     Student-facing hint generator
│   │   ├── guardian.py          Integrity gate (validate + verify)
│   │   └── participant.py       Learning-context tracker
│   ├── policy/
│   │   └── engine.py            Pure: classification prompt, verification prompt,
│   │                            and the (classification, counters) → guidance mapping
│   ├── llm/
│   │   ├── base.py              LLMClient Protocol — single chat-completion method
│   │   ├── azure_openai.py      AzureOpenAILLM (the only file that imports `openai`)
│   │   └── claude.py            ClaudeLLM (the only file that imports `anthropic`)
│   ├── kb/
│   │   ├── base.py              KnowledgeBase Protocol + RetrievedDoc + format_context
│   │   ├── azure_search.py      AzureSearchKB (lazy-imports the SDK)
│   │   └── null.py              NullKB — used when search is unconfigured
│   └── store/
│       ├── base.py              ParticipantStore + GuardianStore Protocols
│       └── sqlite.py            Default SQLite implementations of both
├── data/                        SQLite files live here (gitignored)
├── public/                      Chainlit static assets (logo, favicon, theme)
├── pixi.toml                    Local dev environment + tasks
├── requirements.txt             Pip dependencies (mirrors pixi for Docker)
├── Dockerfile                   Container build
├── docker-compose.yml           One-command local container run
└── config.yaml                  Azure Container App deployment manifest
```

## Local development

The project uses [pixi](https://pixi.sh/) for environment management.

```bash
# 1. copy env template and fill in your Azure OpenAI credentials
cp .env.example .env
$EDITOR .env

# 2. install dependencies
pixi install

# 3. run the Chainlit dev server (auto-reload on save)
pixi run dev
# → http://localhost:8000
```

Other tasks:

```bash
pixi run start      # production-style: chainlit run -h --host 0.0.0.0 --port 8000
pixi run reset-db   # nuke local SQLite stores under data/
```

`pixi.toml` sets `PARTICIPANT_DB_PATH` and `GUARDIAN_DB_PATH` to absolute paths
under `data/` automatically when the env activates.

### Running with Docker

```bash
docker compose up --build
```

`docker-compose.yml` mounts `./data` to `/data` inside the container so the
SQLite files persist across restarts.

## Environment variables

All env reads happen in `SystemConfig.from_env()` (`agentic_system/config.py`)
or in `app.py`. The agents themselves never touch `os.environ`.

| Variable | Required? | Notes |
|---|---|---|
| `AZURE_OPENAI_ENDPOINT` | yes | Used by all three agents. |
| `AZURE_OPENAI_API_KEY` | yes | |
| `AZURE_OPENAI_DEPLOYMENT_NAME` | yes | The chat-model deployment (e.g. `gpt-4o`). |
| `AZURE_OPENAI_API_VERSION` | no | Defaults to `2024-12-01-preview`. |
| `AZURE_SEARCH_ENDPOINT` | no | Leave the three `AZURE_SEARCH_*` blank to disable RAG (the harness falls back to `NullKB`). |
| `AZURE_SEARCH_API_KEY` | no | |
| `AZURE_SEARCH_INDEX_NAME` | no | |
| `STUDENT_ID` | no | Single-user prototype identity. Default `default-student`. |
| `LAB_ID` | no | Default `default-lab`. |
| `COURSE_ID` | no | Default `CSC580`. |
| `PARTICIPANT_DB_PATH` | no | Default `data/participant.db`. |
| `GUARDIAN_DB_PATH` | no | Default `data/guardian.db`. |
| `RAG_TOP_N` | no | How many docs to retrieve. Default `3`. |
| `RAG_MAX_CONTENT_LENGTH` | no | Per-doc truncation in the prompt. Default `1000`. |
| `HISTORY_KEEP_TURNS` | no | Conversation history window passed to the Lab Companion. Default `6`. |
| `VERIFIER_MAX_RETRIES` | no | Retries when Guardian rejects a draft. Default `2`. |
| `LOG_LEVEL` | no | `INFO` by default. Set `DEBUG` to see classifications/retries inline in the UI. |

## Policy at a glance

`agentic_system/policy/engine.py` is intentionally a pure module so the
behavior is auditable in one place.

**Question classifications** (input gate):
- `CONCEPTUAL`, `PROCEDURAL`, `CLARIFICATION` — allowed.
- `DIRECT_SOLUTION` — hard rejection.
- `ANSWER_FARMING` — incremental extraction across turns; allowed but throttled.

**Guidance levels** (what shape the Lab Companion's response takes):
- `FULL` — normal hint-style tutoring.
- `MODERATE` — nudge harder toward independence; shorter answers.
- `MINIMAL` — at most one hint, no elaboration, no code.
- `REJECTED` — politely decline.

**Throttling rules** (`derive_guidance_level`):
- 3 violations in a session → escalate; all subsequent turns rejected.
- Q12+ → at least `MODERATE`. Q14+ → `MINIMAL`. Q16+ → `REJECTED`.
- Any `DIRECT_SOLUTION` classification → `REJECTED` for that turn.
- Any `ANSWER_FARMING` classification → `MINIMAL` for that turn.

**Failure modes** are all fail-safe: a classifier error defaults to
`PROCEDURAL` / `MODERATE`; a verifier error passes the draft through; a
companion error returns a polite "please rephrase" message.

## Azure deployment

The app currently deploys as an Azure Container App
(`config.yaml`). Beyond Azure OpenAI itself, you will typically also want:

- **Azure AI Foundry** — host the chat-model deployment, and (if RAG is on)
  the embedding-model deployment used to build the Search index.
- **Azure AI Search** — host the index. Configure a skillset to chunk
  documents and produce embeddings via the Foundry embedding deployment.
  Index field names expected by `AzureSearchKB`: `parent_id`, `chunk_id`,
  `chunk`, `title`.
- **Azure Storage** — Blob for the documents that feed AI Search; an Azure
  Files share if you want SQLite stores to persist across container
  restarts (mount it into the container at the path you point
  `PARTICIPANT_DB_PATH` / `GUARDIAN_DB_PATH` to).
- **Container Registry + Container App + Container Apps Environment** —
  see `config.yaml` for the deployed resource shape.

> ⚠️ Azure AI Search truncates documents above its size limit and rejects
> oversized files outright. When uploading textbook material, split it
> manually into per-chapter or per-section files before indexing.
