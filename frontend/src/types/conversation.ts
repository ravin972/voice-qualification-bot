/**
 * Client-side conversation state.
 *
 * The backend has no "get past conversation" endpoint (its in-memory test
 * store discards a conversation once it ends), so this dashboard *drives* a
 * real conversation through /conversation/test/start + /message and builds
 * the transcript/timeline from the real requests it sent and the real
 * responses it received — nothing here is fabricated, it's just accumulated
 * client-side rather than replayed from a server-side history endpoint.
 */
import type {
  ConversationState,
  ConversationSummary,
  ConversationTurnResponse,
  QualificationResult,
  TurnLatency,
} from "@/types/api";

export type Speaker = "bot" | "customer";

/** One line in the transcript/timeline — either something the bot said or the customer typed. */
export interface TranscriptEntry {
  id: string;
  speaker: Speaker;
  text: string;
  timestamp: string; // ISO string, captured client-side when the line arrived
}

/** Which of the scenario's questions has been answered, and how. */
export interface QualificationItem {
  key: string;
  prompt: string;
  status: "pending" | "yes" | "no";
}

/** One turn's real latency, kept for the latency-over-time chart. */
export interface LatencyHistoryPoint {
  turn: number;
  llm_ms: number | null;
  total_ms: number | null;
}

/**
 * Everything the dashboard knows about the conversation currently in progress.
 *
 * `result`/`latency`/`summary` are hoisted to the top level (rather than read
 * off `latest`) so both data sources — the text-mode engine and the live
 * phone-call feed — populate the same shape and every card renders unchanged.
 * `latest` remains for the text-mode engine's own bookkeeping and is `null`
 * for live calls (a live snapshot is not a `ConversationTurnResponse`).
 */
export interface ConversationUiState {
  conversationId: string | null;
  scenarioId: string | null;
  state: ConversationState | null;
  transcript: TranscriptEntry[];
  latest: ConversationTurnResponse | null;
  result: QualificationResult | null;
  latency: TurnLatency | null;
  summary: ConversationSummary | null;
  latencyHistory: LatencyHistoryPoint[];
  startedAt: string | null;
  ended: boolean;
}

export const EMPTY_CONVERSATION: ConversationUiState = {
  conversationId: null,
  scenarioId: null,
  state: null,
  transcript: [],
  latest: null,
  result: null,
  latency: null,
  summary: null,
  latencyHistory: [],
  startedAt: null,
  ended: false,
};
