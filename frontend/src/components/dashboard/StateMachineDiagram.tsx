import { motion } from "framer-motion";
import { GitBranch } from "lucide-react";
import { Fragment } from "react";
import { SectionCard } from "@/components/dashboard/SectionCard";
import { cn } from "@/lib/utils";
import type { ConversationState } from "@/types/api";

interface StateMachineDiagramProps {
  current: ConversationState | null;
}

const HAPPY_PATH: ConversationState[] = [
  "START",
  "QUESTION_ONE",
  "QUESTION_TWO",
  "QUESTION_THREE",
  "QUALIFIED",
];

const LABELS: Record<ConversationState, string> = {
  START: "Start",
  QUESTION_ONE: "Question 1",
  QUESTION_TWO: "Question 2",
  QUESTION_THREE: "Question 3",
  QUALIFIED: "Qualified",
  REJECTED: "Rejected",
  ENDED: "Ended",
};

export function StateMachineDiagram({ current }: StateMachineDiagramProps) {
  // REJECTED can be reached from any question node — show it as the branch
  // it actually is rather than pretending the flow is strictly linear.
  const showRejectedBranch = current === "REJECTED";
  const nodes = showRejectedBranch
    ? (["START", "QUESTION_ONE", "QUESTION_TWO", "QUESTION_THREE", "REJECTED"] as ConversationState[])
    : HAPPY_PATH;

  return (
    <SectionCard title="Conversation State" icon={GitBranch}>
      <div className="flex flex-col">
        {nodes.map((node, index) => {
          const isActive = node === current;
          const isPast = current !== null && nodes.indexOf(current) > index && current !== "ENDED";
          const isEndedAndTerminal =
            current === "ENDED" && (node === "QUALIFIED" || node === "REJECTED");
          return (
            <Fragment key={node}>
              <motion.div
                animate={isActive ? { scale: [1, 1.03, 1] } : {}}
                transition={{ duration: 0.6, repeat: isActive ? Infinity : 0 }}
                className={cn(
                  "flex items-center gap-3 rounded-lg border px-3 py-2 text-sm transition-colors",
                  isActive || isEndedAndTerminal
                    ? node === "REJECTED"
                      ? "border-destructive/40 bg-destructive/10 text-destructive"
                      : node === "QUALIFIED"
                        ? "border-success/40 bg-success/10 text-success"
                        : "border-primary/40 bg-primary/10 text-primary"
                    : isPast
                      ? "border-border/40 text-muted-foreground"
                      : "border-border/40 text-muted-foreground/60",
                )}
              >
                <span
                  className={cn(
                    "size-2 shrink-0 rounded-full",
                    isActive || isEndedAndTerminal
                      ? node === "REJECTED"
                        ? "bg-destructive"
                        : node === "QUALIFIED"
                          ? "bg-success"
                          : "bg-primary"
                      : "bg-current opacity-40",
                  )}
                />
                <span className="font-medium">{LABELS[node]}</span>
                {isActive ? (
                  <span className="ml-auto text-[0.65rem] uppercase tracking-wide opacity-80">
                    active
                  </span>
                ) : null}
              </motion.div>
              {index < nodes.length - 1 ? (
                <div className="ml-[0.8rem] h-3 w-px bg-border" />
              ) : null}
            </Fragment>
          );
        })}
      </div>
    </SectionCard>
  );
}
