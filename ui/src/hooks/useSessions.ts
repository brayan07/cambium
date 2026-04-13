import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import type { Session } from "../lib/types";

interface SessionFilters {
  status?: string;
  origin?: string;
  limit?: number;
}

export function useSessions(filters?: SessionFilters) {
  const params: Record<string, string> = {};
  if (filters?.status) params.status = filters.status;
  if (filters?.origin) params.origin = filters.origin;
  if (filters?.limit) params.limit = String(filters.limit);

  return useQuery({
    queryKey: ["sessions", filters],
    queryFn: () => apiGet<Session[]>("/sessions", { params }),
    staleTime: 5_000,
    refetchInterval: 5_000,
  });
}

export function useSession(id: string | null) {
  return useQuery({
    queryKey: ["session", id],
    queryFn: () => apiGet<Session>(`/sessions/${id}`),
    enabled: !!id,
    staleTime: 5_000,
  });
}
