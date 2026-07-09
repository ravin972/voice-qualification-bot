import { PhoneCall, TerminalSquare } from "lucide-react";
import { cn } from "@/lib/utils";

export type DashboardMode = "live" | "test";

interface ModeToggleProps {
  mode: DashboardMode;
  onChange: (mode: DashboardMode) => void;
  liveActive: boolean;
}

const OPTIONS: { value: DashboardMode; label: string; icon: typeof PhoneCall }[] = [
  { value: "live", label: "Live phone call", icon: PhoneCall },
  { value: "test", label: "Test console", icon: TerminalSquare },
];

/** Segmented control switching the dashboard between the live feed and the text console. */
export function ModeToggle({ mode, onChange, liveActive }: ModeToggleProps) {
  return (
    <div className="inline-flex items-center gap-1 rounded-lg border border-border/60 bg-card/50 p-1">
      {OPTIONS.map(({ value, label, icon: Icon }) => {
        const selected = mode === value;
        return (
          <button
            key={value}
            type="button"
            onClick={() => onChange(value)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
              selected
                ? "bg-primary/15 text-primary"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Icon className="size-4" />
            {label}
            {value === "live" && liveActive ? (
              <span className="ml-0.5 size-2 rounded-full bg-success" />
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
