import { Percent } from "lucide-react";
import { BottomPanel } from "@/components/dashboard/BottomPanel";
import { ConversationTimeline } from "@/components/dashboard/ConversationTimeline";
import { LatencyCard } from "@/components/dashboard/LatencyCard";
import { LatencyChart } from "@/components/dashboard/LatencyChart";
import { MetricsBar } from "@/components/dashboard/MetricsBar";
import { QualificationChecklist } from "@/components/dashboard/QualificationChecklist";
import { StateMachineDiagram } from "@/components/dashboard/StateMachineDiagram";
import { SystemStatusCard } from "@/components/dashboard/SystemStatusCard";
import { UnavailableCard } from "@/components/dashboard/UnavailableCard";
import type { ConversationUiState, QualificationItem } from "@/types/conversation";

interface DashboardViewProps {
  ui: ConversationUiState;
  qualificationItems: QualificationItem[];
  isBusy?: boolean;
}

/**
 * The shared visualization grid, rendered identically for a text-mode
 * conversation and a live phone call — both supply the same
 * `ConversationUiState`, so nothing here knows or cares which source it is.
 */
export function DashboardView({ ui, qualificationItems, isBusy = false }: DashboardViewProps) {
  return (
    <>
      <MetricsBar ui={ui} isBusy={isBusy} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        <div className="lg:col-span-5">
          <ConversationTimeline entries={ui.transcript} />
        </div>
        <div className="flex flex-col gap-4 lg:col-span-7">
          <QualificationChecklist items={qualificationItems} result={ui.result} />
          <StateMachineDiagram current={ui.state} />
        </div>
      </div>

      <BottomPanel entries={ui.transcript} summary={ui.summary} ended={ui.ended} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <LatencyCard latency={ui.latency} />
        <UnavailableCard
          title="Confidence"
          icon={Percent}
          reason="The intent classifier returns a single label (YES/NO/REPEAT/UNCLEAR), not a probability — there's no confidence score to show without changing the classifier's output contract."
        />
        <SystemStatusCard />
      </div>

      <LatencyChart history={ui.latencyHistory} startedAt={ui.startedAt} ended={ui.ended} />
    </>
  );
}
