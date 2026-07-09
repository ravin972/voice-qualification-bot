import { CircleSlash2, FileText, MessageSquare, Music } from "lucide-react";
import { SectionCard } from "@/components/dashboard/SectionCard";
import { SummaryCard } from "@/components/dashboard/SummaryCard";
import { TranscriptChat } from "@/components/dashboard/TranscriptChat";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { ConversationSummary } from "@/types/api";
import type { TranscriptEntry } from "@/types/conversation";

interface BottomPanelProps {
  entries: TranscriptEntry[];
  summary: ConversationSummary | null;
  ended: boolean;
}

export function BottomPanel({ entries, summary, ended }: BottomPanelProps) {
  return (
    <SectionCard title="Call Detail" icon={MessageSquare} contentClassName="pt-2">
      <Tabs defaultValue="transcript">
        <TabsList>
          <TabsTrigger value="transcript" className="gap-1.5">
            <MessageSquare className="size-3.5" />
            Transcript
          </TabsTrigger>
          <TabsTrigger value="recording" className="gap-1.5">
            <Music className="size-3.5" />
            Audio Player
          </TabsTrigger>
          <TabsTrigger value="summary" className="gap-1.5">
            <FileText className="size-3.5" />
            AI Summary
          </TabsTrigger>
        </TabsList>

        <TabsContent value="transcript" className="pt-3">
          <TranscriptChat entries={entries} />
        </TabsContent>

        <TabsContent value="recording" className="pt-3">
          <div className="flex flex-col items-center justify-center gap-2 py-10 text-center">
            <CircleSlash2 className="size-6 text-muted-foreground" />
            <p className="text-sm font-medium text-muted-foreground">Recording unavailable</p>
            <p className="max-w-sm text-xs text-muted-foreground/80">
              The backend does not yet capture or store call recordings for this text-driven demo
              conversation. Nothing is faked here — this player only appears once a real
              recording URL is provided by the backend.
            </p>
          </div>
        </TabsContent>

        <TabsContent value="summary" className="border-none pt-3">
          <SummaryCard summary={summary} ended={ended} />
        </TabsContent>
      </Tabs>
    </SectionCard>
  );
}
