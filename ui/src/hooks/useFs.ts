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

export interface FsInfoResponse {
  root: FsRoot;
  path: string;
  exists: boolean;
  remote_url: string | null;
}

/** Metadata about a root: absolute path and optional git remote URL. */
export function useFsInfo(root: FsRoot) {
  return useQuery({
    queryKey: ["fs", "info", root],
    queryFn: () => apiGet<FsInfoResponse>("/fs/info", { params: { root } }),
    staleTime: 60_000,
  });
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
