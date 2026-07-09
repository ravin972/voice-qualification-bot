import { motion } from "framer-motion";
import { ArrowRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { ConversationSummary } from "@/types/api";

interface SummaryCardProps {
  summary: ConversationSummary | null;
  ended: boolean;
}

/** AI Summary tab content (no card chrome of its own — hosted inside BottomPanel's Tabs). */
export function SummaryCard({ summary, ended }: SummaryCardProps) {
  if (!summary) {
    return (
      <p className="py-10 text-center text-sm text-muted-foreground">
        {ended
          ? "No summary available for this conversation."
          : "Available once the conversation ends."}
      </p>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className="flex flex-col gap-3"
    >
      <div className="flex items-center gap-2">
        <Badge
          variant={summary.qualified ? "default" : "destructive"}
          className={cn(summary.qualified && "bg-success text-success-foreground")}
        >
          {summary.verdict}
        </Badge>
        <p className="text-xs text-muted-foreground">
          Generated from the conversation's real recorded answers
        </p>
      </div>

      <ul className="flex flex-col gap-1.5 text-sm text-foreground">
        {summary.highlights.map((line) => (
          <li key={line} className="flex items-start gap-2">
            <span className="mt-1.5 size-1 shrink-0 rounded-full bg-muted-foreground" />
            {line}
          </li>
        ))}
      </ul>

      <div className="flex items-center gap-2 rounded-lg bg-muted/50 px-3 py-2.5 text-sm">
        <ArrowRight className="size-4 shrink-0 text-primary" />
        <span className="font-medium text-foreground">{summary.recommendation}</span>
      </div>
    </motion.div>
  );
}
