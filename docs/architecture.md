# Cambium Architecture

> Living document. Last updated: 2026-04-05.
> This file is the canonical reference for how the system fits together.
> Update it when the architecture changes.

## What Cambium Is

A personal empowerment engine — an async AI agent framework oriented around a single user's values. Not a task management system powered by AI, but a thought partner that learns, reflects, and improves.

The core differentiator is the **self-improvement loop**: skills are hypotheses about how to help the user; the lifecycle engine runs experiments, measures outcomes against the user's constitution, and proposes improvements.

## System Overview

```mermaid
graph TD
    subgraph External
        Triggers["External Triggers<br/>(n8n, CLI, webhooks)"]
    end

    subgraph Server["Cambium Server (FastAPI)"]
        ChannelAPI["Channel API<br/>/channels/*"]
        Queue["SQLite Queue<br/>(messages)"]
        Consumer["Consumer Loop<br/>poll → dispatch → ack/nack"]
        SessionAPI["Session API<br/>/sessions/*"]
        Runner["Routine Runner<br/>resolve instance → create session<br/>→ issue JWT → delegate"]
        Adapter["Adapter (Claude Code)<br/>build skills dir → write .mcp.json<br/>→ spawn subprocess → stream events"]
        Store["Session Store<br/>(SQLite)"]
        Broadcaster["Stream Broadcaster<br/>(SSE fanout)"]
    end

    subgraph Subprocess
        Claude["Claude Code CLI<br/>Skills + MCP servers<br/>loaded from session cwd"]
    end

    Triggers -->|HTTP POST| ChannelAPI
    ChannelAPI --> Queue
    Queue --> Consumer
    Consumer --> Runner
    Runner --> Adapter
    Adapter --> Store
    Adapter --> Broadcaster
    Broadcaster -->|SSE stream| SessionAPI
    Adapter -->|subprocess| Claude
```

## Core Abstractions

### Message

The fundamental unit of communication. Travels through named **channels**.

```
Message
├── id: str               # Generated from uuid4()
├── channel: str          # e.g., "tasks", "completions"
├── payload: dict         # Arbitrary JSON data
├── source: str           # Who published it
├── status: pending → in_flight → done | failed
├── attempts: int         # Retry count (max 3)
├── timestamp: datetime
└── claimed_at: datetime | None
```

### Routine

YAML-defined event handler. Binds a channel listener to an adapter instance. Routines define **permissions** — what a routine can read and write.

```yaml
# Example: executor.yaml
name: executor
adapter_instance: executor       # Which adapter config to use
listen: [tasks]                  # Channels to consume from
publish: [completions, input_needed]  # Channels allowed to emit to
```

### Adapter Instance

User-configured personality of an adapter type. Each instance has its own model, system prompt, skills, and MCP servers.

```yaml
# Example: ~/.cambium/adapters/claude-code/instances/executor.yaml
name: executor
adapter_type: claude-code
config:
  model: opus
  system_prompt_path: adapters/claude-code/prompts/executor.md
  skills: [cambium-api]
  mcp_servers: [clickup, gmail]
```

### Adapter Type

Runtime abstraction — how to execute an adapter instance. Currently one implementation: `ClaudeCodeAdapter`.

```
AdapterType (ABC)
├── send_message(instance, user_message, session_id, session_token,
│                api_base_url, live, on_event, on_raw_event, cwd) → RunResult
│   Callbacks:
│   ├── on_event(chunk)        # OpenAI-format SSE chunks → broadcaster
│   └── on_raw_event(event)    # TranscriptEvent → session store
└── launch_interactive(instance, session_id, cwd)  # exec into CLI
```

### Session

Tracks a single execution context. Two types:

| Type | Created by | Lifecycle |
|------|-----------|-----------|
| ONE_SHOT | Consumer loop | Message arrives → session created (ACTIVE) → adapter runs → COMPLETED/FAILED |
| INTERACTIVE | Session API | Client creates → sends messages → observes via SSE → closes |

```mermaid
stateDiagram-v2
    [*] --> CREATED
    CREATED --> ACTIVE: one-shot: immediate / interactive: first message
    ACTIVE --> COMPLETED: success
    ACTIVE --> FAILED: error / max retries
    COMPLETED --> [*]
    FAILED --> [*]

    note right of CREATED: One-shot sessions skip CREATED —\nstored directly as ACTIVE.\nInteractive sessions persist CREATED\nuntil first message.
```

```
Session
├── id: str               # Generated from uuid4()
├── type: ONE_SHOT | INTERACTIVE
├── status: CREATED → ACTIVE → COMPLETED | FAILED
├── routine_name, adapter_instance_name
├── metadata: dict        # Arbitrary session metadata
└── created_at, updated_at: datetime
```

Note: `working_dir` (`~/.cambium/data/sessions/{id}/`) is computed at runtime by the RoutineRunner, not stored on the Session model. Messages are stored separately in the `session_messages` table via `SessionStore`.

### Skill

Claude Code native capability — a directory containing `SKILL.md` with YAML frontmatter.

Skills are the agent's tools. The built-in `cambium-api` skill lets the agent publish messages to channels using `CAMBIUM_API_URL` and `CAMBIUM_TOKEN` environment variables. This is how adapters trigger downstream work **without knowing about Cambium internals**.

### TranscriptEvent

Adapter-agnostic event for persistence. Each adapter translates its native stream format into this contract; the runner persists it blindly.

```
TranscriptEvent
├── role: assistant | user | system | tool
├── content: str              # Human-readable summary
├── event_type: str           # Adapter-specific label
└── raw: dict                 # Original event (nothing lost)
```

## Channel Topology

Channels are **wake-up signals**, not context carriers. They contain minimal metadata (event type, entity key). The receiving routine looks up full context from the shared database. This keeps messages lightweight and the database as the single source of truth.

```mermaid
graph LR
    subgraph External
        ext(["events"])
    end

    subgraph Routines
        coordinator["coordinator"]
        interlocutor["interlocutor"]
        planner["planner"]
        executor["executor"]
        reviewer["reviewer"]
        consolidator["consolidator"]
    end

    subgraph Channels
        plans(["plans"])
        tasks(["tasks"])
        completions(["completions"])
        evaluations(["evaluations"])
        reflections(["reflections"])
        sessions_completed(["sessions_completed"])
        input_needed(["input_needed"])
    end

    subgraph Data
        input_store[("input_requests store")]
    end

    ext --> coordinator
    evaluations --> coordinator
    reflections --> coordinator

    coordinator --> plans
    coordinator --> tasks
    coordinator --> events
    coordinator --> input_needed

    interlocutor -.->|can publish to any channel| plans
    interlocutor -.-> tasks
    interlocutor -.-> events

    plans --> planner
    planner --> tasks
    planner --> input_needed

    tasks --> executor
    executor --> completions
    executor --> input_needed

    completions --> reviewer
    reviewer --> evaluations

    sessions_completed --> consolidator
    consolidator --> reflections

    input_needed --> input_store
```

### Design Principles

- **Channels as wake-up signals.** Messages carry minimal payload (event type + entity key). Routines look up full context from the shared database. This avoids stale data in messages and keeps the database as the single source of truth.
- **Event batching.** The coordinator accumulates events within a time window (~1 min) before processing. This prevents thrashing on rapid external updates (e.g., multiple ClickUp status changes in quick succession). The consolidator similarly batches completed session logs.
- **Interlocutor = interactive coordinator.** The interlocutor has the same broad permissions as the coordinator — it can publish to any channel. The difference is the trigger: the coordinator wakes from external events, the interlocutor wakes from the user. Both can route work anywhere.
- **User input authority split.** Only work-doing routines (coordinator, planner, executor) can request user input. Evaluating routines (reviewer, consolidator) must predict what the user would say based on past behavior, stated values, and feedback history — that's their job.
- **`input_needed` is system-consumed.** No routine listens on `input_needed` — the system auto-persists these to the central `input_requests` store. The coordinator reads the store during batch processing to stay aware of pending input, avoiding a self-wake loop.

### Channel Reference

| Channel | Producers | Consumers | Payload |
|---------|-----------|-----------|---------|
| `events` | External (ClickUp, cron, user actions), coordinator | coordinator (batched) | Event type + entity key |
| `plans` | coordinator, interlocutor | planner | Project key |
| `tasks` | coordinator, planner, interlocutor | executor | Task key |
| `completions` | executor | reviewer | Task key + output reference |
| `evaluations` | reviewer | coordinator | Task key + verdict (accepted / rejected / changes_requested) |
| `reflections` | consolidator | coordinator | Observation + evidence references |
| `sessions_completed` | system (on session close) | consolidator | Session ID |
| `input_needed` | coordinator, planner, executor | system (auto-persist to input_requests store) | Entity key + question + external location |

### Routine Reference

| Routine | Listens on | Publishes to | User input | Batching |
|---------|-----------|-------------|------------|----------|
| **coordinator** | `events`, `evaluations`, `reflections` | `plans`, `tasks`, `events`, `input_needed` | Yes (registers in store) | ~1 min window on `events` |
| **interlocutor** | *(user session)* | any channel | Is the user interface | None — real-time |
| **planner** | `plans` | `tasks`, `input_needed` | Yes (registers in store) | None |
| **executor** | `tasks` | `completions`, `input_needed` | Yes (registers in store) | None |
| **reviewer** | `completions` | `evaluations` | No — must predict | None |
| **consolidator** | `sessions_completed` | `reflections` | No — must predict | Batches completed sessions |

## Data Flow: End to End

```mermaid
sequenceDiagram
    participant Ext as External Trigger
    participant API as Channel API
    participant Q as SQLite Queue
    participant CL as Consumer Loop
    participant RR as Routine Runner
    participant Ad as Claude Code Adapter
    participant CC as Claude Code CLI
    participant SS as Session Store
    participant SB as Stream Broadcaster

    Ext->>API: POST /channels/tasks/send
    API->>Q: publish(Message)
    Note over Q: status = pending

    CL->>Q: consume(channels, limit=10)
    Q-->>CL: [Message] (status → in_flight)

    CL->>RR: send_message(routine, message, session_id)
    RR->>SS: create session (ACTIVE)
    Note over RR: resolve instance, issue JWT,<br/>create working dir
    RR->>SS: store user message as SessionMessage

    RR->>Ad: send_message(instance, user_message, session_id)
    Ad->>Ad: build skills dir, write .mcp.json
    Ad->>CC: spawn subprocess (stdin: user message)

    loop stream-json output
        CC-->>Ad: raw event line
        Ad->>SS: TranscriptEvent → SessionMessage
        Ad->>SB: OpenAI chunk → SSE subscribers
    end

    CC-->>Ad: exit code
    Ad-->>RR: RunResult (success/failure)
    RR->>SS: update session (COMPLETED/FAILED)

    alt success
        CL->>Q: ack(msg.id)
    else failure
        CL->>Q: nack(msg.id) — retry up to 3x
    end
```

## Configuration Model

All user state lives in `~/.cambium/`, bootstrapped by `cambium init`.

```
~/.cambium/
├── config.yaml                     # Framework config (db path, queue adapter)
├── constitution.md                 # User's values, goals, priorities
├── mcp-servers.json                # MCP server registry (user-created, not seeded by init)
│
├── routines/                       # Channel → adapter bindings
│   ├── coordinator.yaml
│   ├── interlocutor.yaml
│   ├── planner.yaml
│   ├── executor.yaml
│   ├── reviewer.yaml
│   └── consolidator.yaml
│
├── adapters/
│   └── claude-code/
│       ├── instances/              # Adapter personalities
│       │   ├── coordinator.yaml
│       │   ├── executor.yaml
│       │   └── ...
│       ├── prompts/                # System prompts per instance
│       │   ├── coordinator.md
│       │   ├── executor.md
│       │   └── ...
│       └── skills/                 # Seeded with cambium-api; user adds custom skills here
│
├── data/
│   ├── cambium.db                  # SQLite (messages + sessions + transcripts)
│   ├── sessions/{session_id}/      # Working dir per execution
│   ├── memory/                     # User memory/context (reserved, not yet integrated)
│   └── logs/                       # Execution logs (reserved, not yet integrated)
│
├── knowledge/                      # Knowledge base (user-managed)
└── .git/                           # Version-controlled for backup
```

### MCP Server Config

```json
// ~/.cambium/mcp-servers.json
{
  "clickup": {
    "command": "python3",
    "args": ["-m", "mcp.server.clickup"],
    "env": { "CLICKUP_TOKEN": "..." }
  },
  "gmail": {
    "url": "https://gmail.mcp.claude.com/mcp",
    "headers": { "Authorization": "Bearer ..." }
  }
}
```

Supports both `stdio` (command + args) and `remote` (url + headers) transports. The adapter converts these to `.mcp.json` format and writes it to the session's working directory. Claude Code discovers it automatically from cwd.

## CLI Entry Points

| Command | Purpose |
|---------|---------|
| `cambium init [--github]` | Bootstrap `~/.cambium/` from defaults. Optionally create private GitHub repo for backup. |
| `cambium server [--live] [--port 8350]` | Start FastAPI server + consumer loop. `--live` enables real Claude Code execution (vs mock). |
| `cambium send CHANNEL [PAYLOAD]` | Publish a message to a channel via HTTP. |
| `cambium chat ROUTINE` | Start interactive Claude Code session with a routine's config. Execs into CLI. |

## API Surface

### Unauthenticated

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/channels/{channel}/send` | POST | Publish message (external triggers) |
| `/queue/status` | GET | Pending count + subscribed channels |
| `/health` | GET | Server health + consumer status |

### Authenticated (JWT — issued to adapter sessions)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/channels/{channel}/publish` | POST | Publish with permission check (routine must list channel in `publish`) |
| `/channels/permissions` | GET | Query routine's read/write channels |

### Session API

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/sessions` | POST | Create interactive session |
| `/sessions/{id}/messages` | POST | Send message → SSE stream response |
| `/sessions/{id}/messages` | GET | Conversation history |
| `/sessions/{id}` | GET | Session metadata |
| `/sessions/{id}/stream` | GET | Observe running session (SSE) |
| `/sessions/{id}` | DELETE | End session |

## Key Design Decisions

1. **Adapters don't know about channels.** An adapter receives a message and produces output. To trigger downstream work, the agent uses the `cambium-api` skill — calling back to the server via HTTP with its JWT token. This keeps adapters decoupled from the framework.

2. **Everything in `~/.cambium/`.** User config, routines, prompts, skills, MCP servers, and data all live in one directory. The framework reads from it; `cambium init` seeds it from `defaults/`. This directory is git-backed for versioning and backup.

3. **SQLite for everything persistent.** Queue, sessions, transcripts — single DB file at `~/.cambium/data/cambium.db`. Simple, reliable, no external dependencies.

4. **TranscriptEvent as adapter-agnostic contract.** Each adapter translates its native stream format (Claude's stream-json, future adapters' formats) into TranscriptEvents. The runner persists them without inspecting content. Format-specific logic lives in the adapter, not the runner.

5. **JWT-scoped permissions.** Each session gets a token encoding its routine name. When the agent publishes to a channel via `cambium-api`, the server verifies the routine is allowed to publish there. This prevents the reviewer from accidentally writing to `plans`.

6. **One-shot vs interactive sessions.** The consumer loop handles one-shot (fire-and-forget) execution. The session API handles interactive (multi-turn, SSE-observable) conversations. Same adapter, different lifecycle.

## Current State & Gaps

### Implemented (as of 2026-04-05)
- Core server, consumer loop, queue, session store
- Claude Code adapter with skills, MCP passthrough, transcript storage
- Channel-based pub/sub with JWT permissions
- `cambium init` with GitHub backup option
- Interactive sessions via API (SSE streaming)
- 6 default routines (coordinator, interlocutor, planner, executor, reviewer, consolidator)

### In Progress
- **Phase 2: Port Marcus** — replacing n8n + async-runner.py with Cambium's consumer loop
- **ClickUp polling source** — native task ingestion (replacing n8n trigger)

### Not Yet Built
- **Event batching** — coordinator and consolidator need time-windowed event accumulation (~1 min)
- **Central input_requests store** — persistence layer for user input requests with external location pointers
- **Consolidator** — background routine that digests session logs into shared memory and produces reflections
- **Self-improvement loop** — consolidator produces reflections → coordinator creates plans → staging validates → deploy
- **Skill testing / staging** — ephemeral environment to validate changes before promoting to production config
- **Memory / knowledge layer** — `~/.cambium/knowledge/` directory exists but no framework integration
- **Configuration hot-reload** — changes to routines/adapters/skills require server restart
- **Dead-letter queue** — messages that fail 3x are marked `failed` with no alerting or recovery path
- **Metrics / observability** — no built-in execution time, success rate, or queue depth tracking
- **Non-streaming session mode** — API returns 501 for `stream=False`

## Future: Self-Improvement Loop

The long-term vision. Not yet implemented, but the architecture is designed for it.

```mermaid
graph TD
    Executor -->|completions| Reviewer
    Reviewer -->|evaluations| Coordinator

    Executor -->|sessions_completed| Consolidator
    Planner -->|sessions_completed| Consolidator
    Reviewer -->|sessions_completed| Consolidator

    Consolidator -->|reflections| Coordinator
    Coordinator -->|plans| Planner

    Planner -->|tasks| Executor
    Executor -->|completions| Reviewer

    Coordinator -->|"plan (self-improvement)"| Planner
    Planner -->|"task (apply change)"| Executor
    Executor -->|completions| Reviewer

    Reviewer -->|"evaluation (validate change)"| Coordinator
    Coordinator -->|deploy| Production["Deploy to production<br/>(skills, prompts, config)"]
```

The **sleep/wake cycle**:
- **Wake** — the system does work: coordinator routes, planner decomposes, executor builds, reviewer evaluates.
- **Sleep** — the consolidator digests completed session logs, consolidates into shared memory, and produces reflections: "we keep failing at X," "this skill underperforms on Y," "the user corrected Z three times."

The coordinator receives reflections and decides what to do — create a self-driven goal, plan an improvement, or do nothing. Self-driven goals are distinguished from user goals in the database but flow through the same planning and execution pipeline.

**Improvement lifecycle:**
1. Consolidator observes a pattern across sessions → publishes reflection
2. Coordinator creates a plan for the improvement (self-driven goal)
3. Planner decomposes into tasks (e.g., edit a skill, adjust a prompt)
4. Executor applies the change in a staging environment
5. Reviewer validates the change against user values and past behavior
6. If accepted: coordinator deploys to production config
7. If rejected: feedback loops back through the same pipeline
