---
name: book-lookup
description: >
  Look up book knowledge from the vault library. Use when a task or conversation
  needs context from a digested book. Navigates the progressive disclosure
  hierarchy (index -> book -> chapter -> section) token-efficiently.
---

# Book Lookup

You retrieve knowledge from digested books stored in `vault/library/`.

## When to Use

- A task or conversation references a book concept, author, or theme
- You need to ground advice in a specific book's argument
- Any prompt asks for book knowledge on a topic

## Progressive Disclosure Protocol

Navigate the hierarchy level by level. **Stop as soon as you have sufficient
context** — do not read deeper than necessary.

### Level 1: Library Index (~200 tokens)

Read `vault/library/_index.md`.

- Scan the catalog for books whose tags or synopses match the query
- If no books are relevant, report that and stop
- If one or more books match, proceed to Level 2 for the best candidate(s)

### Level 2: Book Overview (~500-1000 tokens per book)

Read `vault/library/<book>/_book.md`.

- Review the synopsis, key themes, and chapter index
- Identify which chapter(s) are most relevant to the query
- If the book overview alone answers the question, stop here and return it
- If you need more detail, proceed to Level 3 for the relevant chapter(s)

### Level 3: Chapter Digest (~1000-2000 tokens per chapter)

Read `vault/library/<book>/chapters/<chapter>.md`.

- Read the chapter summary, key ideas, and notable quotes
- If this level provides sufficient context, stop here
- If you need a specific passage or deeper argument, check the section
  references and proceed to Level 4

### Level 4: Granular Section (variable tokens)

Read `vault/library/<book>/sections/<section>.md`.

- Check the `token_count` in frontmatter before reading — stay within budget
- Extract the specific passage or argument needed
- This is the deepest level; return what you find

## Token Budget

Aim to answer queries in **under 4,000 tokens of retrieval** total. This means:

- Most lookups should resolve at Level 2 or 3 (index + book + one chapter)
- Only descend to Level 4 when a specific passage is truly needed
- If multiple books are relevant, read Level 2 for each but only go deeper
  on the most promising one
- Track cumulative tokens read and note it in your response

## Response Format

When returning book knowledge, always include citations:

```
**Source:** *Book Title* by Author — Chapter N: "Chapter Name", Section N.M (p. XX if available)

[Retrieved passage or summary]
```

If you synthesized across multiple levels, note which levels you read:

```
Retrieved from: _index.md → _book.md → chapters/03-chapter-name.md (3 levels, ~1,800 tokens)
```

## Edge Cases

- **No library exists yet:** If `vault/library/_index.md` does not exist, report
  "No books have been ingested into the library yet." Do not fabricate content.
- **Book exists but no matching chapter:** Return the book-level synopsis and
  note that no chapter specifically addresses the query.
- **Query spans multiple books:** Retrieve Level 2 from each relevant book,
  then go deeper only on the one with the strongest match.
- **Token budget exceeded:** If you've read 4,000+ tokens and still don't have
  a clear answer, return what you have with a note that deeper reading may help.

## What This Skill Does NOT Do

- **Ingest books** — retrieval only
- **Create or modify library files** — retrieval only
- **Search outside the vault** — only reads from `vault/library/`
