import { useState } from "react";
import { AlertCircle, Phone, Send } from "lucide-react";
import { SectionCard } from "@/components/dashboard/SectionCard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useHealth } from "@/hooks/useHealth";
import type { ConversationUiState } from "@/types/conversation";

interface CallControlsProps {
  ui: ConversationUiState;
  isStarting: boolean;
  isSending: boolean;
  error: string | null;
  onStart: (scenarioId?: string) => void;
  onSend: (text: string) => void;
}

const QUICK_REPLIES = ["Yes", "No", "Repeat"];

export function CallControls({
  ui,
  isStarting,
  isSending,
  error,
  onStart,
  onSend,
}: CallControlsProps) {
  const { data: health } = useHealth();
  const scenarios = health?.scenarios.scenario_ids ?? [];
  const [scenarioId, setScenarioId] = useState<string>("");
  const [draft, setDraft] = useState("");

  const canSend = Boolean(ui.conversationId) && !ui.ended && !isSending;

  const handleSend = (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || !canSend) return;
    onSend(trimmed);
    setDraft("");
  };

  return (
    <SectionCard title="Call Controls" icon={Phone}>
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Select value={scenarioId} onValueChange={setScenarioId}>
            <SelectTrigger className="min-w-48">
              <SelectValue placeholder="Default scenario" />
            </SelectTrigger>
            <SelectContent>
              {scenarios.map((id) => (
                <SelectItem key={id} value={id}>
                  {id}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            onClick={() => onStart(scenarioId || undefined)}
            disabled={isStarting}
            className="gap-1.5"
          >
            <Phone className="size-4" />
            {ui.conversationId && !ui.ended ? "Restart Call" : "Start Call"}
          </Button>
          {ui.conversationId ? (
            <span className="font-mono text-xs text-muted-foreground">{ui.conversationId}</span>
          ) : null}
        </div>

        <form
          onSubmit={(event) => {
            event.preventDefault();
            handleSend(draft);
          }}
          className="flex items-center gap-2"
        >
          <Input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder={
              canSend ? "Type the caller's reply…" : "Start a call to send a message"
            }
            disabled={!canSend}
          />
          <Button type="submit" size="icon" variant="secondary" disabled={!canSend || !draft.trim()}>
            <Send className="size-4" />
          </Button>
        </form>

        <div className="flex flex-wrap gap-1.5">
          {QUICK_REPLIES.map((label) => (
            <Button
              key={label}
              type="button"
              size="sm"
              variant="outline"
              disabled={!canSend}
              onClick={() => handleSend(label)}
            >
              {label}
            </Button>
          ))}
        </div>

        {error ? (
          <div className="flex items-center gap-2 rounded-lg bg-destructive/10 px-3 py-2 text-xs text-destructive">
            <AlertCircle className="size-4 shrink-0" />
            {error}
          </div>
        ) : null}
      </div>
    </SectionCard>
  );
}
