---
name: user-alignment
description: Human-in-the-loop protocol — request types, user task assignment, and session resume flow. Use when creating requests for user input, assigning tasks to the user, or checking pending user requests.
---

# User Alignment

Cambium uses a structured protocol for requesting user input. There are two mechanisms:

1. **User tasks** — work items with `assigned_to: "user"` for real work the user must do
2. **Session requests** — questions or permission checks from agent sessions to the user

## Which reference to read

Each routine reads **only** its relevant reference file. Do not read files for other stages.

| Your routine | Read this file | What it covers |
|---|---|---|
| **interlocutor** | `references/interlocutor.md` | Presenting and answering pending requests, user task review |
| **coordinator** | `references/coordinator.md` | Monitoring user queue, overload detection, replanning signals |
| **planner** | `references/planner.md` | Assigning tasks to user, creating preference requests |
| **executor** | `references/executor.md` | Permission/information requests, session pause and resume |
