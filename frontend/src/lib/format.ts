/** Formats an elapsed duration (seconds) as `mm:ss`. */
export function formatDuration(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = Math.floor(totalSeconds % 60);
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

/** Formats a latency value in milliseconds, or a placeholder if unavailable. */
export function formatMs(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (value < 1) return "<1 ms";
  return `${Math.round(value)} ms`;
}

/** Human label for a state-machine node, e.g. QUESTION_ONE -> "Question 1". */
export function formatStateLabel(state: string | null): string {
  if (!state) return "Idle";
  const map: Record<string, string> = {
    START: "Start",
    QUESTION_ONE: "Question 1",
    QUESTION_TWO: "Question 2",
    QUESTION_THREE: "Question 3",
    QUALIFIED: "Qualified",
    REJECTED: "Rejected",
    ENDED: "Ended",
  };
  return map[state] ?? state;
}

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}
