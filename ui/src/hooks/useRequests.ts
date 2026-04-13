import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "../lib/api";
import type { Request, RequestSummary, RequestStatus } from "../lib/types";

export function useRequestSummary() {
  return useQuery({
    queryKey: ["requests", "summary"],
    queryFn: () => apiGet<RequestSummary>("/requests/summary"),
    staleTime: 10_000,
    refetchInterval: 10_000,
  });
}

export function useRequests(status?: RequestStatus) {
  return useQuery({
    queryKey: ["requests", "list", status ?? "all"],
    queryFn: () =>
      apiGet<Request[]>("/requests", {
        params: status ? { status } : undefined,
      }),
    staleTime: 5_000,
    refetchInterval: 10_000,
  });
}

export function useAnswerRequest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, answer }: { id: string; answer: string }) =>
      apiPost<Request>(`/requests/${id}/answer`, { answer }, { auth: true }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["requests"] });
    },
  });
}

export function useRejectRequest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiPost<{ status: string }>(`/requests/${id}/reject`, undefined, {
        auth: true,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["requests"] });
    },
  });
}
