import { Gauge } from "lucide-react";
import { SectionCard } from "@/components/dashboard/SectionCard";
import { formatMs } from "@/lib/format";
import type { TurnLatency } from "@/types/api";

interface LatencyCardProps {
  latency: TurnLatency | null;
}

const ROWS: { key: keyof TurnLatency; label: string }[] = [
  { key: "stt_ms", label: "STT" },
  { key: "llm_ms", label: "LLM" },
  { key: "tts_ms", label: "TTS" },
  { key: "total_ms", label: "Total" },
];

export function LatencyCard({ latency }: LatencyCardProps) {
  return (
    <SectionCard title="Latency" icon={Gauge}>
      {latency === null ? (
        <p className="py-6 text-center text-sm text-muted-foreground">
          No turn processed yet.
        </p>
      ) : (
        <div className="grid grid-cols-4 gap-2">
          {ROWS.map(({ key, label }) => (
            <div
              key={key}
              className="flex flex-col items-center gap-1 rounded-lg bg-muted/50 px-2 py-3"
            >
              <span className="text-[0.65rem] font-medium uppercase tracking-wide text-muted-foreground">
                {label}
              </span>
              <span
                className={
                  key === "total_ms"
                    ? "text-sm font-semibold text-primary"
                    : "text-sm font-semibold text-foreground"
                }
              >
                {formatMs(latency[key])}
              </span>
            </div>
          ))}
        </div>
      )}
      <p className="mt-3 text-[0.7rem] text-muted-foreground">
        Real per-turn measurements from the backend's <code>measure()</code> instrumentation —
        stt/tts are always unavailable in this text-driven demo, which never touches those ports.
      </p>
    </SectionCard>
  );
}
