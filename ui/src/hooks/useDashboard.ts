import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import type { QueueStatus, ChannelEvent } from "../lib/types";

export function useQueueStatus() {
  return useQuery({
    queryKey: ["queue", "status"],
    queryFn: () => apiGet<QueueStatus>("/queue/status"),
    staleTime: 10_000,
    refetchInterval: 10_000,
  });
}

export function useRecentEvents(limit = 50) {
  return useQuery({
    queryKey: ["events", "recent", limit],
    queryFn: () =>
      apiGet<ChannelEvent[]>("/events", { params: { limit: String(limit) } }),
    staleTime: 10_000,
    refetchInterval: 15_000,
  });
}
