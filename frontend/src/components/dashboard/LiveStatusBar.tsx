import { PhoneCall } from "lucide-react";
import { SectionCard } from "@/components/dashboard/SectionCard";
import { cn } from "@/lib/utils";

interface LiveStatusBarProps {
  connected: boolean;
  callActive: boolean;
  callSid: string | null;
}

/** Live-mode status: WebSocket connection + whether a real call is in progress. */
export function LiveStatusBar({ connected, callActive, callSid }: LiveStatusBarProps) {
  const { dotClass, label, hint } = !connected
    ? {
        dotClass: "bg-destructive",
        label: "Reconnecting to live stream…",
        hint: "The dashboard stream socket is down — retrying automatically.",
      }
    : callActive
      ? {
          dotClass: "bg-success animate-pulse",
          label: "Live call in progress",
          hint: "Streaming snapshots from the phone call as it happens.",
        }
      : {
          dotClass: "bg-success",
          label: "Connected — waiting for a live call",
          hint: "Dial the Twilio number; this view updates the moment a call connects.",
        };

  return (
    <SectionCard title="Live Phone Call" icon={PhoneCall}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2.5">
          <span className={cn("size-2.5 rounded-full", dotClass)} />
          <div>
            <p className="text-sm font-medium text-foreground">{label}</p>
            <p className="text-xs text-muted-foreground">{hint}</p>
          </div>
        </div>
        {callSid ? (
          <span className="font-mono text-xs text-muted-foreground">{callSid}</span>
        ) : null}
      </div>
    </SectionCard>
  );
}
