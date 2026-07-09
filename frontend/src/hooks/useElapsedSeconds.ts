import { useEffect, useState } from "react";

/** Ticks once a second, returning seconds elapsed since `startedAt` (or 0 if null/frozen once ended). */
export function useElapsedSeconds(startedAt: string | null, frozen: boolean): number {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!startedAt) {
      setElapsed(0);
      return;
    }
    const start = new Date(startedAt).getTime();
    const tick = () => setElapsed((Date.now() - start) / 1000);
    tick();
    if (frozen) return;
    const interval = window.setInterval(tick, 1000);
    return () => window.clearInterval(interval);
  }, [startedAt, frozen]);

  return elapsed;
}
