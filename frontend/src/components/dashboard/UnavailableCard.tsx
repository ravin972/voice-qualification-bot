import type { LucideIcon } from "lucide-react";
import { CircleSlash2 } from "lucide-react";
import { SectionCard } from "@/components/dashboard/SectionCard";

interface UnavailableCardProps {
  title: string;
  icon: LucideIcon;
  reason: string;
}

/**
 * Honest placeholder for a feature the backend genuinely doesn't support yet
 * (sentiment, per-intent confidence, call recording). No fake numbers, no
 * lorem ipsum — just a clear statement of what's missing and why.
 */
export function UnavailableCard({ title, icon, reason }: UnavailableCardProps) {
  return (
    <SectionCard title={title} icon={icon}>
      <div className="flex flex-col items-center justify-center gap-2 py-6 text-center">
        <CircleSlash2 className="size-6 text-muted-foreground" />
        <p className="text-sm font-medium text-muted-foreground">Unavailable</p>
        <p className="max-w-[22rem] text-xs text-muted-foreground/80">{reason}</p>
      </div>
    </SectionCard>
  );
}
