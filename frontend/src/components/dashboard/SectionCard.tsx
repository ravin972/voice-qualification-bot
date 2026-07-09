import { motion } from "framer-motion";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface SectionCardProps {
  title: string;
  icon?: LucideIcon;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  contentClassName?: string;
}

/** Consistent card shell (title + icon + optional action) used across the dashboard. */
export function SectionCard({
  title,
  icon: Icon,
  action,
  children,
  className,
  contentClassName,
}: SectionCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      className={cn("flex min-h-0 flex-col", className)}
    >
      <Card className="flex min-h-0 flex-1 flex-col gap-0 rounded-xl py-0 shadow-none">
        <CardHeader className="flex flex-row items-center justify-between gap-2 border-b border-border/60 !py-3.5">
          <CardTitle className="flex items-center gap-2 text-sm font-medium text-foreground">
            {Icon ? <Icon className="size-4 text-muted-foreground" /> : null}
            {title}
          </CardTitle>
          {action}
        </CardHeader>
        <CardContent className={cn("flex-1 py-4", contentClassName)}>{children}</CardContent>
      </Card>
    </motion.div>
  );
}
