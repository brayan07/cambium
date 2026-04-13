import { apiGet } from "./api";

export interface RawMessage {
  id: string;
  role: string;
  content: string;
  created_at: string;
  sequence: number;
}

const PAGE_SIZE = 500;

/**
 * Fetch all messages for a session, paging through the server's
 * sequence-based pagination until exhausted.
 *
 * The server's default `limit` is 100, which silently truncates longer
 * sessions if the client doesn't page. See cambium#28.
 */
export async function fetchAllMessages(
  sessionId: string,
): Promise<RawMessage[]> {
  const all: RawMessage[] = [];
  let after = -1;
  while (true) {
    const page = await apiGet<RawMessage[]>(
      `/sessions/${sessionId}/messages?after=${after}&limit=${PAGE_SIZE}`,
    );
    if (page.length === 0) break;
    all.push(...page);
    if (page.length < PAGE_SIZE) break;
    after = page[page.length - 1].sequence;
  }
  return all;
}
