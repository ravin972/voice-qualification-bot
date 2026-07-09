# Voice Qualification Bot

A config-driven voice qualification engine: it answers an inbound phone call,
asks a fixed set of yes/no questions, and returns a **deterministic**
qualified/rejected verdict — targeting sub-second turn latency. A live React
dashboard watches every call happen in real time.

One engine runs multiple bots as **plain YAML scenario files** — no code
changes to add a new one:

| Bot | Questions | Qualifies as |
|---|---|---|
| **Home Renovation Lead Qualifier** | own your home? · budget over $10,000? · start within 3 months? | `HOT_LEAD` |
| **QuickRupee Loan Qualification Bot** | salaried employee? · monthly salary above ₹25,000? · live in a metro city? | `ELIGIBLE` |

> **Core guarantee:** the LLM's only job is to normalise speech into
> `YES / NO / REPEAT / UNCLEAR`. **All eligibility logic is deterministic
> Python** (`QualificationService`), never the model — see
> [docs/ARCHITECTURE.md §7, ADR-2](./docs/ARCHITECTURE.md#7-key-architectural-decisions-adrs).

---

## What's implemented

| Piece | Status |
|---|---|
| Architecture: DI graph, typed settings, structured logging, app factory | ✅ |
| WebSocket transport (Twilio Media Streams) + TwiML webhook | ✅ real-call verified |
| **Live-call bridge** — `/media-stream` audio in/out fully wired to `ConversationService.run()` | ✅ real-call verified |
| Conversation state machine — Open/Closed, table-driven, no nested `if`s | ✅ |
| Vendor integrations: Deepgram (STT), OpenAI (intent classifier) | ✅ |
| **TTS fallback chain** — ElevenLabs → Cartesia → OpenAI TTS → local OS voice (dev only) | ✅ real-call verified |
| Qualification rules — one implementation drives every scenario | ✅ |
| Both bots as YAML scenario config, auto-discovered at startup | ✅ |
| Docker image + `docker compose up` | ✅ built & run-tested |
| **`ConversationService`** — full orchestration: greeting → questions → LLM classify → state machine → verdict → goodbye | ✅ |
| Hot-lead → human-agent transfer, with a logged simulation mode when no Twilio credentials are configured | ✅ |
| **Local test-mode HTTP endpoints** (`/conversation/test/start`, `/conversation/test/message`) — exercise the real engine with no Twilio/WebSocket/Deepgram | ✅ |
| **Live event bus + `/dashboard/stream` WebSocket** — every call publishes an immutable snapshot after each turn | ✅ real-call verified |
| **React dashboard** (`frontend/`) — Live phone-call view + a text-mode test console, same cards drive both | ✅ |
| `/health` — scenario-loader status + vendor config presence | ✅ |
| Per-turn latency logging (STT/LLM/TTS/total), tagged with `conversation_id`/`call_sid` | ✅ |

Everything above is implemented, unit- or integration-tested, and has been
verified against a **real answered Twilio phone call** end to end — not just
imported or run through `TestClient` — see [Verification](#verification).

👉 **[`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md)** has the full design: dependency
rules, ADRs, and Mermaid diagrams (layers, components, sequence, state machine).

---

## Stack

| Concern | Choice | Why |
|---|---|---|
| Web / async | **FastAPI + asyncio** | Non-blocking I/O for concurrent calls |
| Audio transport | **Twilio Media Streams** over `wss://` | Real-time full-duplex voice |
| STT | **Deepgram** (streaming) | Low-latency phone-call ASR |
| Intent classification | **OpenAI** (JSON mode, `temperature=0`) | Constrained speech→enum classifier only |
| TTS | **ElevenLabs → Cartesia → OpenAI TTS → local OS voice** | Priority-ordered fallback chain — a billing/auth failure or outage on one vendor falls through to the next rather than the call going silent; the local voice only ever runs in `local` dev |
| Live observability | **In-process event bus → `/dashboard/stream` WebSocket** | Every call publishes an immutable per-turn snapshot; the React dashboard renders it live |
| Frontend | **React 19 + Vite + TanStack Query + Recharts** | Live phone-call view and a text-mode test console over the same cards |
| Config | **pydantic-settings** + YAML | Typed env validation; scenarios as external config |
| Logging | **structlog** | Structured JSON events; never `print` |

Every vendor sits behind an interface (port) and is swappable from one
composition root — see [`app/config/dependencies.py`](./app/config/dependencies.py).

---

![Dashboard](docs\images\dashboard.png)
---

## Scenario configuration (the architectural highlight)

Bots are **not** Python code — they're YAML files under
[`app/scenarios/data/`](./app/scenarios/data/). The registry scans that
directory at startup and loads whatever it finds; adding a third bot means
adding a third file, nothing else.

```yaml
# app/scenarios/data/loan_qualifier.yaml
bot: loan_qualifier

questions:
  - id: salaried
    text: Are you a salaried employee?
  - id: salary
    text: Is your monthly salary above ₹25,000?
  - id: metro
    text: Do you live in a metro city?

success:
  message: Congratulations. An agent will contact you shortly.

failure:
  message: Unfortunately, you do not meet the current eligibility criteria.
```

That's the entire minimal shape — `name`, per-outcome `label`, `greeting`,
`reprompt_unclear`, and `goodbye` are optional and fall back to sensible
defaults (see [`app/scenarios/loader.py`](./app/scenarios/loader.py)). The
shipped files use the full shape for both `HOT_LEAD` and `ELIGIBLE` labels.

Malformed YAML fails fast with a clear, file-located error
(`ScenarioDefinitionError`) instead of a confusing downstream crash.

---

## How it works

1. Twilio hits `POST /twilio/voice`; we return TwiML that opens a media stream.
2. The `wss://…/media-stream` WebSocket receives audio, builds a `CallSession`,
   and starts `ConversationService.run()` as a concurrent task bridged to the
   socket via an `asyncio.Queue` (`app/websocket/handler.py`).
3. `ConversationService` streams audio → **Deepgram** → transcript.
4. **OpenAI** normalises the transcript into a single `Intent`.
5. The `Intent` drives an explicit **state machine** (no nested `if`s).
6. Once all gates are answered, **`QualificationService` (pure Python)** decides,
   and a `HOT_LEAD` outcome can trigger **Twilio** agent transfer.
7. The outcome is spoken through the **TTS fallback chain** (ElevenLabs, then
   Cartesia, then OpenAI TTS, falling through on any billing/auth failure or
   outage); the call reaches `ENDED`.
8. After every turn, `ConversationService` publishes an immutable snapshot
   (state, qualification progress, latency, transcript) onto an in-process
   event bus; anyone connected to `/dashboard/stream` — including the React
   dashboard — sees it arrive live, while the call is still in progress.

Every step above is implemented, tested, and has been driven by a real,
answered phone call (see [Verification](#verification)). Steps 3–6 are also
fully exercisable without a phone call at all, over plain HTTP — see the next
section.

---

## Local testing without Twilio, WebSockets, or Deepgram

`POST /conversation/test/start` and `POST /conversation/test/message` drive
the real state machine, the real OpenAI classifier, and the real qualification
service over plain HTTP/JSON — no telephony, audio, or WebSocket required.
This is the fastest way to exercise the whole decision engine (including a
scripted demo) without any vendor account, and it's also what the frontend's
"Test console" mode drives.

```bash
# Start a conversation
curl -s -X POST http://localhost:8000/conversation/test/start \
  -H "Content-Type: application/json" \
  -d '{"scenario_id": "lead_qualifier"}'
# -> {"conversation_id": "test_...", "state": "QUESTION_ONE",
#     "messages": ["Hi, thanks for your interest...", "Do you own your home?"], ...}

# Answer each question in turn
curl -s -X POST http://localhost:8000/conversation/test/message \
  -H "Content-Type: application/json" \
  -d '{"conversation_id": "test_...", "text": "yes"}'
# ...repeat with "yes" two more times to reach a HOT_LEAD verdict.
```

The response shape (`ConversationTurnResponse`) and both request bodies are
fully documented in the interactive OpenAPI docs at `/docs` once the server is
running. Full interactive docs and the schemas are visible at
[http://localhost:8000/docs](http://localhost:8000/docs).

`ConversationService.start_test_conversation`/`submit_test_message` reuse the
exact same decision core as the live-call path (`run()`) — no qualification or
state-transition logic is duplicated between the two; only audio delivery
(TTS + WebSocket vs. plain JSON) differs, and text-mode never publishes to the
event bus (it isn't a phone call). See
[`app/api/conversation_testing.py`](./app/api/conversation_testing.py).

---

## Live dashboard

`frontend/` is a React app with two modes:

- **Live phone call** — subscribes to `/dashboard/stream` and renders each
  call's snapshot (transcript, qualification checklist, state diagram,
  latency, final verdict) as it's published, live, while the call is still
  happening. A short in-memory replay buffer means opening the dashboard
  after a call still repaints its outcome.
- **Test console** — the original text-driven mode: type the caller's replies
  and drive the same `/conversation/test/*` endpoints described above.

The dashboard auto-switches to Live the instant a real call connects. See
[`frontend/README.md`](./frontend/README.md) for the frontend's own stack,
layout, and how to run it (`npm install && npm run dev` from `frontend/`,
backend running first).

---

## Quickstart

### Docker (recommended)

```bash
cp .env.example .env        # fill in your API keys
docker compose up --build
```

```bash
curl http://localhost:8000/health
curl -X POST "http://localhost:8000/twilio/voice?scenario=loan_qualifier"
```

Exposing this to real Twilio calls during development needs a public tunnel
(e.g. ngrok) pointed at port 8000; set `PUBLIC_BASE_URL` to that URL, and
point the Twilio number's Voice webhook at `<PUBLIC_BASE_URL>/twilio/voice`.

### Local (Python 3.12)

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt   # runtime + test/lint tooling
cp .env.example .env                  # fill in your API keys
uvicorn app.main:app --reload
# → http://localhost:8000/health   and   http://localhost:8000/docs
```

> **`.env` gotcha:** don't put `# comments` on the same line as a value.
> `python-dotenv` (local runs) strips them, but Docker's `env_file:` mechanism
> does not, and will pass the comment through as part of the value.

### Frontend dashboard

```bash
cd frontend
npm install
npm run dev
# → http://localhost:5173/ (Vite proxies /api/* — including the dashboard
#   WebSocket — to the backend on :8000; no CORS config, no backend change)
```

---

## Testing

```bash
pip install -r requirements-dev.txt

pytest                                   # everything (unit + integration)
pytest -m unit                           # pure logic — fast, no I/O
pytest -m integration                    # real FastAPI app via TestClient (HTTP + WebSocket)
pytest --cov=app --cov-report=term-missing   # coverage report
```

```
tests/
├── conftest.py            # shared fixtures + unit/integration auto-marking
├── unit/                  # state machine, qualification rules, scenario loader,
│                          # both-flows reuse proof, OpenAI classifier (fake client),
│                          # TTS fallback chain + adapters, event bus
└── integration/           # health/TwiML endpoints, WebSocket media-stream
                            # lifecycle, dashboard live-stream, DI-wiring —
                            # all via a real ASGI app
```

**175 tests pass.** The small amount of uncovered code is almost entirely the
Deepgram/ElevenLabs callback-bridge internals and the local-OS-voice fallback
tier — those were verified manually against fake vendor clients / a mocked
engine during development (documented in the module docstrings) rather than
committed as brittle SDK-internals tests.

---

## Verification

Every claim of "done" above was actually exercised, not just imported:

- **Real Twilio phone calls, twice, answered live**: a real inbound/outbound
  call was placed and spoken to, driving Twilio → the media-stream WebSocket
  → Deepgram → OpenAI intent classification → the state machine →
  qualification → TTS fallback → audio back to the caller → a `HOT_LEAD`
  verdict, with per-turn latency logged throughout.
- **TTS fallback chain, proven under a real vendor failure**: ElevenLabs
  genuinely returned `402 Payment Required` (a real billing-plan limitation,
  not simulated) on both live calls, and every line fell through to OpenAI TTS
  automatically — confirmed from the structured logs (`tts.provider_failed`
  → `tts.provider_selected`).
- **Live dashboard, proven during a real call**: a WebSocket subscriber (and
  separately, the actual React app in a browser) received the call's
  snapshots live, interleaved with the caller speaking — not replayed after
  the fact — culminating in the same `HOT_LEAD` verdict.
- **Docker:** `docker build` succeeded and `docker compose up` was run for
  real — `/health` and `/twilio/voice` were curled against the live
  container, and Docker's own `HEALTHCHECK` reported `healthy`.
- **WebSocket transport:** the full Twilio Media Streams frame lifecycle
  (`connected → start → media → stop`) was driven through the real app via
  `TestClient`, including malformed-frame and abrupt-disconnect handling.
- **Vendor adapters:** STT/TTS async bridge plumbing (callback → queue →
  `AsyncIterator`) was stress-tested with fake vendor clients for the normal
  path, timeouts, provider errors, and early-consumer-exit — not just happy path.
- **Qualification rules:** parametrized across both real scenarios, proving
  one implementation (no per-bot branching) drives both bots correctly.
- **Frontend:** `tsc -b`, `vite build` (2920 modules), and `oxlint` all clean;
  the dashboard was opened in a real browser and confirmed rendering a live
  call.

---

## Environment variables

```bash
cp .env.example .env
```

All variables (Twilio / Deepgram / OpenAI / ElevenLabs / Cartesia
credentials, log level, default scenario, reprompt limit) are documented in
[`.env.example`](./.env.example) and validated at startup by
[`app/config/settings.py`](./app/config/settings.py) — the app fails fast
with a clear error if something required is missing or malformed, rather than
failing confusingly later on a live call.

The TTS fallback chain degrades gracefully as vendors are configured or not:
ElevenLabs and OpenAI TTS are always in the chain (OpenAI reuses
`OPENAI_API_KEY`, already required for the intent classifier); Cartesia only
joins the chain once **both** `CARTESIA_API_KEY` and `CARTESIA_VOICE_ID` are
set (voice ids are account-specific — there's no safe default to guess); the
local OS voice only ever runs when `ENVIRONMENT=local`.

---

## Tooling

```bash
ruff check .    # lint + import sort  — clean
mypy app        # strict type checking — clean (45 source files)
```

Both pass with zero errors as of this commit (vendor SDKs without type stubs —
`twilio`, `deepgram-sdk`, `pyttsx3`, `pythoncom` — are explicitly exempted in
`pyproject.toml`, not silenced globally).

```bash
cd frontend
npm run build   # tsc -b && vite build — clean
npm run lint    # oxlint — clean
```

---

## Project layout

```
app/
├── api/                # HTTP: /health, /twilio/voice, /conversation/test/*
├── websocket/           # wss:// media-stream transport, /dashboard/stream
├── state_machine/       # table-driven FSM + Open/Closed policies
├── services/            # STT/TTS-fallback-chain/LLM/telephony adapters,
│                        # qualification, orchestrator, event bus,
│                        # in-memory store backing the local test-mode endpoints
├── models/               # Pydantic domain models incl. the dashboard snapshot
├── scenarios/            # YAML loader, registry, data/*.yaml bot definitions
├── prompts/               # LLM system prompt (intent classifier only)
├── config/                # settings + DI composition root
└── main.py
frontend/                 # React dashboard — Live phone-call view + test console
tests/
├── unit/
└── integration/
docker/Dockerfile · docker-compose.yml
requirements.txt · requirements-dev.txt · .env.example
docs/ARCHITECTURE.md · LICENSE
```

Full annotated tree: [`docs/ARCHITECTURE.md` §6](./docs/ARCHITECTURE.md#6-folder-structure).

---

## Future improvements

- **Latency:** barge-in cancellation, connection pooling/warm sockets,
  speculative TTS of the next question, pre-warming the OpenAI connection to
  avoid the observed cold-start timeout on a call's first classification.
- **Resilience:** the TTS side now has a full vendor fallback chain; STT
  (Deepgram) and the LLM classifier are still single-vendor — the same
  fallback pattern could extend there.
- **Delivery:** WhatsApp/SMS follow-up on qualification, CRM webhook on
  outcome, gating agent transfer per-scenario rather than globally
  (`Scenario.requires_agent_transfer` — currently any qualified scenario
  transfers if telephony + a destination number are configured).
- **Platform:** persistent call/session store (both the conversation store and
  the dashboard's event-bus replay buffer are in-memory and per-process today),
  per-scenario analytics, multi-tenant scenario management, Kubernetes
  deployment, a small admin UI or CLI for validating a scenario YAML file
  before deploying it.
- **Dashboard:** per-call history/selection in Live mode (today it shows the
  current/most-recent call only), route-level code-splitting if the frontend
  grows more pages (bundle is ~875 KB minified today).
- **Quality:** golden-transcript eval set for the intent normaliser, load tests
  for concurrent-call throughput, CI pipeline running lint/type-check/tests.

- **Call history**
- **Agent transfer**
- **Multi-tenant support**
- **Redis Event Bus**
- **Kafka**
- **Kubernetes**

---

## License

MIT — see [`LICENSE`](./LICENSE). Originally built as a hiring-assignment
deliverable.
