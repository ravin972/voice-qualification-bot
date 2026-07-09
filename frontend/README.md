# Voice Qualification Dashboard

A conversation-analytics dashboard for the Voice AI backend in the parent
directory. It has two modes, switchable at the top of the page:

- **Live phone call** — subscribes to the backend's `/dashboard/stream`
  WebSocket and renders a real Twilio call's transcript, qualification
  progress, state machine, and latency **as the call happens**, no mock data,
  no fake latency, no placeholder recordings.
- **Test console** — drives the backend's local test-mode HTTP endpoints
  (`/conversation/test/*`) so the same cards can be exercised by typing
  replies, without a phone call.

The dashboard auto-switches to Live the instant a real call connects.

---

## Live mode: how it stays honest

The backend's live-call path (`ConversationService.run()`, wired to
Twilio/Deepgram/the TTS fallback chain) publishes an immutable snapshot
(`ConversationUpdate`) to an in-process event bus after every meaningful turn
— see the parent repo's `docs/ARCHITECTURE.md` §7 ADR-9. `useLiveCallFeed`
subscribes to that bus over `/dashboard/stream` and folds each snapshot into
the same UI state shape the test-console hook produces, so every card below
renders either source unchanged.

A short in-memory replay buffer on the backend means opening the dashboard
right after a call still repaints its outcome — you don't have to be
connected while the call happens to see the result.

### What's real vs. honestly unavailable

| Card | Status | Why |
|---|---|---|
| Conversation Timeline / Transcript | ✅ Real | Live mode: the call's actual spoken/heard lines, streamed as they happen. Test mode: the exact requests/responses you drove. |
| Qualification Progress | ✅ Real | Live mode: `qualification_progress` on each snapshot. Test mode: derived from `answers` + `questions`. |
| Conversation State | ✅ Real | The live state-machine node, either from the snapshot or the test-mode response. |
| Latency (STT/LLM/TTS/Total) | ✅ Real | The backend's own `measure()` timings. In live mode, `stt_ms`/`tts_ms` are populated from the real call; in text mode, those ports are never touched so they're `null`. |
| Latency chart / turn count / duration | ✅ Real | Accumulated client-side from real per-turn data, either source. |
| AI Summary | ✅ Real, rule-based (test mode only) | Composed by the backend from the real recorded answers/verdict — deliberately *not* branded as an LLM narrative, since it isn't one. Not produced on the live path today. |
| System Status | ✅ Real | Polls the backend's real `GET /health` (scenario loader + vendor credential presence). |
| Sentiment | ⬜ Unavailable | No sentiment analysis exists in the backend. |
| Confidence (per-answer %) | ⬜ Unavailable | The classifier returns a label only, never a probability. |
| Recording / Audio Player | ⬜ Unavailable | The backend never records or stores call audio. |

---

## Tech stack

React 19 · Vite · TypeScript · Tailwind CSS v4 · shadcn/ui (Radix) · TanStack
React Query · Recharts · Framer Motion · Lucide icons.

## Project layout

```
src/
├── components/
│   ├── ui/           # shadcn/ui primitives (generated)
│   └── dashboard/     # every card + DashboardView (shared grid), ModeToggle,
│                       # LiveStatusBar
├── hooks/
│   ├── useLiveCallFeed.ts         # subscribes to /dashboard/stream, folds
│   │                               # ConversationUpdate snapshots into UI state
│   ├── useConversationEngine.ts   # drives /conversation/test/start+message
│   ├── useHealth.ts               # polls GET /health
│   └── useElapsedSeconds.ts
├── lib/
│   ├── api.ts          # fetch-based API client
│   ├── format.ts        # duration/latency/state label formatting
│   └── utils.ts          # shadcn's cn() helper
├── types/
│   ├── api.ts            # hand-mirrored backend Pydantic models,
│   │                       # incl. ConversationUpdate
│   └── conversation.ts   # shared client-side UI state (fed by either hook)
└── pages/Dashboard.tsx    # mode toggle + assembles everything
```

## Running it

The backend (parent directory) must be running first:

```bash
# from the repo root
docker compose up --build
# or: uvicorn app.main:app --reload
```

Then, from this directory:

```bash
npm install
npm run dev
```

Open the printed URL (`http://localhost:5173/`, or the next free port if
that one's busy). It opens in **Live phone call** mode by default — dial the
configured Twilio number and watch the cards update as you speak, or switch
to **Test console** to drive a scripted conversation by typing replies.

In dev, Vite proxies `/api/*` to `http://localhost:8000` **including
WebSocket upgrades** (`ws: true` in `vite.config.ts`), so both the REST
endpoints and `/api/dashboard/stream` reach the backend with no CORS
configuration and no backend change. To point at a different backend (e.g. a
deployed instance), set `VITE_API_BASE_URL` in a `.env` file — the live-feed
hook derives the correct `ws://`/`wss://` URL from it automatically.

### Other scripts

```bash
npm run build     # tsc -b && vite build — production bundle in dist/
npm run preview   # serve the production build locally
npm run lint       # oxlint
```

## Notes on the `ui/` folder and lint

`src/components/ui/*.tsx` are shadcn/ui's generated primitives (Button, Card,
Select, Tabs, …) — not hand-written, and intentionally left as generated
rather than customized, so they stay easy to re-generate/update via
`npx shadcn@latest add <component>`. Their standard pattern of exporting a
`cva()` variants function alongside the component (e.g. `export { Button,
buttonVariants }`) trips the `react/only-export-components` Fast-Refresh
lint rule; that's expected in every shadcn project, so it's scoped off for
`components/ui/**` in `.oxlintrc.json` rather than restructuring vendored
files. Everything under `components/dashboard/`, `hooks/`, `lib/`, `types/`,
and `pages/` is hand-written and lints clean under the default rules.

## Known limitations

- **One call at a time**: Live mode renders the current/most-recent call from
  the backend's in-memory replay buffer — there's no per-call history or
  selection across multiple past calls yet.
- **No AI Summary on the live path**: the rule-based summary card is only
  populated by the test-console's `/conversation/test/*` responses today; the
  live snapshot doesn't carry one (see `docs/ARCHITECTURE.md` §9 in the parent
  repo).
- **Bundle size**: the production JS bundle is ~875 KB minified (Radix +
  Recharts + Framer Motion pull their own weight). Route-level code-splitting
  would trim this if this dashboard grew more pages — not done here since
  there's only one page.
- **Verified in a real browser**: this was checked with a clean TypeScript
  build, a clean production bundle, a clean lint run, and — critically — the
  actual React app opened in a real browser during a real, answered Twilio
  call, confirming the Live view updated card-by-card as the call progressed.
