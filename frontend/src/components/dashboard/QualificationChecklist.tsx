import { motion } from "framer-motion";
import { Check, CircleDashed, ListChecks, X } from "lucide-react";
import { SectionCard } from "@/components/dashboard/SectionCard";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { QualificationResult } from "@/types/api";
import type { QualificationItem } from "@/types/conversation";

interface QualificationChecklistProps {
  items: QualificationItem[];
  result: QualificationResult | null;
}

export function QualificationChecklist({ items, result }: QualificationChecklistProps) {
  return (
    <SectionCard title="Qualification Progress" icon={ListChecks}>
      <div className="flex flex-col gap-2">
        {items.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            No scenario loaded yet.
          </p>
        ) : (
          items.map((item, index) => (
            <motion.div
              key={item.key}
              initial={{ opacity: 0, x: -6 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.2, delay: index * 0.03 }}
              className="flex items-center gap-3 rounded-lg border border-border/60 px-3 py-2.5"
            >
              <span
                className={cn(
                  "flex size-6 shrink-0 items-center justify-center rounded-full",
                  item.status === "yes" && "bg-success/15 text-success",
                  item.status === "no" && "bg-destructive/15 text-destructive",
                  item.status === "pending" && "bg-muted text-muted-foreground",
                )}
              >
                {item.status === "yes" ? (
                  <Check className="size-3.5" />
                ) : item.status === "no" ? (
                  <X className="size-3.5" />
                ) : (
                  <CircleDashed className="size-3.5" />
                )}
              </span>
              <span className="text-sm text-foreground">{item.prompt}</span>
            </motion.div>
          ))
        )}
      </div>

      <div className="mt-4 flex items-center justify-between rounded-lg bg-muted/50 px-3 py-3">
        <span className="text-sm font-medium text-muted-foreground">Current Decision</span>
        {result ? (
          <Badge
            variant={result.qualified ? "default" : "destructive"}
            className={cn(
              "px-2.5 py-1 text-xs font-semibold",
              result.qualified && "bg-success text-success-foreground",
            )}
          >
            {result.label}
          </Badge>
        ) : (
          <Badge variant="outline" className="text-muted-foreground">
            Pending
          </Badge>
        )}
      </div>
    </SectionCard>
  );
}
