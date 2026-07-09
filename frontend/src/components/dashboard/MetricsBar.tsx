import { Activity, Clock, Gauge, Mic, PhoneCall, Smile } from "lucide-react";
import { MetricTile } from "@/components/dashboard/MetricTile";
import { formatDuration, formatMs, formatStateLabel } from "@/lib/format";
import { useElapsedSeconds } from "@/hooks/useElapsedSeconds";
import type { ConversationUiState } from "@/types/conversation";

interface MetricsBarProps {
  ui: ConversationUiState;
  isBusy: boolean;
}

export function MetricsBar({ ui, isBusy }: MetricsBarProps) {
  const elapsed = useElapsedSeconds(ui.startedAt, ui.ended);
  const active = Boolean(ui.conversationId) && !ui.ended;

  const speaker = isBusy
    ? "Bot"
    : ui.ended
      ? "—"
      : ui.transcript.at(-1)?.speaker === "bot"
        ? "Customer"
        : ui.conversationId
          ? "Bot"
          : "—";

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      <MetricTile
        label="Active Calls"
        value={active ? "1" : "0"}
        icon={PhoneCall}
        tone={active ? "success" : "muted"}
        pulse={active}
      />
      <MetricTile
        label="Conversation State"
        value={formatStateLabel(ui.state)}
        icon={Activity}
        tone={ui.state === "QUALIFIED" ? "success" : ui.state === "REJECTED" ? "destructive" : "default"}
      />
      <MetricTile
        label="Call Duration"
        value={ui.conversationId ? formatDuration(elapsed) : "—"}
        icon={Clock}
      />
      <MetricTile label="Sentiment" value="Unavailable" icon={Smile} tone="muted" hint="No backend signal" />
      <MetricTile label="Current Speaker" value={speaker} icon={Mic} tone={isBusy ? "warning" : "default"} />
      <MetricTile
        label="Latency (total)"
        value={formatMs(ui.latency?.total_ms)}
        icon={Gauge}
      />
    </div>
  );
}
