import { LineChart as LineChartIcon } from "lucide-react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { SectionCard } from "@/components/dashboard/SectionCard";
import { formatDuration } from "@/lib/format";
import { useElapsedSeconds } from "@/hooks/useElapsedSeconds";
import type { LatencyHistoryPoint } from "@/types/conversation";

interface LatencyChartProps {
  history: LatencyHistoryPoint[];
  startedAt: string | null;
  ended: boolean;
}

export function LatencyChart({ history, startedAt, ended }: LatencyChartProps) {
  const elapsed = useElapsedSeconds(startedAt, ended);

  return (
    <SectionCard
      title="Latency Over Time"
      icon={LineChartIcon}
      action={
        <div className="flex items-center gap-4 text-xs text-muted-foreground">
          <span>
            Turns <span className="font-semibold text-foreground">{history.length}</span>
          </span>
          <span>
            Duration{" "}
            <span className="font-semibold text-foreground">
              {startedAt ? formatDuration(elapsed) : "—"}
            </span>
          </span>
        </div>
      }
    >
      {history.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground">
          Latency will appear here once the conversation has processed a turn.
        </p>
      ) : (
        <div className="h-56 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={history} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis
                dataKey="turn"
                tick={{ fill: "var(--muted-foreground)", fontSize: 11 }}
                tickLine={false}
                axisLine={{ stroke: "var(--border)" }}
                label={{ value: "Turn", position: "insideBottom", offset: -2, fontSize: 11, fill: "var(--muted-foreground)" }}
              />
              <YAxis
                tick={{ fill: "var(--muted-foreground)", fontSize: 11 }}
                tickLine={false}
                axisLine={{ stroke: "var(--border)" }}
                unit="ms"
                width={56}
              />
              <Tooltip
                contentStyle={{
                  background: "var(--popover)",
                  border: "1px solid var(--border)",
                  borderRadius: "0.5rem",
                  fontSize: "0.75rem",
                }}
                labelFormatter={(turn) => `Turn ${turn}`}
              />
              <Line
                type="monotone"
                dataKey="llm_ms"
                name="LLM"
                stroke="var(--primary)"
                strokeWidth={2}
                dot={{ r: 3 }}
                connectNulls
              />
              <Line
                type="monotone"
                dataKey="total_ms"
                name="Total"
                stroke="var(--success)"
                strokeWidth={2}
                dot={{ r: 3 }}
                connectNulls
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </SectionCard>
  );
}
