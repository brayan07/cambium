import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import type { RequestSummary } from "../lib/types";

export function useRequestSummary() {
  return useQuery({
    queryKey: ["requests", "summary"],
    queryFn: () => apiGet<RequestSummary>("/requests/summary"),
    staleTime: 10_000,
    refetchInterval: 10_000,
  });
}
