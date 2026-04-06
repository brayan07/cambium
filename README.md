# Cambium

A personal empowerment engine — an async AI agent framework that helps one person live and work according to their values.

Cambium runs AI agents as **routines** connected by a channel-based pub/sub system. Each routine listens on channels, processes messages through an adapter (currently Claude Code), and publishes results to downstream channels. The architecture is designed for a self-improvement loop: skills are hypotheses about how to help the user, and the system can reflect on outcomes, propose improvements, and validate them before deploying.

## Quick Start

```bash
# Install
uv pip install -e .

# Bootstrap user config
cambium init

# Start the server (mock mode for testing)
cambium server

# Start with real Claude Code execution
cambium server --live

# Publish a message
cambium send tasks '{"task_id": "abc", "action": "execute"}'

# Interactive session
cambium chat interactive
```

## Architecture

See [docs/architecture.md](docs/architecture.md) for the full system architecture, including component diagrams, channel topology, data flow, and design decisions.

## Project Structure

```
src/cambium/
├── adapters/          # Runtime execution (Claude Code)
├── cli/               # CLI commands (init)
├── consumer/          # Message polling and dispatch (concurrency + batching)
├── episode/           # Episodic memory index (episodes + channel events)
├── mcp/               # MCP server registry and passthrough
├── memory/            # Long-term memory service (git-backed markdown init)
├── models/            # Core data models (Message, Routine, Skill)
├── preference/        # Preference learning and calibration
├── queue/             # Persistent message queue (SQLite)
├── runner/            # Orchestrator (session + auth + execution + episode logging)
├── server/            # FastAPI app, auth, session/episode/work-item endpoints
├── session/           # Session lifecycle, transcript storage, SSE
├── timer/             # Cron-scheduled heartbeat system
└── work_item/         # Planning and execution backbone

defaults/              # Seed config for cambium init
├── routines/          # 8 default routines
├── adapters/          # Adapter instances, prompts, skills
├── memory/            # Seed content for long-term memory directory
└── timers.yaml        # Cron schedule for heartbeat timers

tests/                 # Test suite (278 tests)
docs/                  # Architecture and design docs
scripts/               # Demo and utility scripts
```

## Configuration

All user state lives in `~/.cambium/`, initialized by `cambium init`. This includes routines, adapter instances, system prompts, skills, MCP server configs, and the SQLite database. The directory is git-backed for versioning.

See [docs/architecture.md#configuration-model](docs/architecture.md#configuration-model) for the full layout.
