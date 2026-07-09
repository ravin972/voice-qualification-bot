import { useEffect, useRef, useState } from "react";
import { CallControls } from "@/components/dashboard/CallControls";
import { DashboardView } from "@/components/dashboard/DashboardView";
import { Header } from "@/components/dashboard/Header";
import { LiveStatusBar } from "@/components/dashboard/LiveStatusBar";
import { ModeToggle, type DashboardMode } from "@/components/dashboard/ModeToggle";
import { useConversationEngine } from "@/hooks/useConversationEngine";
import { useLiveCallFeed } from "@/hooks/useLiveCallFeed";

export function Dashboard() {
  const engine = useConversationEngine();
  const live = useLiveCallFeed();
  const [mode, setMode] = useState<DashboardMode>("live");

  // Pull focus to the live view the moment a real phone call connects, so an
  // incoming call takes over the dashboard even if you were on the test console.
  const wasActive = useRef(false);
  useEffect(() => {
    if (live.callActive && !wasActive.current) setMode("live");
    wasActive.current = live.callActive;
  }, [live.callActive]);

  return (
    <div className="min-h-screen bg-background">
      <Header />

      <main className="mx-auto flex max-w-[1600px] flex-col gap-4 px-4 py-6 lg:px-8">
        <div className="flex items-center justify-between">
          <ModeToggle mode={mode} onChange={setMode} liveActive={live.callActive} />
        </div>

        {mode === "live" ? (
          <>
            <LiveStatusBar
              connected={live.connected}
              callActive={live.callActive}
              callSid={live.state.conversationId}
            />
            <DashboardView ui={live.state} qualificationItems={live.qualificationItems} />
            <footer className="py-4 text-center text-xs text-muted-foreground">
              Streaming live from{" "}
              <code className="rounded bg-muted px-1 py-0.5">/dashboard/stream</code> — real
              phone-call snapshots emitted by ConversationService over the event bus.
            </footer>
          </>
        ) : (
          <>
            <CallControls
              ui={engine.state}
              isStarting={engine.isStarting}
              isSending={engine.isSending}
              error={engine.error}
              onStart={engine.start}
              onSend={engine.sendMessage}
            />
            <DashboardView
              ui={engine.state}
              qualificationItems={engine.qualificationItems}
              isBusy={engine.isStarting || engine.isSending}
            />
            <footer className="py-4 text-center text-xs text-muted-foreground">
              Driven live against{" "}
              <code className="rounded bg-muted px-1 py-0.5">POST /conversation/test/*</code> — the
              same state machine, LLM classifier, and qualification engine a real call would use.
            </footer>
          </>
        )}
      </main>
    </div>
  );
}
