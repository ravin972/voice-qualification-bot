import { AudioLines } from "lucide-react";
import { Badge } from "@/components/ui/badge";

export function Header() {
  return (
    <header className="border-b border-border/60 bg-card/50">
      <div className="mx-auto flex max-w-[1600px] items-center justify-between px-4 py-4 lg:px-8">
        <div className="flex items-center gap-3">
          <span className="flex size-9 items-center justify-center rounded-lg bg-primary/15 text-primary">
            <AudioLines className="size-5" />
          </span>
          <div>
            <h1 className="text-base font-semibold leading-tight text-foreground">
              Voice Qualification Dashboard
            </h1>
            <p className="text-xs text-muted-foreground">
              Live conversation analytics for the qualification engine
            </p>
          </div>
        </div>
        <Badge variant="outline" className="hidden sm:inline-flex">
          Live calls + test console
        </Badge>
      </div>
    </header>
  );
}
