import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../lib/api";

export type FsRoot = "memory" | "config";

export interface FsEntry {
  name: string;
  type: "dir" | "file";
  size: number | null;
  modified: number;
}

export interface FsListResponse {
  entries: FsEntry[];
}

export interface FsReadResponse {
  content: string;
  size: number;
  modified: number;
  extension: string;
}

/** List entries in a directory under the given root. */
export function useFsList(root: FsRoot, path: string, enabled = true) {
  return useQuery({
    queryKey: ["fs", "ls", root, path],
    queryFn: () =>
      apiGet<FsListResponse>("/fs/ls", { params: { root, path } }),
    enabled,
    staleTime: 10_000,
  });
}

/** Read the contents of a text file under the given root. */
export function useFsFile(root: FsRoot, path: string | null) {
  return useQuery({
    queryKey: ["fs", "read", root, path],
    queryFn: () =>
      apiGet<FsReadResponse>("/fs/read", {
        params: { root, path: path ?? "" },
      }),
    enabled: !!path,
    staleTime: 10_000,
  });
}
