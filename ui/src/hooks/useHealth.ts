import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import type { HealthResponse } from "../lib/types";

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: () => apiGet<HealthResponse>("/health"),
    staleTime: 10_000,
    refetchInterval: 10_000,
  });
}
