import { useCallback, useMemo, useReducer } from "react";
import { useMutation } from "@tanstack/react-query";
import { ApiError, api } from "@/lib/api";
import type { ConversationTurnResponse } from "@/types/api";
import {
  EMPTY_CONVERSATION,
  type ConversationUiState,
  type QualificationItem,
  type TranscriptEntry,
} from "@/types/conversation";

type Action =
  | { type: "RESET" }
  | { type: "CUSTOMER_SPOKE"; text: string }
  | { type: "TURN_RECEIVED"; response: ConversationTurnResponse };

let entryCounter = 0;
function nextEntryId(): string {
  entryCounter += 1;
  return `entry_${entryCounter}`;
}

function reducer(state: ConversationUiState, action: Action): ConversationUiState {
  switch (action.type) {
    case "RESET":
      return EMPTY_CONVERSATION;

    case "CUSTOMER_SPOKE": {
      const entry: TranscriptEntry = {
        id: nextEntryId(),
        speaker: "customer",
        text: action.text,
        timestamp: new Date().toISOString(),
      };
      return { ...state, transcript: [...state.transcript, entry] };
    }

    case "TURN_RECEIVED": {
      const { response } = action;
      const botEntries: TranscriptEntry[] = response.messages.map((text) => ({
        id: nextEntryId(),
        speaker: "bot",
        text,
        timestamp: new Date().toISOString(),
      }));
      const latencyHistory = response.latency_ms
        ? [
            ...state.latencyHistory,
            {
              turn: state.latencyHistory.length + 1,
              llm_ms: response.latency_ms.llm_ms,
              total_ms: response.latency_ms.total_ms,
            },
          ]
        : state.latencyHistory;
      return {
        conversationId: response.conversation_id,
        scenarioId: response.scenario_id,
        state: response.state,
        transcript: [...state.transcript, ...botEntries],
        latest: response,
        result: response.result,
        latency: response.latency_ms,
        summary: response.summary,
        latencyHistory,
        startedAt: state.startedAt ?? new Date().toISOString(),
        ended: response.ended,
      };
    }

    default:
      return state;
  }
}

/**
 * Drives the "Test console" mode: a real conversation against the backend's
 * local test-mode endpoints (POST /conversation/test/start,
 * POST /conversation/test/message), accumulating transcript/qualification/
 * state entirely from those real responses. For a real phone call rendered
 * live as it happens, see `useLiveCallFeed` instead — this hook never touches
 * Twilio/Deepgram/audio at all, by design, so it can be exercised with no
 * phone call and no vendor account.
 */
export function useConversationEngine() {
  const [state, dispatch] = useReducer(reducer, EMPTY_CONVERSATION);

  const startMutation = useMutation({
    mutationFn: api.startConversation,
    onSuccess: (response) => {
      dispatch({ type: "TURN_RECEIVED", response });
    },
  });

  const messageMutation = useMutation({
    mutationFn: api.submitMessage,
    onSuccess: (response) => {
      dispatch({ type: "TURN_RECEIVED", response });
    },
  });

  const start = useCallback(
    (scenarioId?: string) => {
      dispatch({ type: "RESET" });
      startMutation.mutate({ scenario_id: scenarioId });
    },
    [startMutation],
  );

  const sendMessage = useCallback(
    (text: string) => {
      if (!state.conversationId || state.ended) return;
      dispatch({ type: "CUSTOMER_SPOKE", text });
      messageMutation.mutate({ conversation_id: state.conversationId, text });
    },
    [messageMutation, state.conversationId, state.ended],
  );

  const reset = useCallback(() => dispatch({ type: "RESET" }), []);

  const qualificationItems = useMemo<QualificationItem[]>(() => {
    const questions = state.latest?.questions ?? [];
    const answers = state.latest?.answers ?? {};
    return questions.map((question) => {
      const answer = answers[question.key];
      const status = answer === "YES" ? "yes" : answer === "NO" ? "no" : "pending";
      return { key: question.key, prompt: question.prompt, status };
    });
  }, [state.latest]);

  const error =
    startMutation.error instanceof ApiError
      ? startMutation.error.message
      : messageMutation.error instanceof ApiError
        ? messageMutation.error.message
        : null;

  return {
    state,
    qualificationItems,
    isStarting: startMutation.isPending,
    isSending: messageMutation.isPending,
    error,
    start,
    sendMessage,
    reset,
  };
}
