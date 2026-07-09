/**
 * TypeScript mirror of the backend's Pydantic response/request models.
 *
 * Kept in exact lockstep with:
 *   - app/api/conversation_testing.py (ConversationTurnResponse and friends)
 *   - app/api/health.py (HealthResponse)
 *   - app/state_machine/states.py (State)
 *   - app/models/intent.py (Intent)
 *
 * There is no server-generated schema wired up (e.g. openapi-typescript) —
 * these are hand-mirrored. If the backend response shape changes, this file
 * must change with it.
 */

/** Conversation state-machine node. Mirrors app/state_machine/states.py::State. */
export type ConversationState =
  | "START"
  | "QUESTION_ONE"
  | "QUESTION_TWO"
  | "QUESTION_THREE"
  | "QUALIFIED"
  | "REJECTED"
  | "ENDED";

/** Normalised caller intent. Mirrors app/models/intent.py::Intent. */
export type Intent = "YES" | "NO" | "REPEAT" | "UNCLEAR";

/** One qualifying question in a scenario. Mirrors app/models/scenario.py::Question. */
export interface Question {
  key: string;
  prompt: string;
  disqualify_on_no: boolean;
}

/** The Python-decided verdict. Mirrors app/models/session.py::QualificationResult. */
export interface QualificationResult {
  qualified: boolean;
  label: string;
  reason: string;
}

/**
 * Real per-turn latency in milliseconds, sourced from the same measure()
 * calls that write to the backend's structured logs. Any field is null if
 * that stage didn't run this turn (text-mode never touches stt_ms/tts_ms).
 */
export interface TurnLatency {
  stt_ms: number | null;
  llm_ms: number | null;
  tts_ms: number | null;
  total_ms: number | null;
}

/**
 * Deterministic recap built from the real recorded answers and verdict — not
 * an LLM-generated narrative. See app/api/conversation_testing.py::_build_summary.
 */
export interface ConversationSummary {
  highlights: string[];
  verdict: string;
  qualified: boolean;
  recommendation: string;
}

/** Shared response shape for both /conversation/test/start and /message. */
export interface ConversationTurnResponse {
  conversation_id: string;
  scenario_id: string;
  state: ConversationState;
  messages: string[];
  ended: boolean;
  result: QualificationResult | null;
  latency_ms: TurnLatency | null;
  answers: Record<string, Intent>;
  questions: Question[];
  summary: ConversationSummary | null;
}

/** One utterance in a live call's running transcript. Mirrors app/models/events.py. */
export interface TranscriptLine {
  speaker: "bot" | "caller";
  message: string;
}

/** One qualification gate's live answer state. Mirrors app/models/events.py. */
export interface QualificationProgressItem {
  key: string;
  prompt: string;
  status: "pending" | "yes" | "no";
}

/**
 * A single immutable snapshot of a live phone call, pushed over
 * /dashboard/stream after every meaningful transition. Mirrors
 * app/models/events.py::ConversationUpdate — the one canonical event type.
 */
export interface ConversationUpdate {
  call_sid: string;
  timestamp: string;
  sequence: number;
  speaker: "bot" | "caller";
  message: string;
  conversation_state: ConversationState;
  qualification_progress: QualificationProgressItem[];
  final_result: QualificationResult | null;
  latency: TurnLatency | null;
  transcript_so_far: TranscriptLine[] | null;
}

export interface StartConversationRequest {
  scenario_id?: string;
}

export interface SubmitMessageRequest {
  conversation_id: string;
  text: string;
}

/** GET /health response. Mirrors app/api/health.py::HealthResponse. */
export interface HealthResponse {
  status: string;
  service: string;
  environment: string;
  scenarios: {
    ok: boolean;
    scenario_ids: string[];
    error: string | null;
  };
  vendor_config: {
    twilio: boolean;
    openai: boolean;
    deepgram: boolean;
    elevenlabs: boolean;
  };
}

/** Structured error body FastAPI returns for HTTPException (404 etc). */
export interface ApiErrorBody {
  detail: string;
}
