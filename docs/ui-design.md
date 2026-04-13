# Cambium UI — High-Level Design

> Living document. Last updated: 2026-04-08.
> This document defines the architecture and information design for the Cambium web UI.
> It is the basis for implementation plans — no code ships without a section here.

## Purpose

The UI is the primary entry point for users to interact with Cambium. It replaces the CLI
as the default interface for:

- **Conversing** with the system (interlocutor sessions)
- **Responding** to requests and completing user-assigned tasks
- **Observing** system activity (sessions, work items, episodes)
- **Understanding** what the system believes about the user (preferences, constitution)

The UI does NOT replace the CLI for administrative tasks (init, server management, adapter
configuration). Those remain CLI-only.

---

## Tech Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Framework | **React 19 + TypeScript** | Largest ecosystem for complex UIs (chat, streaming, trees). Best AI-assisted development support. Strong portfolio signal. |
| Build | **Vite 6** | Fast HMR, native TypeScript, clean proxy config for dev against FastAPI |
| Styling | **Tailwind CSS v4** | Utility-first, no design system to fight. Fast iteration for a single developer. |
| Components | **Radix UI primitives** | Accessible, unstyled building blocks. Compose with Tailwind rather than overriding a design system. |
| Server state | **TanStack React Query v5** | Handles caching, invalidation, polling, and SSE integration cleanly. Avoids hand-rolled fetch/state sync. |
| Routing | **React Router v7** | Standard. Flat route structure maps cleanly to Cambium's API domains. |
| Icons | **Lucide React** | Lightweight, consistent, MIT-licensed |
| Markdown | **react-markdown + remark-gfm** | For rendering session transcripts, constitution, knowledge entries |

### Not included (and why)

| Omitted | Reason |
|---------|--------|
| Next.js / Remix | We already have a backend. SPA against FastAPI is simpler. |
| Redux / Zustand | React Query handles server state. Local state is minimal — React context suffices. |
| GraphQL | The API is REST + SSE. Adding a GraphQL layer adds complexity for zero benefit. |
| Lexical / rich text editor | V1 doesn't need rich editing. Plain textarea + markdown preview. |
| Drag-and-drop | Premature for v1. Work items don't need manual reordering yet. |

---

## Deployment Model

**Bundled with FastAPI — single process, single port.**

```
Development:
  Vite dev server (:5173) ──proxy /api/*──▶ FastAPI (:8350)

Production:
  FastAPI (:8350)
    ├── /api/*        → API routes (existing)
    └── /*            → StaticFiles(ui/dist/)   ← Vite build output
```

### Why this model

- **Zero additional infrastructure.** `cambium server` already runs. The UI is just static
  files served from the same process.
- **No CORS.** Same origin means no middleware configuration, no preflight requests.
- **Simple deployment.** One process, one port, one container (future).
- **Dev experience preserved.** Vite's proxy gives full HMR + instant reloads against the
  real API during development.

### Build integration

```
ui/
├── src/                    # React source
├── public/                 # Static assets
├── index.html              # Vite entry point
├── vite.config.ts          # Proxy config → FastAPI
├── tsconfig.json
├── tailwind.config.ts
└── package.json            # Project-scoped deps (not global)
```

Production build: `cd ui && npm run build` → outputs to `ui/dist/`.
FastAPI mounts `ui/dist/` as a static file directory with a catch-all fallback for
client-side routing.

---

## Information Architecture

### Navigation Model

Left sidebar with icon + label navigation. Five primary sections:

```
┌──────────────────────────────────────────────────┐
│ [≡] Cambium                                      │
├──────────┬───────────────────────────────────────┤
│          │                                       │
│  💬 Chat │   [ Main content area ]               │
│          │                                       │
│  📥 Inbox│                                       │
│          │                                       │
│  📋 Work │                                       │
│          │                                       │
│  📊 Dash │                                       │
│          │                                       │
│  🧠 Mind │                                       │
│          │                                       │
│──────────│                                       │
│  ⚙ Conf. │                                       │
│          │                                       │
└──────────┴───────────────────────────────────────┘
```

| Section | Route | Purpose |
|---------|-------|---------|
| **Chat** | `/chat` | Start/resume sessions, observe running sessions |
| **Inbox** | `/inbox` | Pending requests + user-assigned tasks (action required) |
| **Work** | `/work` | Work item tree — full project/task hierarchy |
| **Dashboard** | `/dashboard` | System overview — active sessions, queue health, recent activity |
| **Mind** | `/mind` | Constitution, preferences, knowledge, memory browser |
| **Configuration** | `/config` | Routines, adapters, timers (read-only in v1, editable later) |

### Why this grouping

The sections follow user intent, not API structure:

- **"I want to talk"** → Chat
- **"Something needs my attention"** → Inbox
- **"What's the system working on?"** → Work / Dashboard
- **"What does the system believe?"** → Mind
- **"How is the system configured?"** → Configuration

The Inbox is the **action center** — it aggregates everything that requires user response.
Chat is separate because conversations are open-ended, not queue items.

---

## Page Designs

### 1. Chat (`/chat`)

The primary conversational interface. Uses an **embedded terminal** for interactive
sessions — deferring to the adapter's native CLI interface (Claude Code) rather than
reimplementing chat rendering.

#### Design Rationale

Claude Code already has rich rendering: streaming output, tool call visualization,
diffs, syntax highlighting, markdown, interactive prompts. Reimplementing all of this
in React would be enormous effort and always lag behind the real CLI. Instead, the UI
embeds a terminal emulator ([xterm.js](https://xtermjs.org/)) that runs the actual
adapter CLI.

This is **adapter-agnostic by design**: if a future adapter has its own CLI (Codex,
Cursor, etc.), the UI embeds that CLI. The UI doesn't need to know how each adapter
renders its output.

#### Session List (left panel)

A scrollable list of sessions, grouped and sorted:

```
┌─ Active Sessions ──────────────────────┐
│  ● executor — "Digest ch. 3 of..."    │  ← running, observable
│  ● planner — "Decompose career..."    │  ← running, observable
├─ Your Conversations ──────────────────┤
│  ○ interlocutor — "Morning check-in"  │  ← completed today
│  ○ interlocutor — "Resume review"     │  ← completed yesterday
├─ Paused (awaiting input) ─────────────┤
│  ◐ executor — "Merge PR #17"         │  ← has pending request
│  ◐ planner — "Research depth?"       │  ← has pending request
└────────────────────────────────────────┘
                             [+ New Chat]
```

**Data sources:**
- `GET /sessions?status=active` — running sessions
- `GET /sessions?origin=user&limit=20` — user conversations
- `GET /requests?status=pending` → join with session IDs for paused sessions

#### Terminal View (main area — Interactive & Drop-in)

When the user starts a new chat or drops into an existing session, the main area
renders an xterm.js terminal connected to a PTY running the adapter CLI:

```
┌─────────────────────────────────────────────┐
│  interlocutor · active                      │
│  [End Session]                              │
├─────────────────────────────────────────────┤
│                                             │
│  ╭──────────────────────────────────────╮   │
│  │                                      │   │
│  │  > Good morning. You have 3 pending  │   │
│  │    requests and 2 user tasks.        │   │
│  │                                      │   │
│  │  ● Read vault/notes/2026-04-08.md    │   │
│  │    (423 tokens)                      │   │
│  │                                      │   │
│  │  Let's start with the requests.      │   │
│  │                                      │   │
│  │  > The executor working on the       │   │
│  │    resume draft is asking about...   │   │
│  │    ░░░░                              │   │
│  │                                      │   │
│  │  ─────────────────────────────────   │   │
│  │  > _                                 │   │
│  │                                      │   │
│  ╰──────────────────────────────────────╯   │
│                                             │
└─────────────────────────────────────────────┘
```

This IS the Claude Code interface — tool calls, diffs, markdown, streaming all render
natively. The user types directly into the terminal.

**Three interaction modes:**

| Mode | Trigger | Rendering | Backend |
|------|---------|-----------|---------|
| **Converse** | Select/create an interlocutor session | **Terminal** (xterm.js + PTY) | `WS /api/terminal/{session_id}` spawns PTY running `cambium chat interlocutor` |
| **Drop-in** | Click "Drop In" on a system session | **Terminal** (xterm.js + PTY) | Cancel-then-resume: stop running subprocess → spawn PTY with `--resume` |
| **Observe** | Click "Observe" on an active session | **Lightweight transcript** (React) | `GET /sessions/{id}/stream` SSE — plain text, no tool calls |

**New chat flow:**
1. User clicks "+ New Chat"
2. UI opens WebSocket to `WS /api/terminal/new?routine=interlocutor`
3. Backend creates session, spawns PTY running `cambium chat interlocutor --session {id}`
4. xterm.js connects to WebSocket — user sees Claude Code boot up

**Drop-in flow (cancel-then-resume):**

System sessions run as one-shot subprocesses — there's no stdin to inject into
mid-execution. Instead, drop-in uses a **cancel-then-resume** pattern that works
with existing infrastructure:

```
User clicks "Drop In" on active executor session
  │
  ├─ UI shows interstitial: "Waiting for current turn..."
  │  with [Cancel Now] button
  │
  ▼
Server: POST /api/terminal/{session_id}/drop-in
  │
  ├─ Wait up to N seconds (default: 10) for subprocess to complete naturally
  │
  ├─ If timeout: send SIGINT to subprocess (Claude Code handles gracefully)
  │
  ▼
Subprocess exits → session status → COMPLETED (or FAILED)
  │
  ├─ sessions_completed fires with enriched payload (see below)
  │  → summarizer digests the autonomous segment in parallel
  │
  ▼
Server spawns PTY with --resume for this session ID
  │  Claude Code loads full transcript history
  │
  ▼
xterm.js connects — user is in interactive terminal
  │  Session status: ACTIVE again (reopened)
  │
  ▼
User finishes interaction (explicit end or session completes)
  │
  ├─ sessions_completed fires again with interaction_type: "user_drop_in"
  │  → summarizer digests the user interaction segment
  │
  ▼
Done — two digests exist: autonomous work + user intervention
```

**Why cancel-then-resume instead of mid-session injection:**
- System sessions use `claude -p` (non-interactive) — no stdin to pipe into
- The adapter's `attach()` does `os.execvp()` which replaces the process — can't
  attach to an already-running subprocess
- Cancel-then-resume reuses existing infrastructure: `--resume` loads prior
  transcript, `sessions_completed` fires naturally at each boundary
- Each segment gets its own summarizer pass — no new event types needed

**SIGINT safety:** Claude Code handles SIGINT gracefully (saves state). If the
agent was mid-tool-call (e.g., writing a file), partial work may remain. This is
the same risk as Ctrl+C in a normal terminal. The `--resume` session will have
full context of what was attempted, so the user (or the agent) can clean up.

**Terminal lifecycle:**

PTY processes are lightweight (a few MB each). For a single-user system, there is
**no cap on concurrent PTYs**. The user can switch between sessions freely without
killing previous terminals.

All PTYs share a single cleanup rule: **15-minute idle timeout**. The frontend
tracks keypress timestamps per terminal and sends keepalive pings to the server.
After 15 minutes of no terminal input, the server kills the PTY and completes the
session. When a session completes naturally or the user explicitly ends it, the
PTY is also killed.

System sessions (consumer-dispatched) do NOT use PTYs — they use the existing
subprocess model and are governed by per-routine `max_concurrency`.

**What happens when a PTY session idles out:**

Two cases depending on how the session started:

| Session type | Idle behavior | Rationale |
|---|---|---|
| **User-initiated** (interlocutor chat) | PTY killed → session COMPLETED. User can reopen later with `--resume`. | No autonomous work to resume. Session just stops. |
| **Drop-in** (user took over a system session) | PTY killed → session COMPLETED → `sessions_completed` fires → summarizer digests. **Does NOT auto-resume as autonomous.** | The user intervened for a reason — auto-resuming could undo their intent. If the underlying work item still needs doing, the coordinator notices the stalled item on its next activation and re-queues through the normal pipeline. |

The "no auto-resume" rule keeps behavior predictable: once the user takes control,
the system doesn't silently restart work behind them. The coordinator is already
designed to monitor stuck work items and re-route — that's the right layer for
recovery.

#### Observation View (main area — Observe mode)

For passive observation, a lightweight React-rendered transcript replaces the terminal.
This is intentionally simpler — no tool calls, no rich formatting, just message content:

```
┌─────────────────────────────────────────────┐
│  executor · active · observing              │
│  Work item: "Extract relevant experience"   │
├─────────────────────────────────────────────┤
│                                             │
│  [system] Task: Extract relevant experience │
│  from master resume for FAR.AI position...  │
│                                             │
│  [assistant] I'll read the master resume    │
│  and the FAR.AI job posting to identify...  │
│                                             │
│  [assistant] Based on the posting, the key  │
│  requirements are: 1) ML research...        │
│  ░░░░ (streaming)                           │
│                                             │
│                              [Drop In ▶]    │
└─────────────────────────────────────────────┘
```

**Implementation:** `GET /sessions/{id}/stream` SSE with `EventSource`. Renders
`TranscriptEvent` content (the `content` field — human-readable summary, not raw
adapter output). "Drop In" button switches from observation to terminal mode.

**What observation intentionally omits:**
- Tool call details (file reads, edits, bash commands)
- Syntax-highlighted diffs
- Interactive elements
- Raw adapter output

This keeps observation cheap — no PTY, no WebSocket, just SSE polling. The user
can always "Drop In" to get the full experience.

#### Session Segmentation via Enriched Completion Events

The cancel-then-resume pattern gives us natural segmentation: each subprocess run
produces its own `sessions_completed` event. No new event types or tables needed.
The key addition is **enriching the completion payload** so the session-summarizer
(which runs on Haiku) gets explicit context about what to focus on.

**Current `sessions_completed` payload:**
```json
{
  "session_id": "abc123",
  "routine_name": "executor",
  "success": true,
  "trigger_channel": "tasks"
}
```

**Enriched payload:**
```json
{
  "session_id": "abc123",
  "routine_name": "executor",
  "success": true,
  "trigger_channel": "tasks",
  "is_reopened": true,
  "interaction_type": "user_drop_in",
  "prior_digest_exists": true,
  "message_range": { "start": 42, "end": 67 },
  "prior_message_count": 41,
  "canceled": true
}
```

**New fields:**

| Field | Type | Purpose |
|-------|------|---------|
| `is_reopened` | bool | Whether this session was previously completed and reopened |
| `interaction_type` | enum | What kind of run this was (see table below) |
| `prior_digest_exists` | bool | Whether the summarizer has already digested an earlier segment |
| `message_range` | `{start, end}` | Which messages belong to this segment |
| `prior_message_count` | int | How many messages existed before this segment started |
| `canceled` | bool | Whether the subprocess was canceled via SIGINT (vs. natural completion) |

**Interaction types:**

| Value | Meaning | Summarizer directive |
|-------|---------|---------------------|
| `autonomous` | Normal system-triggered run (first run, or resumed after drop-in) | Standard: goal, actions, outcome, learnings |
| `user_drop_in` | User canceled a running session and took over via terminal | Focus on what the user changed or corrected. Strong preference signal. |
| `resume_from_request` | HITL request answered, session resumed via `resume` channel | How did the user's answer affect execution? |
| `user_initiated` | User started this session directly (interlocutor chat) | Standard interactive session |

**Why enrich the payload instead of using watermarks:**

The consolidator uses a watermark pattern (`reflected_through_sequence` in session
metadata) to avoid re-processing. This works for a strong model that can do
bookkeeping. But the session-summarizer runs on **Haiku** — a weaker model that
benefits from explicit directives over inference.

The system already knows all the metadata at the time it publishes `sessions_completed`.
Computing it is cheap (one query for message count). Front-loading it in the payload
lets the summarizer prompt say:

> "A prior digest exists covering messages 1-41 (autonomous executor work).
> Focus your summary on messages 42-67, which represent a user drop-in segment.
> Note what the user changed or corrected relative to the autonomous work."

This is strictly better than asking Haiku to read the full transcript and figure
out what's new.

**Example: full drop-in lifecycle**

```
1. Executor starts on task "Extract relevant experience"
   → subprocess runs, messages 1-41 generated
   
2. User clicks "Drop In"
   → SIGINT sent after 10s timeout
   → subprocess exits
   → sessions_completed fires:
     { interaction_type: "autonomous", canceled: true,
       message_range: {start: 1, end: 41} }
   → summarizer digests messages 1-41 (in parallel with step 3)
   
3. PTY spawns with --resume, user interacts
   → messages 42-67 generated (user redirects approach)
   → user ends session
   → sessions_completed fires:
     { interaction_type: "user_drop_in", is_reopened: true,
       prior_digest_exists: true, prior_message_count: 41,
       message_range: {start: 42, end: 67} }
   → summarizer digests messages 42-67, noting user intervention
```

Two digests exist in `memory/sessions/YYYY-MM-DD/`:
- `{short-id}-seg1.md` — autonomous work (canceled mid-execution)
- `{short-id}-seg2.md` — user drop-in (correction applied)

All sessions use ordinal suffixes starting at `-seg1`, even if never reopened.
This avoids renaming files when a previously-completed session is reopened later.

**Paused sessions:**

A session is considered "paused" when it has a pending blocking request (permission
or information). The UI shows these in the "Paused" group in the session list.
When the user answers the request (from Inbox or by dropping in), the session
resumes via the existing `resume` channel mechanism. The resulting completion event
carries `interaction_type: "resume_from_request"`.

#### Session metadata sidebar (optional, toggleable)

Right panel showing session context:
- Routine name and adapter instance
- Associated work item (if any)
- Episode link
- Pending requests from this session
- Duration and message count
- Segment history (user interactions with timestamps)

---

### 2. Inbox (`/inbox`)

The action center. Everything that needs the user's attention, sorted by urgency.

```
┌─────────────────────────────────────────────────────┐
│  Inbox                                    [filters] │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ⚠ PERMISSION · executor · 2h ago                  │
│  "Can I merge self-improvement PR #17?"             │
│  [Approve] [Reject] [Open Session]                  │
│                                                     │
│  ─────────────────────────────────────────────────  │
│                                                     │
│  ? INFORMATION · planner · 45m ago                  │
│  "What's the API key for the new SMS provider?"     │
│  [Answer] [Open Session]                            │
│                                                     │
│  ─────────────────────────────────────────────────  │
│                                                     │
│  ○ PREFERENCE · coordinator · 1d ago                │
│  "Research depth: survey or deep-dive?"             │
│  Default: survey · Timeout: 48h (23h remaining)     │
│  [Survey] [Deep-dive] [Use your judgment]           │
│                                                     │
│  ═════════════════════════════════════════════════  │
│                                                     │
│  📋 USER TASK · planner · 3h ago                    │
│  "Run setup_oauth.py (requires your credentials)"   │
│  Est: 10 min · Blocks: "Gmail integration setup"    │
│  [Mark Complete] [View in Work Tree]                │
│                                                     │
└─────────────────────────────────────────────────────┘
```

**Data sources:**
- `GET /requests?status=pending` — session requests (permission, information, preference)
- `GET /requests/summary` — counts by type for badge numbers
- `GET /work-items?assigned_to=user&status=ready` — user-assigned tasks

**Interactions:**
- **Answer request:** Inline answer for simple cases (approve/reject, select option).
  Calls `POST /requests/{id}/answer`. For complex answers, "Open Session" drops into
  the originating session context.
- **Complete user task:** "Mark Complete" calls `POST /work-items/{id}/complete`.
  Result field optional (text input appears on click).

**Inbox badge:** The sidebar nav shows a count badge — `pending requests + ready user tasks`.
Polled via React Query with a 10-second stale time.

**Sorting:** Permission > Information > Preference > User Tasks. Within each type, oldest first.

---

### 3. Work (`/work`)

Hierarchical view of all work items in the system.

```
┌──────────────────────────────────────────────────────┐
│  Work Items                    [status filter ▾]     │
├──────────────────────────────────────────────────────┤
│                                                      │
│  ▼ Resume tailoring pipeline          ready          │
│    ├─ Research FAR.AI job posting      completed ✓   │
│    ├─ Extract relevant experience      active ●      │
│    │   └─ Session: executor-abc123     [observe]     │
│    ├─ Generate tailored resume         pending       │
│    └─ ★ Review final PDF               pending 👤   │
│                                                      │
│  ▼ Weekly knowledge consolidation     active ●       │
│    ├─ Scan session digests             completed ✓   │
│    ├─ Update preference beliefs        active ●      │
│    └─ Write weekly digest              pending       │
│                                                      │
│  ▶ MojoMan SMS birthday automation    completed ✓    │
│                                                      │
└──────────────────────────────────────────────────────┘
```

**Data sources:**
- `GET /work-items?status=pending,ready,active,blocked` — top-level items (no parent)
- `GET /work-items/{id}/tree` — expand subtree on click
- `GET /work-items/{id}/events` — event timeline in detail view

**Features:**
- **Expandable tree:** Lazy-loaded children via `/children` or `/tree`
- **Status filtering:** Toggle which statuses are visible (default: hide completed)
- **User tasks highlighted:** Items with `assigned_to: "user"` get a person icon (👤)
  and are visually distinct
- **Session link:** Active items with a `session_id` show a link to observe the session
- **Detail panel:** Clicking an item opens a right panel with full details:
  - Description, context, dependencies
  - Event timeline (created → decomposed → claimed → completed/failed)
  - Associated session transcript (if any)
  - Review history (verdict, feedback)

**Item actions (detail panel):**
- Complete (for user tasks): `POST /work-items/{id}/complete`
- Block/unblock: `POST /work-items/{id}/block` or `/unblock`
- View events: `GET /work-items/{id}/events`

---

### 4. Dashboard (`/dashboard`)

System overview — the "glanceable" page.

```
┌──────────────────────────────────────────────────────┐
│  Dashboard                                           │
├──────────┬──────────┬──────────┬─────────────────────┤
│ Sessions │ Queue    │ Requests │ Work Items          │
│  3 active│ 2 pending│ 1 perm.  │ 4 active            │
│  12 today│ 0 failed │ 2 pref.  │ 2 blocked           │
│          │          │          │ 7 completed today    │
├──────────┴──────────┴──────────┴─────────────────────┤
│                                                      │
│  Recent Activity                                     │
│  ─────────────────────────────────────────────────   │
│  10:32  executor completed "Extract experience"      │
│  10:15  reviewer accepted "Research FAR.AI posting"  │
│  09:45  coordinator → planner: "Resume pipeline"     │
│  09:30  sentry: all systems healthy                  │
│  09:15  interlocutor: morning check-in (user)        │
│                                                      │
├──────────────────────────────────────────────────────┤
│                                                      │
│  Active Sessions                                     │
│  ─────────────────────────────────────────────────   │
│  ● executor (3m) — "Extract relevant experience"     │
│  ● planner (1m) — "Decompose career positioning"     │
│  ● memory-consolidator (30s) — hourly scan           │
│                                                      │
└──────────────────────────────────────────────────────┘
```

**Data sources:**
- `GET /health` — consumer status, pending/in-flight messages
- `GET /queue/status` — queue depth
- `GET /sessions?status=active` — running sessions
- `GET /sessions?limit=20` — recent sessions (for activity feed)
- `GET /requests/summary` — request counts
- `GET /work-items?status=active,blocked` — work item counts
- `GET /events?since=<today>&limit=50` — channel events for activity feed

**Refresh:** React Query with 10-second stale time on health/queue. 30-second on
activity feed. Active sessions polled every 5 seconds.

---

### 5. Mind (`/mind`)

The system's beliefs and the user's values. Read-heavy, with selective editing.

```
┌──────────────────────────────────────────────────────┐
│  Mind                                                │
├──────────┬───────────────────────────────────────────┤
│          │                                           │
│ Constit. │  ## Constitution                          │
│          │                                           │
│ Prefs    │  ### Goals                                │
│          │  1. Sound body and sound mind              │
│ Knowledge│  2. Understand the world                   │
│          │  3. Promote human flourishing              │
│ Episodes │                                           │
│          │  ### Values                                │
│          │  - Wisdom: research before asserting...    │
│          │  - Courage: push back when wrong...        │
│          │                                           │
│          │  [Edit]                                    │
│          │                                           │
└──────────┴───────────────────────────────────────────┘
```

**Sub-pages:**

| Sub-page | Route | Content | Data source |
|----------|-------|---------|-------------|
| **Constitution** | `/mind/constitution` | Rendered markdown (read-only v1) | `GET /api/config/constitution.md` |
| **Preferences** | `/mind/preferences` | Preference belief files (markdown) | `GET /api/fs/ls?root=memory&path=knowledge/user/preferences` + static file fetch |
| **Knowledge** | `/mind/knowledge` | Knowledge entries from memory | `GET /api/memory/ls?path=knowledge` + `GET /api/memory/knowledge/{file}` |
| **Episodes** | `/mind/episodes` | Timeline of routine invocations | `GET /episodes?since=&until=` |

**Preferences sub-page detail:**

Preferences are markdown files in `memory/knowledge/user/preferences/`, each with
a confidence scalar (0-1), evidence trail, and last-confirmed date. The UI renders
these as a browsable list with confidence indicators:

```
┌──────────────────────────────────────────────────────┐
│  Preferences                                         │
├──────────────────────────────────────────────────────┤
│                                                      │
│  Prefers bundled PRs for refactors       conf: 0.7   │
│  Last confirmed: 2026-04-05 · 3 evidence entries     │
│                                                      │
│  Research depth: survey first            conf: 0.8   │
│  Last confirmed: 2026-04-07 · 5 evidence entries     │
│                                                      │
│  Terse responses, no trailing summaries  conf: 0.9   │
│  Last confirmed: 2026-04-08 · 2 evidence entries     │
│                                                      │
│  Horizontal layout for ordered data      conf: 0.5   │
│  Last confirmed: 2026-03-15 · 1 evidence entry       │
│                                                      │
└──────────────────────────────────────────────────────┘
```

Clicking a preference opens the full markdown file — rendered with the evidence
trail, confidence interpretation, and history. Confidence scale:

| Range | Meaning |
|-------|---------|
| 0.9-1.0 | Standing instruction — follow unless user says otherwise |
| 0.7-0.8 | Strong default — follow, mention if visible |
| 0.5-0.6 | Lean toward this, consider asking if high-stakes |
| < 0.5 | Weak signal — don't rely on it, ask |

**Data source:** Entirely served via the filesystem access layer — directory listing
to enumerate files, static file fetch to read each one, frontmatter parsing in the
browser to extract confidence and last-confirmed for the list view.

**Episodes sub-page:**

Timeline view of episodes with filters by routine and date range. Clicking an
episode shows its trigger events, emitted events, and links to the session transcript.

---

### 6. Configuration (`/config`)

Read-only in v1. Shows the current system configuration.

- **Routines:** List of routines with their channel bindings, concurrency settings
- **Adapters:** Instances with model, prompt path, skills, MCP servers
- **Timers:** Cron schedules and their targets
- **Health:** Server health, consumer status, queue depth (duplicate of dashboard
  health card — acceptable for v1)

Future: inline editing with server restart prompt.

---

## Real-Time Data Strategy

The UI uses two real-time transports: **WebSocket** for terminal sessions and
**SSE** for observation. Everything else uses React Query polling.

### Pattern 1: Terminal sessions (WebSocket + PTY)

Interactive chat and drop-in sessions use a WebSocket that bridges xterm.js to a
server-side PTY process.

```
Browser                          Server
┌──────────┐    WebSocket     ┌──────────────────┐
│ xterm.js │ ◄──────────────► │ PTY bridge       │
│          │   binary frames  │   ├─ spawn PTY   │
│          │   (stdin/stdout) │   ├─ cambium chat │
│          │                  │   └─ or attach()  │
└──────────┘                  └──────────────────┘
```

**New endpoint:** `WS /api/terminal/{session_id}` (or `WS /api/terminal/new?routine=X`)

**Server-side implementation:**
- FastAPI WebSocket endpoint
- Uses `pty.openpty()` + `subprocess.Popen` (or `ptyprocess` library) to spawn
  the adapter CLI in a pseudo-terminal
- Bidirectional pipe: WebSocket frames → PTY stdin, PTY stdout → WebSocket frames
- Terminal resize events (`SIGWINCH`) forwarded from xterm.js fit addon
- PTY cleanup on WebSocket disconnect (with configurable grace period for reconnect)

**Client-side implementation:**
- xterm.js with `AttachAddon` for WebSocket connection
- `FitAddon` for responsive terminal sizing
- `WebLinksAddon` for clickable URLs in terminal output
- Connection state management: connecting → connected → disconnected (with reconnect)

### Pattern 2: Session observation (SSE)

Passive observation uses the existing SSE endpoint. Lightweight — no PTY, no
WebSocket. Renders `TranscriptEvent.content` (human-readable summaries) in React.

`GET /sessions/{id}/stream` returns SSE via `EventSource`. Late joiners receive a
full replay of buffered events, then live events.

**Implementation:** `EventSource` API wrapped in a React Query `useQuery` with custom
`queryFn` that manages the EventSource lifecycle. Events append to a transcript
buffer in query data.

### Pattern 3: Polling (everything else)

All non-streaming data uses React Query polling:

| Data | Stale time | Rationale |
|------|------------|-----------|
| Inbox counts | 10s | User needs near-real-time awareness of new requests |
| Active sessions | 5s | Session list should feel live |
| Work items | 30s | Less time-sensitive, changes are event-driven |
| Dashboard health | 10s | Quick pulse check |
| Activity feed | 30s | Background context, not urgent |
| Preferences/knowledge | 5min | Changes infrequently |
| Configuration | Manual | Changes require server restart anyway |

Future optimization: the server could add an SSE endpoint for system events
(new request, session status change, work item transition) to replace polling
with push notifications. This is not needed for v1.

---

## Authentication

### V1: No authentication

Cambium is a personal tool running on localhost. The API has no user authentication
today (JWT tokens are for routine-to-server communication, not user-to-server).

The UI calls API endpoints directly without auth headers. The "interlocutor" auth
needed for answering requests will require a mechanism for the UI to act as the
interlocutor — this needs a design decision:

**Option A: UI gets its own interlocutor JWT at session creation.**
When the user opens the app, the UI creates an interlocutor session and holds
its JWT. Request answers are sent with this token.

**Option B: Dedicated UI auth endpoint.**
`POST /auth/ui-token` returns a token that grants interlocutor-level permissions.
No session creation needed.

**Recommendation: Option A.** It reuses existing infrastructure. The UI always has
an interlocutor session open — that's the chat interface. Its JWT naturally grants
the permission to answer requests. If the user hasn't started a chat yet, answering
a request from the Inbox creates an interlocutor session implicitly.

### Future: Multi-device access

If Cambium ever runs on a remote server (not localhost), proper user authentication
will be needed. This is out of scope for v1.

---

## Filesystem Access

The UI needs read access to two local directories that the server already uses:
- `~/.cambium/memory/` — knowledge entries, session digests, constitution beliefs
- `~/.cambium/` — configuration files (routines, adapters, timers, constitution)

Since the UI runs in the browser, it can't access the filesystem directly. The
server provides read-only access via two mechanisms:

### Static file serving

FastAPI mounts the directories as static file routes:

```python
from fastapi.staticfiles import StaticFiles

app.mount("/api/memory", StaticFiles(directory=memory_dir), name="memory")
app.mount("/api/config", StaticFiles(directory=config_dir), name="config")
```

The UI fetches files directly by path:
- `GET /api/memory/knowledge/user/preferences/research-depth.md`
- `GET /api/memory/sessions/2026-04-08/abc123-seg1.md`
- `GET /api/config/constitution.md`
- `GET /api/config/routines/executor.yaml`

No serialization, no custom endpoints — raw file content. The browser renders
markdown or parses YAML as needed.

### Directory listing endpoint

`StaticFiles` doesn't support directory listings. One lightweight endpoint covers it:

```python
@app.get("/api/fs/ls")
def list_directory(root: str, path: str = ""):
    """List files and subdirectories under a root directory.
    
    root: "memory" or "config"
    path: relative subpath (e.g., "knowledge/user/preferences")
    
    Returns: { entries: [{ name, type: "file"|"dir", size, modified }] }
    """
```

This powers the Mind section's knowledge browser and config viewer — the UI
calls `/api/fs/ls?root=memory&path=knowledge` to list entries, then fetches
individual files via the static mount.

### V1 scope: read-only

Write access (constitution editing, knowledge entry modification) requires
additional considerations (git commits, validation, config reload). Deferred to v2.

---

## Staging Environment Inspection

Cambium's eval system (`cambium eval`) spins up **isolated staging environments** —
each is a separate server process on a random port with its own in-memory DB and
temp data directory. The UI should be able to inspect any staging environment's
data (sessions, work items, episodes, requests) for debugging and eval analysis.

### Configurable API base URL

The UI reads its API target from a URL query parameter, falling back to the default:

```typescript
// lib/api.ts
const API_BASE = new URLSearchParams(window.location.search).get("api") || "/api";
```

To inspect a staging environment:
```
http://localhost:5173/?api=http://127.0.0.1:45231
```

All components (session list, work items, observation view, filesystem access)
work unchanged — the staging server exposes the identical API surface. The only
limitation is the terminal: staging servers may use `:memory:` databases and
lack the PTY bridge, so interactive chat won't work. Observation and data
inspection are fully functional.

### `--inspect` flag on eval command

Extend `cambium eval` with a `--inspect` flag:

```bash
cambium eval defaults/evals/canary-cascade.yaml --inspect
```

Behavior:
1. Run the eval normally
2. On completion, keep the staging server alive (don't clean up)
3. Print: `Inspect at http://localhost:5173/?api=http://127.0.0.1:45231`
4. Server stays alive until Ctrl+C, then cleans up as usual

This lets a developer (or an agent session — see below) examine the full state
of a staging environment after an eval run.

---

## Self-Improving UI

Cambium's self-improvement loop should extend to the UI itself. The system needs
to be able to delegate UI work to executor sessions that can:

1. **Edit UI source code** (React/TypeScript/CSS files in `ui/`)
2. **Build the UI** (`npm run build` in the session working directory)
3. **Spin up a staging environment** with the modified UI
4. **Take screenshots** of the running UI (headless browser)
5. **Evaluate the result** against design criteria
6. **Iterate** — fix issues, rebuild, re-screenshot, re-evaluate

### What this requires

**The UI must be buildable in a session working directory.** The executor session
needs access to `ui/` source, `node_modules/`, and the ability to run `npm`
commands. This is already possible — the session working directory is a full
checkout of the repo, and the executor has shell access.

**Screenshot capability.** The executor session needs a headless browser to
capture screenshots of the running UI. Options:
- Playwright or Puppeteer via an MCP server (similar to Chrome DevTools MCP)
- `cambium eval` with `--inspect` to keep the staging server alive, then
  screenshot via the browser automation tool
- A dedicated `screenshot` skill that boots a staging server, navigates to
  specified routes, and captures images

**Design criteria for self-evaluation.** The executor needs a reference for what
"good" looks like. This could be:
- The aesthetic direction section of this design doc (already machine-readable)
- Reference screenshots stored in the repo (before/after comparison)
- The frontend-design skill's guidelines (already available as a skill)
- An LLM rubric assertion in the eval framework (already supported —
  `assertion.type: llm_rubric`)

### Design constraints for self-improvement compatibility

To make the UI easy for the system to improve:

- **Component isolation.** Each component should be in its own file with clear
  props interfaces. An executor session editing `SessionList.tsx` shouldn't need
  to understand `Terminal.tsx`.
- **CSS variables for theming.** Color and typography changes are single-file
  edits to `index.css`, not scattered across components.
- **Storybook-style isolation** (future). Individual components renderable in
  isolation for targeted screenshots. Not needed for v1 — full-page screenshots
  are sufficient initially.
- **Build must be fast.** Vite's build is already fast (~2-5s for a small app).
  Don't introduce build steps that slow iteration loops.
- **No brittle snapshot tests.** The system iterates visually, not via pixel-
  perfect assertions. LLM rubric evaluation is the right tool.

### Example self-improvement flow

```
1. Memory-consolidator detects pattern: "user complained about session list
   readability in 3 sessions"
   → proposes improvement to plans channel

2. Planner creates task: "Improve session list visual hierarchy"
   → context includes preference beliefs about the user's layout preferences

3. Executor claims task:
   a. Reads current SessionList.tsx
   b. Edits component (increases spacing, adjusts typography)
   c. Runs `cd ui && npm run build`
   d. Boots staging: `cambium eval --inspect` (or direct server start)
   e. Takes screenshot via headless browser
   f. Self-evaluates against design guidelines
   g. Iterates if needed
   h. Creates PR with before/after screenshots

4. Reviewer evaluates the PR:
   - Checks screenshots against design doc criteria
   - Verifies build passes
   - Accepts or rejects with feedback
```

This flow uses existing infrastructure (executor sessions, PR workflow, eval
staging). The only new pieces are screenshot tooling and the LLM design
evaluation — both of which are composable from existing capabilities.

---

## Component Architecture

### Context Providers (app shell)

```
<App>
  <QueryClientProvider>          // React Query cache
    <BrowserRouter>
      <SidebarProvider>          // Sidebar collapse state
        <InboxCountProvider>     // Polling badge count
          <Layout>
            <Sidebar />
            <Outlet />           // Page content
          </Layout>
        </InboxCountProvider>
      </SidebarProvider>
    </BrowserRouter>
  </QueryClientProvider>
</App>
```

Minimal context layers. React Query handles the hard part (server state).
Local UI state (sidebar, panels) uses simple context or component state.

### Shared Components

| Component | Used by | Purpose |
|-----------|---------|---------|
| `SessionList` | Chat, Dashboard | Filterable list of sessions with status badges |
| `Terminal` | Chat | xterm.js wrapper with WebSocket PTY connection |
| `ObservationView` | Chat, Dashboard | Lightweight SSE transcript renderer (no tool calls) |
| `TranscriptMessage` | ObservationView | Single message with role-based styling (plain text) |
| `RequestCard` | Inbox, Dashboard | Compact request display with inline actions |
| `WorkItemTree` | Work | Recursive expandable tree with lazy loading |
| `WorkItemDetail` | Work | Right panel with full item details + events |
| `MarkdownRenderer` | Mind, ObservationView | Renders markdown with syntax highlighting |
| `StatusBadge` | Everywhere | Consistent status pill (active, pending, etc.) |
| `TimeAgo` | Everywhere | Relative time display ("2h ago") |

### Data Hooks (React Query)

```typescript
// Sessions
useSessions(filters)              // GET /sessions
useSession(id)                    // GET /sessions/{id}
useSessionMessages(id)            // GET /sessions/{id}/messages
useSessionStream(sessionId)       // GET /sessions/{id}/stream (SSE observation)

// Terminal (WebSocket PTY)
useTerminal(sessionId, mode)      // WS /api/terminal/{id} — manages xterm.js lifecycle
useTerminalNew(routine)           // WS /api/terminal/new?routine=X — create + connect

// Requests
useRequests(filters)              // GET /requests
useRequestSummary()               // GET /requests/summary
useAnswerRequest()                // POST /requests/{id}/answer
useRejectRequest()                // POST /requests/{id}/reject

// Work Items
useWorkItems(filters)             // GET /work-items
useWorkItem(id)                   // GET /work-items/{id}
useWorkItemTree(id)               // GET /work-items/{id}/tree
useWorkItemChildren(id)           // GET /work-items/{id}/children
useWorkItemEvents(id)             // GET /work-items/{id}/events
useCompleteWorkItem()             // POST /work-items/{id}/complete

// Episodes & Events
useEpisodes(filters)              // GET /episodes
useEpisode(id)                    // GET /episodes/{id}
useEvents(filters)                // GET /events

// Filesystem (memory + config)
useDirectoryListing(root, path)   // GET /api/fs/ls?root=X&path=Y
useFileContent(root, path)        // GET /api/memory/... or /api/config/... (raw fetch)

// System
useHealth()                       // GET /health
useQueueStatus()                  // GET /queue/status
```

---

## Open Questions

1. ~~**Memory/knowledge API.**~~ **Resolved:** Read-only filesystem access via
   static file serving and a directory listing endpoint. See "Filesystem Access"
   section below. Write access (constitution editing, etc.) deferred to v2.

2. **Constitution editing.** Writing to `constitution.md` from the UI requires a write
   endpoint. This has implications (git commits, config reload). Deferred to v2.

3. **Notification strategy.** V1 relies on polling + inbox badge. Future: browser
   notifications (via Notification API) when a permission request arrives? SSE push
   channel for system events?

4. **Mobile responsiveness.** Target desktop-first. Responsive layout (collapsible
   sidebar, stacked panels) is nice-to-have for v1. Mobile-native interaction patterns
   (bottom nav, swipe) are out of scope.

5. **Dark mode.** Support from day one via Tailwind's `dark:` variants and a toggle
   in the sidebar? Or defer?

6. **Drop-in cancel timeout.** How long to wait for the running subprocess to
   complete before sending SIGINT? Too short and we interrupt work that was about
   to finish; too long and the user waits. Initial default: 10 seconds, with a
   "Cancel Now" button for immediate interrupt.

7. **PTY process lifecycle.** When the user switches sessions in the chat list, should
   the PTY be killed immediately or kept alive for quick switch-back? Keeping PTYs
   alive consumes resources. Suggestion: 30-second grace period, then kill.

8. ~~**Digest naming for segments.**~~ **Resolved:** All digests use ordinal suffix:
   `{short-id}-seg1.md`, `{short-id}-seg2.md`, etc. Every session starts at
   `-seg1` even if never reopened. Consistent naming avoids renaming files when
   a session is reopened later.

---

## Implementation Phases

### Phase 1: Foundation + Terminal Chat
- Vite + React + Tailwind scaffold
- FastAPI static file mount + Vite proxy config
- Layout shell (sidebar, routing)
- **WebSocket PTY bridge** — `WS /api/terminal/{session_id}` endpoint in FastAPI
- **xterm.js integration** — Terminal component with WebSocket attach
- Chat page: session list, new interlocutor chat via terminal
- Basic session observation (lightweight SSE transcript view)

### Phase 2: Drop-in + Enriched Payloads
- **Cancel-then-resume endpoint** — `POST /api/terminal/{session_id}/drop-in`
  (SIGINT subprocess → wait → spawn PTY with `--resume`)
- **Enriched `sessions_completed` payload** — add `is_reopened`, `interaction_type`,
  `message_range`, `prior_digest_exists`, `prior_message_count`, `canceled` fields
- **Summarizer prompt update** — use enriched payload for segment-aware digestion
- Drop-in interstitial UI ("Waiting for current turn..." + Cancel Now button)
- Observation → Drop-in transition ("Drop In" button in observe view)
- Session list grouping: active, paused (pending request), user conversations

### Phase 3: Inbox + Request Handling
- Request list with inline actions
- Answer/reject flow with interlocutor JWT
- User task display and completion
- Inbox badge count in sidebar

### Phase 4: Work Items + Dashboard
- Work item tree with lazy-loaded children
- Status filtering
- Work item detail panel with event timeline
- Dashboard summary cards + active session cards
- Activity feed from channel events

### Phase 5: Mind + Polish
- Preferences visualization (dimension bars, cases)
- Episode timeline browser with segment annotations
- Constitution viewer (editing deferred)
- Knowledge browser (requires memory API)
- Dark mode
- Browser notifications for urgent requests
