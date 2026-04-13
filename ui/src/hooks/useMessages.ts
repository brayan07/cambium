import { useQuery } from "@tanstack/react-query";
import { fetchAllMessages, type RawMessage } from "../lib/messages";

export type Message = RawMessage;

export function useMessages(sessionId: string | null) {
  return useQuery({
    queryKey: ["messages", sessionId],
    queryFn: () => fetchAllMessages(sessionId!),
    enabled: !!sessionId,
    staleTime: 30_000,
  });
}
