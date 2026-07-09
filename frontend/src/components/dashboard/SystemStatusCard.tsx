import { AlertTriangle, Radio } from "lucide-react";
import { SectionCard } from "@/components/dashboard/SectionCard";
import { cn } from "@/lib/utils";
import { useHealth } from "@/hooks/useHealth";

interface StatusRowProps {
  label: string;
  ok: boolean | undefined;
  detail?: string;
}

function StatusRow({ label, ok, detail }: StatusRowProps) {
  return (
    <div className="flex items-center justify-between py-1.5">
      <span className="text-sm text-foreground">{label}</span>
      <span className="flex items-center gap-2">
        {detail ? <span className="text-xs text-muted-foreground">{detail}</span> : null}
        <span
          className={cn(
            "size-2.5 rounded-full",
            ok === undefined ? "bg-muted-foreground/40" : ok ? "bg-success" : "bg-destructive",
          )}
        />
      </span>
    </div>
  );
}

export function SystemStatusCard() {
  const { data, isError, isLoading } = useHealth();

  return (
    <SectionCard title="System Status" icon={Radio}>
      {isLoading ? (
        <p className="py-6 text-center text-sm text-muted-foreground">Checking…</p>
      ) : isError || !data ? (
        <div className="flex flex-col items-center gap-2 py-6 text-center">
          <AlertTriangle className="size-5 text-destructive" />
          <p className="text-sm font-medium text-destructive">Backend unreachable</p>
          <p className="text-xs text-muted-foreground">
            GET /health failed — is the API server running?
          </p>
        </div>
      ) : (
        <div className="flex flex-col divide-y divide-border/60">
          <StatusRow label="Backend API" ok={data.status === "ok"} />
          <StatusRow
            label="Scenario Loader"
            ok={data.scenarios.ok}
            detail={`${data.scenarios.scenario_ids.length} loaded`}
          />
          <StatusRow label="OpenAI" ok={data.vendor_config.openai} />
          <StatusRow label="Twilio" ok={data.vendor_config.twilio} />
          <StatusRow label="Deepgram" ok={data.vendor_config.deepgram} />
          <StatusRow label="ElevenLabs" ok={data.vendor_config.elevenlabs} />
        </div>
      )}
    </SectionCard>
  );
}
