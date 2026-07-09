import { AnimatePresence, motion } from "framer-motion";
import { History } from "lucide-react";
import { SectionCard } from "@/components/dashboard/SectionCard";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { formatTime } from "@/lib/format";
import type { TranscriptEntry } from "@/types/conversation";

interface ConversationTimelineProps {
  entries: TranscriptEntry[];
}

export function ConversationTimeline({ entries }: ConversationTimelineProps) {
  return (
    <SectionCard title="Conversation Timeline" icon={History} className="h-full" contentClassName="p-0">
      <ScrollArea className="h-[420px]">
        <div className="flex flex-col gap-1 px-4 py-3">
          {entries.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              Start a call to see the timeline.
            </p>
          ) : (
            <AnimatePresence initial={false}>
              {entries.map((entry) => (
                <motion.div
                  key={entry.id}
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.2 }}
                  className="grid grid-cols-[5.5rem_5rem_1fr] items-start gap-2 border-b border-border/40 py-2 text-sm last:border-b-0"
                >
                  <span className="font-mono text-xs text-muted-foreground">
                    {formatTime(entry.timestamp)}
                  </span>
                  <Badge
                    variant={entry.speaker === "bot" ? "default" : "secondary"}
                    className="w-fit uppercase"
                  >
                    {entry.speaker}
                  </Badge>
                  <span className="text-foreground">{entry.text}</span>
                </motion.div>
              ))}
            </AnimatePresence>
          )}
        </div>
      </ScrollArea>
    </SectionCard>
  );
}
