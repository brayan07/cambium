import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "../lib/api";
import type {
  WorkItem,
  WorkItemStatus,
  ListWorkItemsResponse,
  WorkItemEvent,
} from "../lib/types";

/** Open tasks assigned to the user — powers the inbox "Tasks for you" section. */
export function useUserTasks() {
  return useQuery({
    queryKey: ["work-items", "user-tasks"],
    queryFn: async () => {
      const res = await apiGet<ListWorkItemsResponse>("/work-items", {
        params: { assigned_to: "user", limit: "100" },
      });
      // Keep only tasks that are actually waiting on the user — not completed/failed/canceled.
      return res.items.filter((i) =>
        ["pending", "ready", "active", "blocked"].includes(i.status),
      );
    },
    staleTime: 10_000,
    refetchInterval: 15_000,
  });
}

/** All work items (we fetch a generous slice and build the tree client-side). */
export function useWorkItems(limit = 500) {
  return useQuery({
    queryKey: ["work-items", "list", limit],
    queryFn: async () => {
      const res = await apiGet<ListWorkItemsResponse>("/work-items", {
        params: { limit: String(limit) },
      });
      return res;
    },
    staleTime: 10_000,
    refetchInterval: 15_000,
  });
}

export function useWorkItem(id: string | null) {
  return useQuery({
    queryKey: ["work-items", "detail", id],
    queryFn: () => apiGet<WorkItem>(`/work-items/${id}`),
    enabled: !!id,
    staleTime: 5_000,
    refetchInterval: 10_000,
  });
}

export function useWorkItemEvents(id: string | null) {
  return useQuery({
    queryKey: ["work-items", "events", id],
    queryFn: () =>
      apiGet<WorkItemEvent[]>(`/work-items/${id}/events`, {
        params: { limit: "100" },
      }),
    enabled: !!id,
    staleTime: 5_000,
    refetchInterval: 10_000,
  });
}

export function useBlockWorkItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) =>
      apiPost<WorkItem>(`/work-items/${id}/block`, { reason }, { auth: true }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["work-items"] }),
  });
}

export function useUnblockWorkItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiPost<WorkItem>(`/work-items/${id}/unblock`, undefined, { auth: true }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["work-items"] }),
  });
}

export function useCompleteWorkItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, result }: { id: string; result?: string }) =>
      apiPost<WorkItem>(
        `/work-items/${id}/complete`,
        { result: result ?? "" },
        { auth: true },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["work-items"] }),
  });
}

/** Node in the computed tree — children resolved from flat list. */
export interface WorkItemNode {
  item: WorkItem;
  children: WorkItemNode[];
  depth: number;
}

/**
 * Build a tree from a flat list of work items using parent_id pointers.
 * Orphans (parent not in list) are treated as roots.
 */
export function buildWorkItemTree(items: WorkItem[]): WorkItemNode[] {
  const byId = new Map<string, WorkItemNode>();
  for (const item of items) {
    byId.set(item.id, { item, children: [], depth: 0 });
  }
  const roots: WorkItemNode[] = [];
  for (const node of byId.values()) {
    const parentId = node.item.parent_id;
    if (parentId && byId.has(parentId)) {
      byId.get(parentId)!.children.push(node);
    } else {
      roots.push(node);
    }
  }

  // Assign depth and sort siblings by created_at desc.
  const assignDepth = (node: WorkItemNode, depth: number) => {
    node.depth = depth;
    node.children.sort((a, b) =>
      b.item.created_at.localeCompare(a.item.created_at),
    );
    for (const child of node.children) assignDepth(child, depth + 1);
  };
  roots.sort((a, b) =>
    b.item.created_at.localeCompare(a.item.created_at),
  );
  for (const root of roots) assignDepth(root, 0);
  return roots;
}

/** Filter a tree by status set — keeps ancestors of any matching node. */
export function filterTreeByStatus(
  roots: WorkItemNode[],
  allowed: Set<WorkItemStatus>,
): WorkItemNode[] {
  const filterNode = (node: WorkItemNode): WorkItemNode | null => {
    const kids = node.children
      .map(filterNode)
      .filter((c): c is WorkItemNode => c !== null);
    if (allowed.has(node.item.status) || kids.length > 0) {
      return { ...node, children: kids };
    }
    return null;
  };
  return roots
    .map(filterNode)
    .filter((n): n is WorkItemNode => n !== null);
}
