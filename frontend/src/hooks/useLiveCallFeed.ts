import { useEffect, useMemo, useReducer, useRef, useState } from "react";
import type { ConversationUpdate, QualificationProgressItem } from "@/types/api";
import {
  EMPTY_CONVERSATION,
  type ConversationUiState,
  type QualificationItem,
  type TranscriptEntry,
} from "@/types/conversation";

/**
 * Derive the `/dashboard/stream` WebSocket URL.
 *
 * In dev, Vite proxies `/api/*` (with `ws: true`) to the backend, so we connect
 * to `/api/dashboard/stream` on the current origin. If `VITE_API_BASE_URL`
 * points at a deployed backend, the socket is derived from that instead.
 */
function streamUrl(): string {
  const base = import.meta.env.VITE_API_BASE_URL as string | undefined;
  if (base) {
    const url = new URL(base, window.location.origin);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    return `${url.origin}${url.pathname.replace(/\/$/, "")}/dashboard/stream`;
  }
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/api/dashboard/stream`;
}

const RECONNECT_DELAY_MS = 2000;

interface LiveState {
  ui: ConversationUiState;
  progress: QualificationProgressItem[];
}

const EMPTY_LIVE: LiveState = { ui: EMPTY_CONVERSATION, progress: [] };

/**
 * Fold one snapshot into the accumulated UI state.
 *
 * Each snapshot is self-contained (it carries the whole `transcript_so_far` and
 * current progress/result/latency), so this reconciles rather than assuming a
 * strict +1 delta: if any snapshots were dropped under load, the transcript
 * still catches up from `transcript_so_far`.
 */
function reduce(prev: LiveState, update: ConversationUpdate): LiveState {
  const isNewCall = prev.ui.conversationId !== update.call_sid;
  const base = isNewCall ? EMPTY_LIVE : prev;

  const soFar = update.transcript_so_far ?? [];
  const existing = base.ui.transcript;
  const transcript: TranscriptEntry[] =
    soFar.length > existing.length
      ? [
          ...existing,
          ...soFar.slice(existing.length).map((line, offset) => ({
            id: `${update.call_sid}-${existing.length + offset}`,
            speaker: line.speaker === "bot" ? ("bot" as const) : ("customer" as const),
            text: line.message,
            timestamp: update.timestamp,
          })),
        ]
      : existing;

  const lastTotal = base.ui.latencyHistory.at(-1)?.total_ms ?? null;
  const total = update.latency?.total_ms ?? null;
  const latencyHistory =
    total !== null && total !== lastTotal
      ? [
          ...base.ui.latencyHistory,
          {
            turn: base.ui.latencyHistory.length + 1,
            llm_ms: update.latency?.llm_ms ?? null,
            total_ms: total,
          },
        ]
      : base.ui.latencyHistory;

  return {
    progress: update.qualification_progress,
    ui: {
      conversationId: update.call_sid,
      scenarioId: null, // not carried on the snapshot; the call SID identifies the call
      state: update.conversation_state,
      transcript,
      latest: null, // a live snapshot is not a ConversationTurnResponse
      result: update.final_result,
      latency: update.latency,
      summary: null, // no rule-based summary on the live path
      latencyHistory,
      startedAt: base.ui.startedAt ?? update.timestamp,
      ended: update.conversation_state === "ENDED",
    },
  };
}

/**
 * Subscribes to the backend's `/dashboard/stream` WebSocket and folds the live
 * `ConversationUpdate` snapshots into the same `ConversationUiState` the
 * text-mode engine produces, so every existing dashboard card renders a real
 * phone call as it happens. Reconnects automatically if the socket drops.
 */
export function useLiveCallFeed() {
  const [{ ui, progress }, dispatch] = useReducer(reduce, EMPTY_LIVE);
  const [connected, setConnected] = useState(false);
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let disposed = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      if (disposed) return;
      const socket = new WebSocket(streamUrl());
      socketRef.current = socket;

      socket.onopen = () => {
        if (!disposed) setConnected(true);
      };
      socket.onmessage = (event) => {
        if (disposed) return;
        try {
          dispatch(JSON.parse(event.data as string) as ConversationUpdate);
        } catch {
          // Ignore a malformed frame rather than tearing down the stream.
        }
      };
      socket.onclose = () => {
        if (disposed) return;
        setConnected(false);
        reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS);
      };
      socket.onerror = () => socket.close();
    };

    connect();

    return () => {
      disposed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      socketRef.current?.close();
    };
  }, []);

  const qualificationItems = useMemo<QualificationItem[]>(
    () =>
      progress.map((item) => ({ key: item.key, prompt: item.prompt, status: item.status })),
    [progress],
  );

  const callActive = ui.conversationId !== null && !ui.ended;

  return { state: ui, qualificationItems, connected, callActive };
}
