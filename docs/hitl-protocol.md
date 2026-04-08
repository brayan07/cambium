# Human-in-the-Loop Protocol — Design Doc

## Context

Cambium is a self-improving agent system that processes work autonomously through 8 routines. It can now modify its own prompts/skills/configs through eval-gated PRs (the self-improvement infrastructure). The missing piece is a **formalized protocol for how the system interacts with its user** — when to ask, what to ask, where requests surface, and how the system learns from responses to ask less over time.

The user's vision: Cambium should help the user realize the best version of their future self according to their values. The system needs to understand the user's values (constitution), learn their preferences (general and procedural), and calibrate how much autonomy it takes vs. how much it defers to the user.

### What exists today

- **`input_needed` channel** — 4 routines can publish to it (coordinator, executor, planner, interlocutor) but **nothing listens**. Requests go nowhere.
- **Work item BLOCKED status** — executor can block items awaiting user input, but no systematic unblocking flow.
- **PR review** — the only formalized approval mechanism (for self-improvement changes).
- **Constitution placeholder** — `constitution.md` exists but is empty and unused by routines.
- **Memory consolidator** — writes knowledge entries with confidence scores, but no structured preference format.
- **Interlocutor** — user-facing chat routine, but has no awareness of pending system requests.

### The core insight

There are **two distinct ways** the system needs user involvement, and they need different abstractions:

1. **User tasks** — the planner assigns the user real work as part of a decomposition. These are work items in the task tree.
2. **Session requests** — an agent session (executor, planner, etc.) needs input from the user mid-execution. These are tied to a specific session, not to the task hierarchy.

---

## Design

### 1. User Tasks (work items assigned to user)

Today, work items flow between system routines: coordinator → planner → executor → reviewer. The user participates only at the edges.

**New**: The planner can create work items with `assigned_to: "user"`. This is a **new field** — distinct from `actor` (which represents who claimed/is executing the item). `assigned_to` is set at creation and means "this work is intended for this entity."

| Example | Why it's a work item |
|---|---|
| "Run `setup_oauth.py`" | Real work the user must do, with dependencies and a result |
| "Review and approve PR #17" | Part of a decomposition — downstream work depends on it |
| "Sign the contract with client X" | Physical action, blocks follow-on tasks |

User tasks sit in the normal work item hierarchy with `depends_on` relationships. When the user completes one, `_resolve_dependents()` automatically unblocks downstream items.

**New field on WorkItem:**
```python
assigned_to: str | None = None  # "user" or None (system handles it)
```

The planner creates these via the normal work item API:
```
POST /work-items
{
  "title": "Run setup_oauth.py (requires your credentials)",
  "assigned_to": "user",
  "context": { "delegation": true, "estimated_effort": "10 minutes" }
}
```

### 2. Session Requests (new abstraction)

A session request is a **question or permission check** from an active agent session to the user. It's tied to the session, not to the work item tree.

**Why this can't be a work item:**
- It belongs to a session, not a task hierarchy
- It doesn't need decomposition, review, or retry logic
- The user should be able to drop into the originating session and discuss
- It may have a default answer and timeout (the session proceeds without the user)

**New model: `Request`**

```python
@dataclass
class Request:
    id: str                          # UUID
    session_id: str                  # The session that created this request
    work_item_id: str | None         # Optional: the work item being executed
    type: RequestType                # PERMISSION, INFORMATION, PREFERENCE
    status: RequestStatus            # PENDING → ANSWERED | EXPIRED | REJECTED
    summary: str                     # One-line description
    detail: str                      # Full context for the user
    options: list[str] | None        # Choices, if applicable
    default: str | None              # Default answer if timeout
    timeout_hours: float | None      # Hours before default is applied (null = never)
    answer: str | None               # User's response
    created_at: str
    answered_at: str | None
    created_by: str | None           # Routine name that created the request
```

**Request types** (subset of the taxonomy — delegation is a user task, not a request):

| Type | Blocking? | Has default? | Example |
|---|---|---|---|
| **Permission** | Yes — session waits | No | "Can I merge PR #17?" |
| **Information** | Yes — session waits | No | "What's the API key for X?" |
| **Preference** | No — session uses default after timeout | Yes | "Research depth: survey or deep-dive? (default: survey, 48h)" |

**API endpoints:**

```
POST /requests                         — create a request (called by agent sessions)
GET  /requests                         — list pending requests (interlocutor, coordinator)
GET  /requests/{id}                    — get request details
POST /requests/{id}/answer             — user provides answer
POST /requests/{id}/reject             — user declines
GET  /requests/summary                 — counts by type, attention metrics
```

**How agent sessions use requests:**

An executor session mid-task can call:
```bash
curl -X POST "$CAMBIUM_API_URL/requests" \
  -H "Authorization: Bearer $CAMBIUM_TOKEN" \
  -d '{
    "type": "permission",
    "summary": "Merge self-improvement PR #17",
    "detail": "Eval passed (100%), 3 files changed. Diff: ...",
    "options": ["approve", "reject"]
  }'
```

The request is created, linked to the session. For blocking types (permission, information), the session **ends** after creating the request. When the user answers, the system publishes to a **system-level `resume` channel** with the session ID and answer. The consumer handles `resume` as built-in infrastructure — it looks up the session, finds the owning routine, and reopens the session by injecting the answer as a message. The routine picks up where it left off with full conversation context. For preference types, the session can proceed with the default after timeout without waiting.

**Request completion and session resume flow:**

1. Agent session creates a blocking request via `POST /requests` → session ends
2. User answers the request via the interlocutor (or future UI)
3. Interlocutor calls `POST /requests/{id}/answer` — **only the interlocutor routine can answer requests** (enforced via JWT claims; other routines get 403)
4. The request service:
   a. Updates request status to `ANSWERED`, stores answer and `answered_at`
   b. Publishes to `resume`: `{ "user_response": "<request-id>" }`
5. Consumer picks up the `resume` message
6. Consumer fetches the request by ID → gets `session_id` and `answer`
7. Consumer looks up session → gets `routine_name` → gets routine from registry
8. Consumer reopens the session by injecting the answer as a user message
9. Consumer tracks this as a running episode (same as any dispatch)

The `resume` channel is **system-level** — handled directly by the consumer, not declared in any routine's `listen` list. It bypasses normal channel→routine routing because the session already identifies the target routine.

**Auth constraint:** The `POST /requests/{id}/answer` endpoint validates that the caller is the interlocutor (from the JWT `routine` claim). This ensures only user-mediated responses can answer requests — no routine can answer on the user's behalf.

**How the user interacts with requests:**

1. **Via the interlocutor** (primary path): At session start, the interlocutor calls `GET /requests` and presents pending items. The user answers conversationally. The interlocutor calls `POST /requests/{id}/answer`. The interlocutor can also load context from the originating session to help the user understand what's being asked.

2. **Via a future UI**: User tasks and requests will surface in the Cambium UI. The user can click into the originating session directly. The UI still calls the answer endpoint authenticated as the interlocutor.

All request answers flow through the interlocutor — this is the single gate ensuring the user (not another routine) is the one responding.

#### Preference request UX

Preference requests include brief context and three response paths:
1. **Answer directly** — strongest preference signal
2. **"Use your best judgment"** — the user saw the request and explicitly delegated. This IS a signal: "user trusts the system's judgment for this type of decision." The system proceeds with its default and records a preference belief.
3. **No response (timeout)** — the system applies its default, but this is **not a preference signal**. The user may not have seen it. No belief is created or updated from silence.

#### Blocking request behavior

Permission and information requests **never expire**. They remain pending until the user answers or rejects. The originating session stays paused.

### 3. Coordinator as Queue Monitor

The coordinator monitors both user tasks and session requests:

```
GET /work-items?assigned_to=user       — user's task queue
GET /requests/summary                   — session request metrics
```

On each activation, the coordinator assesses user load. If the user is overloaded:
- **Preference requests past timeout**: apply defaults (but only if the user actually saw the request — see expiration rules below)
- **Low-priority requests**: defer or consolidate
- **Signal replanning**: publish to `plans` asking planners to find approaches that don't require user input
- **Urgent items**: increase push notification frequency

### 3. Preference Learning

Preferences are learned from two sources at different timescales:

#### Immediate: Session-summarizer issues preference thoughts

The session-summarizer already reads every session transcript. When it detects a preference signal (user correction, explicit statement, style choice), it publishes a thought to the `thoughts` channel:

```json
{
  "type": "preference_signal",
  "dimension": "research_depth",
  "observation": "User said 'start shallow, I'll ask for more'",
  "direction": "prefer survey over deep-dive as default",
  "signal_strength": "explicit_statement",
  "session_id": "abc123"
}
```

The coordinator receives this on `thoughts` and decides whether it warrants immediate action (e.g., updating a preference belief) or should wait for the consolidator's cross-session analysis.

#### Cross-session: Consolidator detects preference patterns

The consolidator runs on a **15-minute cadence** (tightened from hourly) so preference signals from request answers are picked up quickly. During its scans, it looks for patterns across multiple session digests:

- "User has rejected verbose outputs in 4 of the last 6 sessions" → creates/strengthens a preference belief
- "User approved all wiki edits without changes for 3 weeks" → proposes risk calibration update
- "User's behavior contradicts stated constitution value" → surfaces drift observation

The consolidator writes preference beliefs as knowledge entries in `~/.cambium/memory/knowledge/user/preferences/`.

#### Belief format and lifecycle

Standard knowledge entry format:

```markdown
---
title: Research depth preference
confidence: 0.7
last_confirmed: 2026-04-07
---

User prefers survey-level research as a first pass, with deep dives queued
as follow-on tasks only when the survey reveals unexpected complexity or
the user explicitly requests depth.

**Evidence:**
- Approved 3 survey-level outputs without requesting more depth
- Rejected one deep-dive as "overkill for what I needed" (session abc123)
- Explicitly stated "start shallow, I'll ask for more" (session def456)
```

**Lifecycle:**
1. **Genesis**: Explicit user statement (high confidence) or consolidator pattern detection across 3+ sessions (medium confidence)
2. **Strengthening**: Consistent behavior increases confidence
3. **Challenge**: Contradictory behavior → consolidator revises (low confidence) or surfaces as preference request (high confidence: "I thought you preferred X, but you just did Y")
4. **Staleness**: Not confirmed in 90 days → flagged during weekly consolidation

#### How routines consume preferences

Routines read relevant preference files before making judgment calls. A `user-alignment` skill provides a routing table for which preference files are relevant to each routine's decisions.

#### User visibility

The memory repo is human-readable markdown with full git history. The UI exposes it directly — the user can browse all knowledge entries (including preference beliefs), see when they were formed, how they evolved, and edit or delete anything they disagree with. No special preferences dashboard needed; it's just a window into the memory repo. The system has no hidden beliefs about the user.

### 4. Constitution

The constitution is a markdown document where the user articulates their values, goals, and priorities. It lives at `{config_dir}/constitution.md` in the user's versioned repository — not in the system's internal memory.

#### Initialization

A **template** ships with Cambium:

```markdown
# Constitution

## Goals
<!-- What are you trying to achieve in life? List 2-5 overarching goals. -->

## Values
<!-- What principles guide your decisions? What trade-offs do you make? -->

## Projects
<!-- What long-term projects or areas of focus matter to you? -->

## Working Style
<!-- How do you prefer to work? What conditions help you do your best? -->
```

The first time the user starts an interlocutor session after init, the interlocutor offers a **guided conversation** to fill this out. It asks questions, reflects back what it hears, and writes the constitution with the user's approval. The user can also just edit the file directly.

#### How routines use it

- **Coordinator**: Reads when triaging requests that involve goal conflicts. Surfaces which goals are at stake.
- **Planner**: Reads when decomposing high-level objectives. Uses values to calibrate priority, scope, and the balance between thoroughness and speed.
- **Consolidator**: Reads during weekly review. Compares revealed preferences against stated values. Surfaces drift as a thought: "Your constitution says X, but your behavior this month suggests Y."

The constitution is NOT loaded into every session — only when a routine's decision touches the user's goals or values.

### 5. Attention Budget

The coordinator monitors the user's request queue and response patterns. It maintains a model of user availability — not as a hard numerical budget, but as situational awareness.

**Signals the coordinator tracks:**
- Number of pending user requests by type
- Average response latency over the past week
- Whether the user has been active recently (interlocutor sessions)
- Explicit user signals ("I'm busy this week", "ask me more about X")

**Coordinator responses to overload:**
- Stop creating non-blocking (preference) requests
- Consolidate related questions into one
- Signal planners to find approaches that don't require user input
- Apply defaults for preference items past their timeout
- For blocking items: increase push notification urgency

The consolidator also maintains an attention budget belief in memory, updated weekly, capturing the user's general tolerance for interruptions.

### 6. Risk Calibration

Risk calibration is a specific category of preference beliefs. The consolidator maintains risk beliefs:

```markdown
---
title: Risk calibration — self-improvement PRs
confidence: 0.9
last_confirmed: 2026-04-07
---
Always require PR review. Standing policy.
```

```markdown
---
title: Risk calibration — knowledge updates
confidence: 0.7
last_confirmed: 2026-04-05
---
Low-risk. Consolidator commits directly. Git-tracked and auditable.
User has never objected to a consolidator commit.
```

**Safety invariant**: The system never self-promotes to lower risk levels. It proposes promotions as preference requests assigned to the user. Only the user approves. Rejections immediately revert.

### 7. The User-Alignment Skill

A skill providing reference material for how routines incorporate the HITL protocol:

```
defaults/adapters/claude-code/skills/user-alignment/
  SKILL.md          — routing table
  references/
    constitution.md   — how to read and apply the user's constitution
    preferences.md    — how to read, create, and update preference beliefs
    requests.md       — request types, when to assign tasks to user, API usage
    risk.md           — risk calibration beliefs, safety invariants
    budget.md         — attention awareness, overload responses
```

Progressive disclosure pattern, same as the self-improvement skill.

---

## Implementation Phases

### Phase 1: User tasks + session requests (the two abstractions)
- Add `assigned_to` field to work item model and store
- Build `Request` model, store, and `/requests` API endpoints
- Update planner prompt: can create work items with `assigned_to: "user"`
- Update executor/planner prompts: can create session requests via API
- Update interlocutor: reads pending user tasks + requests at session start
- Update coordinator: monitors both queues
- Create `user-alignment` skill with `references/requests.md`
- Document new APIs in `cambium-api` skill

### Phase 2: Constitution
- Ship constitution template in defaults
- Build guided initialization flow in interlocutor prompt
- Wire constitution reads into coordinator, planner, consolidator prompts
- Create `references/constitution.md` in user-alignment skill

### Phase 3: Preference learning
- Define preference directory structure in memory
- Update session-summarizer: emit `preference_signal` thoughts to `thoughts` channel
- Update consolidator: detect cross-session patterns, maintain preference belief files
- Wire routines to read preference files before judgment calls
- Create `references/preferences.md` in user-alignment skill

### Phase 4: Attention budget + risk calibration
- Coordinator attention awareness (queue monitoring, overload → replan signals)
- Consolidator weekly attention budget belief in memory
- Risk calibration beliefs in memory
- Create `references/budget.md` and `references/risk.md`

---

## Key decisions

1. **Two abstractions for user involvement.** Work items with `assigned_to: "user"` for real tasks. `Request` model for session-level questions/permissions. Different lifecycles, different APIs.
2. **`assigned_to` is a new field**, separate from `actor`. `actor` = who claimed it. `assigned_to` = who should do it.
3. **Requests are tied to sessions**, not the work item tree. The user can drop into the originating session to discuss.
4. **Defaults and timeouts set by the creating routine.** The routine has the domain context to know what a reasonable default is. The coordinator manages the attention budget but doesn't override per-request defaults.
5. **No separate preference store.** Preferences are knowledge entries in the memory git repo.
6. **No Bayesian machinery.** LLMs read evidence and adjust beliefs.
7. **Two-speed preference learning.** Session-summarizer catches immediate signals; consolidator detects cross-session patterns.
8. **Constitution lives in memory** with git tracking. Initialized via guided interlocutor session from a template.
9. **Coordinator monitors both queues** (user tasks + session requests) and can trigger replanning when the user is overloaded.
10. **Risk auto-promotion requires user approval.** The system proposes, the user disposes.
11. **Notifications deferred.** UI will surface requests. Webhook adapter later if needed.

## Resolved questions

1. **Request polling vs. blocking.** Sessions end and are resumed when the user answers. Sessions already support reopening. No new infrastructure needed.
2. **Notifications.** Deferred — the UI will surface user tasks and requests. Webhook adapter can be added later.
3. **Request expiration signals.** Silence is NOT a signal. Only explicit "use your best judgment" responses generate preference beliefs. This prevents the system from learning from non-events.

## Resolved questions

4. **Session resume trigger.** When the user answers a request, the request service publishes to a system-level `resume` channel. The consumer handles it directly — looks up the session, finds the routine, reopens the session with the answer injected as a message. No new channel in routine configs.

## Resolved questions

5. **Request visibility tracking.** No `seen_at` tracking. Instead, every request includes a "use your best judgment" option that the user can select quickly. This gives the system an explicit delegation signal without needing to infer anything from silence. Timeouts apply defaults without generating preference signals.
6. **Preference signal path from request answers.** Batch via the existing digest pipeline. The interlocutor session transcript captures the user's answer → session-summarizer digests it → consolidator picks it up on its next scan. Consolidator cadence tightened to 15 minutes (from hourly) so signals are processed quickly. No new channels or event-driven mechanisms needed.

## Files to modify/create

### New files
| File | Purpose |
|------|---------|
| `src/cambium/request/model.py` | `Request`, `RequestType`, `RequestStatus` dataclasses |
| `src/cambium/request/store.py` | SQLite persistence for requests |
| `src/cambium/server/requests.py` | `/requests` API endpoints |
| `defaults/adapters/claude-code/skills/user-alignment/SKILL.md` | Routing table for HITL protocol |
| `defaults/adapters/claude-code/skills/user-alignment/references/` | Progressive disclosure references |
| `defaults/constitution-template.md` | Template for guided initialization |

### Modified files
| File | Change |
|------|--------|
| `src/cambium/consumer/loop.py` | Handle `resume` as system-level channel: look up session → routine, reopen session with answer |
| `src/cambium/work_item/model.py` | Add `assigned_to: str | None` field |
| `src/cambium/work_item/store.py` | Persist and query `assigned_to`; add `list_items(assigned_to=...)` filter |
| `src/cambium/work_item/service.py` | Notification trigger when `assigned_to="user"` item is created |
| `src/cambium/server/work_items.py` | Expose `assigned_to` in API request/response models |
| `src/cambium/server/app.py` | Register requests router, create request store |
| `defaults/adapters/claude-code/prompts/planner.md` | Can create user-assigned work items |
| `defaults/adapters/claude-code/prompts/coordinator.md` | Monitors user queue + requests, detects overload |
| `defaults/adapters/claude-code/prompts/interlocutor.md` | Reads pending requests/tasks at session start |
| `defaults/adapters/claude-code/prompts/session-summarizer.md` | Emits preference signal thoughts |
| `defaults/adapters/claude-code/prompts/memory-consolidator.md` | Cross-session preference pattern detection |
| `defaults/timers.yaml` | Add 15-minute consolidator cadence |
| `defaults/adapters/claude-code/skills/cambium-api/SKILL.md` | Document new `/requests` and `assigned_to` APIs |

## Verification

- Unit tests for user request API endpoints
- Integration test: planner creates user-assigned item → appears in `/user/requests`
- Integration test: user completes item → blocked dependent item unblocks
- Canary-level test: full cascade with a user-assigned delegation step
