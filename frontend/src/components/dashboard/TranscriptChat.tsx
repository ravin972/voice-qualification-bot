import { AnimatePresence, motion } from "framer-motion";
import { Bot, User } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import { formatTime } from "@/lib/format";
import type { TranscriptEntry } from "@/types/conversation";

interface TranscriptChatProps {
  entries: TranscriptEntry[];
}

export function TranscriptChat({ entries }: TranscriptChatProps) {
  if (entries.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        No messages yet — start a call to begin the conversation.
      </p>
    );
  }

  return (
    <ScrollArea className="h-[320px]">
      <div className="flex flex-col gap-3 pr-3">
        <AnimatePresence initial={false}>
          {entries.map((entry) => {
            const isBot = entry.speaker === "bot";
            return (
              <motion.div
                key={entry.id}
                initial={{ opacity: 0, y: 6, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                transition={{ duration: 0.2 }}
                className={cn("flex items-end gap-2", isBot ? "justify-start" : "justify-end")}
              >
                {isBot ? (
                  <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/15 text-primary">
                    <Bot className="size-4" />
                  </span>
                ) : null}
                <div
                  className={cn(
                    "max-w-[75%] rounded-2xl px-3.5 py-2 text-sm",
                    isBot
                      ? "rounded-bl-sm bg-muted text-foreground"
                      : "rounded-br-sm bg-primary text-primary-foreground",
                  )}
                >
                  <p>{entry.text}</p>
                  <p
                    className={cn(
                      "mt-1 text-[0.65rem] opacity-60",
                      isBot ? "text-muted-foreground" : "text-primary-foreground",
                    )}
                  >
                    {formatTime(entry.timestamp)}
                  </p>
                </div>
                {!isBot ? (
                  <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-secondary text-secondary-foreground">
                    <User className="size-4" />
                  </span>
                ) : null}
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </ScrollArea>
  );
}
