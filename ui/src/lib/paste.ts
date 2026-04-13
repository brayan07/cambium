/** Threshold for collapsing pasted text (lines). */
export const COLLAPSE_LINE_THRESHOLD = 15;
/** Threshold for collapsing pasted text (characters). */
export const COLLAPSE_CHAR_THRESHOLD = 800;

export interface CollapsedPaste {
  fullText: string;
  lineCount: number;
  preview: string;
  expanded: boolean;
  /** Cursor position in the textarea when the paste occurred. */
  cursorPos: number;
}

/**
 * Determine whether a pasted text should be collapsed.
 * Returns a CollapsedPaste if it exceeds thresholds, or null if it should
 * be inserted inline (default textarea behavior).
 */
export function detectCollapsiblePaste(
  text: string,
  cursorPos: number,
): CollapsedPaste | null {
  const lines = text.split("\n");
  if (
    lines.length <= COLLAPSE_LINE_THRESHOLD &&
    text.length <= COLLAPSE_CHAR_THRESHOLD
  ) {
    return null;
  }
  return {
    fullText: text,
    lineCount: lines.length,
    preview: lines.slice(0, 4).join("\n"),
    expanded: false,
    cursorPos,
  };
}

/**
 * Assemble the final message text from the textarea input and an optional
 * collapsed paste.  The paste is spliced at the cursor position where it
 * was originally pasted, preserving the user's positional intent.
 */
export function assembleMessage(
  input: string,
  collapsedPaste: CollapsedPaste | null,
): string {
  if (!collapsedPaste) {
    return input.trim();
  }
  const pos = Math.min(collapsedPaste.cursorPos, input.length);
  const before = input.slice(0, pos);
  const after = input.slice(pos);
  return (before + collapsedPaste.fullText + after).trim();
}
