---
name: digest-book
description: >
  Ingest a book from a PDF attachment into the vault library structure.
  Two-tiered architecture: main loop surveys the book and manages context,
  chapter subagents handle individual chapter digestion. Triggered via
  ClickUp tasks with book-ingestion tag.
---

# Digest Book

Ingest a book PDF into the vault library as a structured, token-efficient
knowledge base. This skill is invoked by the async execution loop when a
ClickUp task has the `book-ingestion` tag and a PDF attachment.

## Architecture: Two-Tiered Processing

Like the async grooming skill, this uses a main loop + subagent pattern:

- **Main loop (you):** Surveys the book, extracts the TOC, manages the running
  context summary, dispatches chapter subagents, builds the book index, and
  runs quality gates.
- **Chapter subagents:** Each receives one chapter's page range, the running
  context summary from prior chapters, and the book's metadata. They produce
  chapter digest files and section files, then return a structured summary
  the main loop uses to update the running context.

**Why subagents?** Each chapter's digestion is a self-contained unit of work
that benefits from a fresh context window focused on that chapter's content.
The main loop stays lean — it never reads the raw chapter text itself, only
the compressed summaries returned by subagents.

## Input

The ClickUp task must contain:
- **Tag:** `book-ingestion`
- **PDF attachment:** The source book (attached to the task or a comment)
- **Description fields:** Title, author, and optionally priority sections or
  specific questions to optimize the digest for

Read the task description with `get_task` to extract title, author, and any
guidance before starting.

## Output Structure

All output goes under `vault/library/<book-slug>/` where `<book-slug>` is the
kebab-cased book title (e.g., `meditations-for-mortals`).

```
vault/library/
  _index.md                          # catalog of all digested books (update)
  <book-slug>/
    _book.md                         # book metadata + master index (under 1K tokens)
    chapters/
      01-<chapter-slug>.md           # chapter digest (1-2K tokens each)
      02-...
    sections/
      01-01-<section-slug>.md        # granular section content
      01-02-...
    source/
      <original-filename>.pdf        # source PDF (committed for private repo access)
```

---

## Main Loop: Processing Pipeline

### Step 0: Setup

1. Download the PDF attachment using `download_attachment` (task_id from prompt).
2. Create the directory structure: `vault/library/<book-slug>/chapters/`,
   `vault/library/<book-slug>/sections/`, `vault/library/<book-slug>/source/`.
3. Copy the PDF into `source/`.
4. If `vault/library/_index.md` does not exist, create it with a header and
   empty table.

### Step 1: Survey the Book

Read the PDF in survey passes to build a table of contents before dispatching
subagents:

1. Read pages 1-20 to find the table of contents, preface, and introduction.
2. If the TOC is not in the first 20 pages, continue reading in 20-page chunks
   until found (most books have it within the first 30 pages).
3. Extract a structured TOC: chapter numbers, chapter titles, and page ranges.
4. Note the total page count and any part/section groupings.
5. Read the introduction/preface (if present) to capture the book's thesis and
   framing — this becomes the seed for the running context summary.

**Important:** The Read tool supports PDF files with a `pages` parameter
(e.g., `pages: "1-20"`). Maximum 20 pages per request. Always specify page
ranges — never attempt to read an entire PDF at once.

**Build the TOC data structure** (keep this in your working memory):

```
Book: <title> by <author>
Total pages: <N>
Chapters:
  1. <title> — pages <start>-<end>
  2. <title> — pages <start>-<end>
  ...
```

### Step 2: Initialize Running Context Document

Create a **context document** at `vault/library/<book-slug>/_context.md` that
accumulates knowledge across chapters. This file is a working document — it
persists between subagent calls so the main loop doesn't waste tokens recopying
context into each subagent prompt. Subagents read this file directly.

Seed the context document (~200-400 tokens) from the introduction or preface:

```markdown
# Running Context: <Book Title>

## Central Thesis
<The book's core argument>

## Key Terminology
- **<Term>** — definition/usage

## Argument Progression
- Chapter 0 (Preface/Introduction): <summary of setup>

## Open Threads
<Questions or themes introduced but not yet resolved>
```

If no introduction exists, create the file with empty sections — the first
chapter subagent will seed it.

**Budget:** The context document should stay under **~2,000 tokens**. After
each chapter subagent returns, the main loop updates this file — appending new
entries and compressing older ones to stay within budget. Early chapters get
progressively compressed as later chapters add detail.

**Cleanup:** Delete `_context.md` after the quality gate passes — it's a
working file, not part of the final library structure.

### Step 3: Dispatch Chapter Subagents Sequentially

Process chapters **in order**, one at a time. Each chapter subagent receives
the running context from all prior chapters and returns a structured result
the main loop uses to update context before dispatching the next subagent.

For each chapter in the TOC:

1. **Build the subagent prompt** using the template in the "Chapter Subagent
   Template" section below. Pass the **file path** to the context document —
   the subagent reads it directly rather than receiving context inline.

2. **Dispatch the subagent** using the Agent tool:
   ```
   Agent(
     description: "Digest ch <N>: <chapter-title>",
     prompt: <built from template>,
     subagent_type: "general-purpose"
   )
   ```

3. **Parse the subagent's return.** The subagent returns a structured summary:
   - `chapter_summary`: 2-3 sentence summary of the chapter's argument
   - `key_concepts`: list of concepts/terms introduced
   - `cross_references`: connections to prior chapters
   - `sections_created`: list of section files written
   - `issues`: any problems encountered (unreadable pages, ambiguous structure)

4. **Update the context document.** Edit `vault/library/<book-slug>/_context.md`:
   - Append this chapter to the Argument Progression section
   - Add new terminology to Key Terminology
   - Update Open Threads (resolve answered questions, add new ones)
   - **Compress older entries** if the file exceeds ~2,000 tokens — merge
     early chapter summaries into broader arc descriptions, drop resolved
     threads. Prioritize:
     - Cumulative argument progression
     - Terminology that later chapters may reference
     - Cross-chapter connections
     - Unresolved thematic threads

5. **Proceed to the next chapter.** The subagent reads the updated context
   document directly — no need to embed context in the prompt.

**Sequential is intentional.** Books are sequential — chapter N assumes
chapters 1 through N-1. The running context summary is the mechanism that
preserves this dependency chain. Do not parallelize chapter processing.

### Step 4: Build the Book Index

After all chapter subagents complete, create `_book.md`. You have all the
chapter summaries from the subagent returns — synthesize them:

```markdown
---
title: "<Book Title>"
author: <Author Name>
tags: [<relevant tags>]
ingested: <today's date>
source_format: pdf
total_chapters: <N>
total_sections: <N>
---

# <Book Title> — <Author Name>

## Synopsis
<3-5 sentence synopsis synthesized from all chapter summaries. What is the
book about? What is the central argument? Who is the intended audience?>

## Key Themes
- <Theme 1>
- <Theme 2>
- ...

## Chapter Index

| # | Chapter | Key Ideas | Sections |
|---|---------|-----------|----------|
| 1 | <Title> | <Comma-separated key ideas> | 01-01 through 01-NN |
| 2 | ... | ... | ... |

## Cross-References
- <Links to related vault content, other books, Brayan's constitution>
```

**Constraint:** `_book.md` MUST be under 1,000 tokens. This is the navigation
hub — Marcus reads it first during retrieval. If it exceeds 1,000 tokens,
compress the chapter index entries (shorter key idea summaries, fewer themes).

### Step 5: Update the Library Index

Update `vault/library/_index.md` to include the new book. Add a row to the
Catalog table:

```markdown
| <book-slug> | [[<book-slug>/_book\|<Title>]] | <Author> | <tags> | <N> | <date> |
```

If the catalog still has the placeholder row (`*(no books ingested yet)*`),
replace it with the new row.

### Step 6: Cross-Reference Existing Books

If `vault/library/_index.md` lists other books besides the one being ingested,
use the `book-lookup` skill (if available) or manually read those books'
`_book.md` files to identify thematic connections. Add relevant cross-references
to the new book's `_book.md` and chapter digests.

If no other books exist in the library yet, skip this step.

---

## Chapter Subagent Template

Build this prompt for each chapter subagent. The subagent has access to all
tools (Read, Write, Glob, Grep, Bash, Agent).

```
You are Marcus, processing a single chapter of a book for the vault library.

## Book Context
- Title: <book title>
- Author: <author>
- Book slug: <book-slug>
- Base path: vault/library/<book-slug>/
- Priority guidance from Brayan: <any notes from the task description about
  priority sections or questions to optimize for, or "None">

## Your Chapter
- Chapter number: <N>
- Chapter title: <chapter title>
- Page range: <start>-<end>
- PDF path: <path to the downloaded PDF>

## Running Context from Prior Chapters

Read the context document at `vault/library/<book-slug>/_context.md` before
starting. This contains the cumulative context from all prior chapters —
the book's thesis, key terminology, argument progression, and open threads.
Use it to understand how this chapter fits into the book's arc and to identify
cross-references to earlier material.

If this is the first chapter, the context document will have mostly empty
sections — that's expected.

## Your Task

Read the chapter and produce:
1. A chapter digest file at `vault/library/<book-slug>/chapters/<NN>-<chapter-slug>.md`
2. Section files at `vault/library/<book-slug>/sections/<NN>-<MM>-<section-slug>.md`

### Reading the Chapter

Use the Read tool with the PDF path and `pages` parameter. Maximum 20 pages
per request. If the chapter spans more than 20 pages, read in sequential
20-page chunks.

### Chapter Digest Format

Write to `vault/library/<book-slug>/chapters/<NN>-<chapter-slug>.md`:

```markdown
---
title: "Chapter <N>: <Chapter Title>"
chapter: <N>
pages: "<start>-<end>"
tokens: <approximate token count: word_count × 1.3, rounded to nearest 50>
tags: [<relevant tags>]
created: <today's date>
updated: <today's date>
---

# Chapter <N>: <Chapter Title>

## Summary
<3-5 sentences capturing the chapter's core argument and its contribution
to the book's overall thesis. Reference how this chapter builds on prior
chapters using the running context.>

## Key Ideas
- **<Idea name>** — <One-line explanation>
- ...

## Notable Quotes
> "<Quote>" (p. <page>)
(2-3 per chapter, with page references)

## Connections
- <Links to other vault content, other books, Brayan's constitution>
- <References to concepts from prior chapters using the running context>

## Sections
| # | Section | Description | File |
|---|---------|-------------|------|
| 1 | <Section title> | <One line> | [[<NN>-01-<slug>]] |
| ... | ... | ... | ... |
```

### Section Files Format

For each logical section within the chapter, write to
`vault/library/<book-slug>/sections/<NN>-<MM>-<section-slug>.md`:

```markdown
---
title: "<Section Title>"
chapter: <N>
section: <M>
pages: "<start>-<end>"
tokens: <approximate token count: word_count × 1.3, rounded to nearest 50>
tags: [<relevant tags>]
created: <today's date>
updated: <today's date>
---

# <Section Title>

<Faithful paraphrase of the section content. For copyrighted works, paraphrase
the arguments and include key quotes with page refs. For open-source docs,
verbatim extraction is acceptable.>

## Key Points
- ...

## Annotations
<Marcus's notes: connections to tasks, connections to concepts from prior
chapters, questions for Brayan, links to other vault content. Clearly
distinguished from the author's text.>
```

### Section Granularity

- **Explicit subheadings** in the source → one section per subheading
- **No subheadings but clear topic shifts** → split at topic boundaries
  (typically every 3-5 pages)
- **Short chapters (<10 pages)** with no subheadings → single section is fine
- **Aim for 500-1500 tokens** per section file. Split further if exceeding this.

### Error Handling

- **PDF read fails on certain pages:** Skip the problematic pages, note the gap
  in the chapter digest ("Pages X-Y could not be read"), and continue.
- **Extremely long chapter (40+ pages):** Do two passes — first a structural
  pass (identify sections and key points), then a detail pass (extract quotes,
  build section files).

### Your Return

After writing all files, return a structured summary in this EXACT format
(the main loop parses this):

CHAPTER_RESULT:
chapter: <N>
chapter_summary: <2-3 sentence summary of the chapter's argument>
key_concepts: <comma-separated list of key concepts/terms introduced>
cross_references: <connections to prior chapters or key themes>
sections_created: <comma-separated list of section filenames written>
issues: <any problems encountered, or "none">
END_CHAPTER_RESULT
```

---

## Quality Gate

Before finalizing, the main loop runs these checks:

### 1. Coverage Check
- Compare the TOC from Step 1 against files in `chapters/`
- Verify every chapter has a corresponding digest file
- Verify every section referenced in chapter digests exists in `sections/`
- If any are missing, dispatch a targeted subagent to fill the gap

### 2. Index Token Count Check
- Estimate the token count of `_book.md` (word count × 1.3)
- If over 1,000 tokens, compress: shorten key ideas, reduce themes, tighten
  the synopsis
- Re-write `_book.md` if needed

### 3. Smoke-Test Queries
Run 3 retrieval queries against the freshly ingested book to verify the
progressive disclosure structure works:

1. Pick a specific concept from an early chapter — verify you can navigate
   from `_book.md` → chapter digest → correct section
2. Pick a concept from a late chapter — same navigation check
3. Pick a cross-cutting theme — verify the chapter index helps identify
   multiple relevant chapters

For each query:
- Start by reading only `_book.md`
- Based on the chapter index, identify the relevant chapter(s)
- Read the chapter digest to confirm the concept is covered
- Read the section file to confirm detailed content is present

If any query fails to navigate correctly, fix the index entries and re-run.

**Document the smoke test results** in the PR description so Brayan can see
the retrieval paths work.

### 4. Clean Up Context Document

Delete `vault/library/<book-slug>/_context.md` — it's a working file that
served its purpose during ingestion. The accumulated knowledge is now encoded
in the chapter digests and `_book.md`. Do not commit the context document.

---

## Token Count Estimation

For the `tokens` frontmatter field, use: `token_count ≈ word_count × 1.3`.
Count words in the file body (excluding frontmatter), multiply by 1.3, round
to the nearest 50. This is a budget hint for retrieval, not exact.

## Handling Large Chapters (>20 pages)

The chapter subagent handles this internally:
1. Read in 20-page chunks using the `pages` parameter
2. Process all chunks before writing — hold the full chapter in context
3. For chapters exceeding 40 pages, do a structural pass first (identify
   sections), then a detail pass (extract quotes, build section files)

## Error Handling

- **PDF read fails on certain pages:** Subagent skips and notes the gap.
  Main loop checks for `issues` in the subagent return and logs them.
- **No TOC found:** Use page headers, chapter title pages, or other structural
  cues to build an approximate TOC. Note in `_book.md` frontmatter:
  `toc_source: inferred`.
- **Extremely long book (500+ pages):** Process normally. The subagent pattern
  keeps per-chapter context manageable regardless of book length. Note in
  the ClickUp task comment if the total ingestion is unusually large.
- **Subagent fails or returns malformed result:** Log the issue, skip the
  chapter, and note it in the quality gate. Dispatch a retry subagent with
  the same prompt once — if it fails again, flag as a blocker.

## What This Skill Does NOT Do

- **No EPUB support** — PDF only for now. EPUB is a future enhancement.
- **No LiquidText annotation processing** — future phase.
- **No eval framework** — separate task handles eval authoring and execution.
- **No docs-sync** — upstream tracking for living documents is separate.
- **No vector embeddings** — pure markdown hierarchy, no vector DB.
- **No parallel chapter processing** — chapters are sequential by design.
