import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../lib/api";

export interface Message {
  id: string;
  role: string;
  content: string;
  created_at: string;
  sequence: number;
}

export function useMessages(sessionId: string | null) {
  return useQuery({
    queryKey: ["messages", sessionId],
    queryFn: () => apiGet<Message[]>(`/sessions/${sessionId}/messages`),
    enabled: !!sessionId,
    staleTime: 30_000,
  });
}
