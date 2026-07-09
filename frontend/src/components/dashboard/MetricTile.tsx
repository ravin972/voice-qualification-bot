import { motion } from "framer-motion";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

interface MetricTileProps {
  label: string;
  value: string;
  icon: LucideIcon;
  hint?: string;
  tone?: "default" | "success" | "destructive" | "warning" | "muted";
  pulse?: boolean;
}

const toneClasses: Record<NonNullable<MetricTileProps["tone"]>, string> = {
  default: "text-foreground",
  success: "text-success",
  destructive: "text-destructive",
  warning: "text-warning",
  muted: "text-muted-foreground",
};

/** One tile in the top metrics bar (Active Calls, State, Duration, Speaker, Latency, Sentiment). */
export function MetricTile({
  label,
  value,
  icon: Icon,
  hint,
  tone = "default",
  pulse = false,
}: MetricTileProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      className="flex items-center gap-3 rounded-xl bg-card px-4 py-3 ring-1 ring-foreground/10"
    >
      <div className="relative flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted">
        <Icon className={cn("size-4", toneClasses[tone])} />
        {pulse ? (
          <span className="absolute -right-0.5 -top-0.5 flex size-2.5">
            <span className="absolute inline-flex size-full animate-ping rounded-full bg-success opacity-75" />
            <span className="relative inline-flex size-2.5 rounded-full bg-success" />
          </span>
        ) : null}
      </div>
      <div className="min-w-0">
        <p className="truncate text-[0.7rem] font-medium uppercase tracking-wide text-muted-foreground">
          {label}
        </p>
        <p className={cn("truncate text-sm font-semibold leading-tight", toneClasses[tone])}>
          {value}
        </p>
        {hint ? <p className="truncate text-[0.7rem] text-muted-foreground">{hint}</p> : null}
      </div>
    </motion.div>
  );
}
