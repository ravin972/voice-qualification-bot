import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

/**
 * Polls GET /health so the System Status card reflects the backend's real,
 * current state — not a one-time snapshot. No WebSocket exists for this
 * (the only WS endpoint is Twilio's media stream), so polling is the honest
 * mechanism here.
 */
export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    refetchInterval: 10_000,
    retry: 1,
  });
}
