import { describe, it, expect } from "vitest";
import {
  detectCollapsiblePaste,
  assembleMessage,
  COLLAPSE_LINE_THRESHOLD,
  COLLAPSE_CHAR_THRESHOLD,
} from "./paste";
import type { CollapsedPaste } from "./paste";

// ---------------------------------------------------------------------------
// detectCollapsiblePaste
// ---------------------------------------------------------------------------

describe("detectCollapsiblePaste", () => {
  it("returns null for short text", () => {
    expect(detectCollapsiblePaste("hello world", 0)).toBeNull();
  });

  it("returns null for text at exactly the line threshold", () => {
    const text = Array.from({ length: COLLAPSE_LINE_THRESHOLD }, (_, i) => `line ${i}`).join("\n");
    expect(detectCollapsiblePaste(text, 0)).toBeNull();
  });

  it("collapses text exceeding the line threshold", () => {
    const lines = Array.from({ length: COLLAPSE_LINE_THRESHOLD + 1 }, (_, i) => `line ${i}`);
    const text = lines.join("\n");
    const result = detectCollapsiblePaste(text, 5);

    expect(result).not.toBeNull();
    expect(result!.fullText).toBe(text);
    expect(result!.lineCount).toBe(COLLAPSE_LINE_THRESHOLD + 1);
    expect(result!.cursorPos).toBe(5);
    expect(result!.expanded).toBe(false);
    // Preview is first 4 lines
    expect(result!.preview).toBe(lines.slice(0, 4).join("\n"));
  });

  it("collapses text exceeding the character threshold even if few lines", () => {
    const text = "x".repeat(COLLAPSE_CHAR_THRESHOLD + 1);
    const result = detectCollapsiblePaste(text, 0);

    expect(result).not.toBeNull();
    expect(result!.lineCount).toBe(1);
  });

  it("preserves the cursor position", () => {
    const text = "a\n".repeat(20);
    const result = detectCollapsiblePaste(text, 42);
    expect(result!.cursorPos).toBe(42);
  });
});

// ---------------------------------------------------------------------------
// assembleMessage
// ---------------------------------------------------------------------------

describe("assembleMessage", () => {
  it("returns trimmed input when there is no collapsed paste", () => {
    expect(assembleMessage("  hello  ", null)).toBe("hello");
  });

  it("returns empty string for whitespace-only input and no paste", () => {
    expect(assembleMessage("   ", null)).toBe("");
  });

  // --- paste at beginning ---

  it("prepends paste when cursor was at position 0", () => {
    const paste = makePaste("PASTED", 0);
    expect(assembleMessage("after", paste)).toBe("PASTEDafter");
  });

  // --- paste at end ---

  it("appends paste when cursor was at end of input", () => {
    const paste = makePaste("PASTED", 6);
    expect(assembleMessage("before", paste)).toBe("beforePASTED");
  });

  // --- paste in the middle ---

  it("splices paste at cursor position in the middle of input", () => {
    // "Here's the error:|  What do you think?"
    // cursor at 18 (after "Here's the error: ")
    const paste = makePaste("<log data>", 18);
    expect(assembleMessage("Here's the error:  What do you think?", paste)).toBe(
      "Here's the error: <log data> What do you think?",
    );
  });

  // --- paste-only (empty textarea) ---

  it("returns paste content when textarea is empty", () => {
    const paste = makePaste("just the paste", 0);
    expect(assembleMessage("", paste)).toBe("just the paste");
  });

  // --- cursor beyond input length (defensive) ---

  it("clamps cursor to input length if cursor exceeds it", () => {
    // User typed "hi", cursorPos was saved as 10 (e.g. input was later deleted)
    const paste = makePaste("PASTED", 10);
    expect(assembleMessage("hi", paste)).toBe("hiPASTED");
  });

  // --- whitespace trimming ---

  it("trims leading/trailing whitespace from assembled result", () => {
    const paste = makePaste("PASTED", 3);
    expect(assembleMessage("   ", paste)).toBe("PASTED");
  });

  it("trims outer whitespace but preserves inner structure", () => {
    const paste = makePaste("line1\nline2", 5);
    // input "  ab cd  ", cursor at 5 → before="  ab " after="cd  "
    // assembled: "  ab line1\nline2cd  " → trimmed: "ab line1\nline2cd"
    expect(assembleMessage("  ab cd  ", paste)).toBe("ab line1\nline2cd");
  });

  // --- multiline paste into multiline input ---

  it("handles multiline paste into multiline input", () => {
    const input = "line A\nline B\nline C";
    // Cursor after "line A\n" = position 7
    const paste = makePaste("inserted 1\ninserted 2", 7);
    expect(assembleMessage(input, paste)).toBe(
      "line A\ninserted 1\ninserted 2line B\nline C",
    );
  });
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makePaste(text: string, cursorPos: number): CollapsedPaste {
  const lines = text.split("\n");
  return {
    fullText: text,
    lineCount: lines.length,
    preview: lines.slice(0, 4).join("\n"),
    expanded: false,
    cursorPos,
  };
}
