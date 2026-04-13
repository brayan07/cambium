# Phase 1 Implementation Plan: Foundation + Terminal Chat

> Reference: `docs/ui-design.md` — Phase 1 section
> Branch: `ui-frontend` (worktree at `/Users/bjaramillo/PycharmProjects/cambium-ui`)

## Overview

Phase 1 delivers the foundational infrastructure and the Chat page — the most
complex and distinctive piece of the UI. At the end of this phase, a user can:

1. Open the Cambium UI in a browser
2. See a sidebar with navigation (Chat active, other sections placeholder)
3. View a list of sessions (active, completed, paused)
4. Start a new interlocutor chat → full Claude Code CLI in the browser
5. Observe a running system session → lightweight live transcript

---

## Aesthetic Direction

Cambium is a personal empowerment engine rooted in Stoic philosophy — named after
Marcus Aurelius. The UI should feel like a **refined command center**: calm,
intentional, information-dense without clutter. Not flashy, not playful — authoritative
and focused.

**Tone:** Editorial/utilitarian hybrid. Think: a well-designed terminal dashboard
meets a high-end news reader. The terminal IS the centerpiece — the chrome around
it should complement, not compete.

**Typography:**
- Display/headings: **JetBrains Mono** — distinctive monospace that bridges the
  terminal aesthetic to the surrounding UI. Characterful without being distracting.
- Body/labels: **IBM Plex Sans** — clean, slightly technical, excellent readability
  at small sizes. Pairs well with monospace without defaulting to Inter/Roboto.
- Both available via Google Fonts CDN.

**Color:**
- Dark theme by default (the terminal is dark — surrounding chrome should match).
- Base: near-black (`#0a0a0f`) with subtle blue-gray tints for depth.
- Surface: dark gray (`#14141f`) for cards and panels.
- Border: subtle (`#1e1e2e`) — separation through shade, not lines.
- Text: off-white (`#e0e0e8`) for body, bright white for emphasis.
- Accent: a single warm amber (`#d4a843`) — evokes parchment/gold, ties to the
  Stoic/classical theme. Used sparingly: active nav item, badges, focus rings.
- Status colors: green (active), amber (paused/pending), red (failed), blue (info).
- CSS variables for everything — theme-able from day one.

**Layout:**
- Narrow left sidebar (icon + label, collapsible to icon-only).
- Main content area fills remaining width.
- Chat page splits: session list (fixed-width left panel) + terminal/observation (flex).
- No rounded corners on the terminal. Subtle rounding (2-4px) on UI chrome.
- Generous use of the amber accent as a thin top-border on active elements.

**Motion:**
- Minimal. Sidebar collapse/expand is the main animation (150ms ease).
- Session list items: subtle fade-in on load (staggered 30ms).
- Terminal appearance: no animation — instant. Terminals should feel fast.
- Status badge pulse for active sessions (subtle opacity oscillation).

---

## Implementation Steps

### Step 1: Frontend Scaffold

**Goal:** Vite + React + TypeScript + Tailwind project inside `ui/` directory.

**Files to create:**

```
ui/
├── index.html
├── package.json
├── tsconfig.json
├── tsconfig.node.json
├── vite.config.ts
├── tailwind.config.ts
├── postcss.config.js           # Tailwind v4 may not need this
├── src/
│   ├── main.tsx                # React entry point
│   ├── App.tsx                 # Router + providers
│   ├── index.css               # Tailwind directives + CSS variables + font imports
│   └── vite-env.d.ts           # Vite type declarations
└── public/
    └── (empty for now)
```

**package.json dependencies:**

```json
{
  "dependencies": {
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "react-router": "^7.1.0",
    "@tanstack/react-query": "^5.90.0"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.0.0",
    "vite": "^6.1.0",
    "typescript": "^5.7.0",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "tailwindcss": "^4.0.0",
    "@tailwindcss/vite": "^4.0.0"
  }
}
```

**vite.config.ts:**

```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8350",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
      "/api/terminal": {
        target: "ws://127.0.0.1:8350",
        ws: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
```

Note: The proxy rewrites `/api/sessions` → `/sessions` etc. This means the UI
always uses `/api/` prefixed paths, and in production the FastAPI app mounts its
existing routes under `/api/` (or a reverse proxy does the rewrite). This avoids
changing any existing endpoint paths.

**CSS variables (index.css):**

```css
@import "tailwindcss";
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;500;700&display=swap');

@theme {
  --color-base: #0a0a0f;
  --color-surface: #14141f;
  --color-border: #1e1e2e;
  --color-text: #e0e0e8;
  --color-text-muted: #8888a0;
  --color-accent: #d4a843;
  --color-accent-dim: #d4a84333;

  --color-status-active: #4ade80;
  --color-status-paused: #d4a843;
  --color-status-failed: #ef4444;
  --color-status-info: #60a5fa;

  --font-display: "JetBrains Mono", monospace;
  --font-body: "IBM Plex Sans", sans-serif;
}
```

**Validation:** `cd ui && npm install && npm run dev` serves on :5173.

---

### Step 2: Layout Shell + Routing

**Goal:** Sidebar navigation, page routing, responsive collapse.

**Files to create:**

```
ui/src/
├── components/
│   ├── Layout.tsx              # Sidebar + Outlet wrapper
│   └── Sidebar.tsx             # Nav items with icons + labels
├── pages/
│   ├── ChatPage.tsx            # Phase 1 focus
│   ├── InboxPage.tsx           # Placeholder
│   ├── WorkPage.tsx            # Placeholder
│   ├── DashboardPage.tsx       # Placeholder
│   ├── MindPage.tsx            # Placeholder
│   └── ConfigPage.tsx          # Placeholder
└── lib/
    └── api.ts                  # Base fetch wrapper with /api prefix
```

**App.tsx routing:**

```tsx
<BrowserRouter>
  <QueryClientProvider client={queryClient}>
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Navigate to="/chat" />} />
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/inbox" element={<InboxPage />} />
        <Route path="/work" element={<WorkPage />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/mind/*" element={<MindPage />} />
        <Route path="/config" element={<ConfigPage />} />
      </Route>
    </Routes>
  </QueryClientProvider>
</BrowserRouter>
```

**Sidebar:**
- 6 nav items: Chat, Inbox, Work, Dashboard, Mind, Config
- Icons: Lucide React (`MessageSquare`, `Inbox`, `ListTree`, `LayoutDashboard`,
  `Brain`, `Settings`)
- Active item: amber left border + amber text
- Collapse toggle at bottom: shrinks to icon-only (48px width → full 200px)
- Sidebar state: `localStorage` persisted via simple React state

**Placeholder pages:** Just a centered heading with the page name. These get
built in later phases.

**Validation:** Navigate between all 6 routes. Sidebar highlights correctly.
Collapse/expand works. Layout is responsive (sidebar overlays on narrow viewports).

---

### Step 3: Session List Component

**Goal:** Left panel in Chat page showing sessions grouped by state.

**Files to create:**

```
ui/src/
├── hooks/
│   └── useSessions.ts          # React Query hook for GET /api/sessions
├── components/
│   ├── SessionList.tsx          # Grouped list with status badges
│   └── StatusBadge.tsx          # Reusable status pill component
└── lib/
    └── types.ts                 # TypeScript types matching API responses
```

**types.ts** — mirrors the Pydantic response models:

```typescript
interface Session {
  id: string;
  origin: "system" | "user";
  status: "created" | "active" | "completed" | "failed";
  routine_name: string | null;
  adapter_instance_name: string | null;
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
}

interface Request {
  id: string;
  session_id: string;
  type: "permission" | "information" | "preference";
  status: "pending" | "answered" | "expired" | "rejected";
  summary: string;
  // ... (full type in types.ts)
}
```

**useSessions hook:**

```typescript
function useSessions(filters?: { status?: string; origin?: string; limit?: number }) {
  return useQuery({
    queryKey: ["sessions", filters],
    queryFn: () => api.get("/api/sessions", { params: filters }),
    staleTime: 5_000,  // 5s for active session list
  });
}
```

**SessionList groups:**
1. **Active Sessions** — `status=active`, sorted by `updated_at` desc
2. **Paused** — sessions with pending requests (join sessions + requests data)
3. **Your Conversations** — `origin=user`, recent, sorted by `updated_at` desc
4. **Completed** — recent completed sessions (collapsible, default collapsed)

Each item shows: routine name, first line of metadata or work item title, status
badge, relative time.

**"+ New Chat" button** at the bottom of the list. Wired up in Step 5.

**Validation:** With the Cambium server running, the session list populates.
Status badges render correctly. Groups display in correct order. Empty states
show appropriate messages ("No active sessions").

---

### Step 4: WebSocket PTY Bridge (Backend)

**Goal:** FastAPI WebSocket endpoint that spawns a PTY and bridges it to the browser.

This is the most significant new backend piece. It requires adding a Python
dependency (`ptyprocess`) and a new router module.

**Files to create/modify:**

```
src/cambium/server/terminal.py      # NEW — WebSocket PTY bridge
src/cambium/server/app.py           # MODIFY — include terminal router, add static files
pyproject.toml                      # MODIFY — add ptyprocess + websockets dependencies
```

**Python dependency:**

```
uv pip install --python .venv/bin/python ptyprocess
```

Add `ptyprocess` and `websockets` to `pyproject.toml` dependencies.

**terminal.py — WebSocket PTY bridge:**

```python
"""WebSocket ↔ PTY bridge for terminal sessions."""

import asyncio
import logging
import os
import pty
import signal
import struct
import subprocess
import fcntl
import termios
from dataclasses import dataclass, field
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

log = logging.getLogger(__name__)

router = APIRouter(prefix="/terminal", tags=["terminal"])

# --- PTY process management ---

@dataclass
class PtySession:
    session_id: str
    pid: int
    fd: int                         # PTY master file descriptor
    last_input: float               # Timestamp of last user input
    websocket: Optional[WebSocket] = None

    def resize(self, rows: int, cols: int) -> None:
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, winsize)

    def kill(self) -> None:
        try:
            os.kill(self.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass


# Active PTY sessions: session_id → PtySession
_pty_sessions: dict[str, PtySession] = {}
IDLE_TIMEOUT = 15 * 60  # 15 minutes


@router.websocket("/new")
async def terminal_new(
    ws: WebSocket,
    routine: str = Query(default="interlocutor"),
):
    """Create a new session and open a terminal."""
    await ws.accept()

    # Spawn PTY running `cambium chat <routine>`
    session = _spawn_pty(routine=routine)
    session.websocket = ws
    _pty_sessions[session.session_id] = session

    try:
        await _bridge(ws, session)
    finally:
        _cleanup(session)


@router.websocket("/{session_id}")
async def terminal_attach(
    ws: WebSocket,
    session_id: str,
):
    """Attach to an existing session (reopen with --resume)."""
    await ws.accept()

    # If a PTY already exists for this session, reattach
    existing = _pty_sessions.get(session_id)
    if existing and existing.websocket is None:
        existing.websocket = ws
        try:
            await _bridge(ws, existing)
        finally:
            existing.websocket = None
        return

    # Otherwise, spawn a new PTY with --resume
    session = _spawn_pty(session_id=session_id, resume=True)
    session.websocket = ws
    _pty_sessions[session.session_id] = session

    try:
        await _bridge(ws, session)
    finally:
        _cleanup(session)


def _spawn_pty(
    routine: str = "interlocutor",
    session_id: str | None = None,
    resume: bool = False,
) -> PtySession:
    """Fork a PTY running the cambium chat command."""
    import uuid, time

    if session_id is None:
        session_id = str(uuid.uuid4())

    cmd = ["cambium", "chat", routine]
    if resume:
        cmd.extend(["--resume", session_id])
    else:
        cmd.extend(["--session", session_id])

    pid, fd = pty.fork()
    if pid == 0:
        # Child — exec into cambium chat
        os.execvp(cmd[0], cmd)
    else:
        # Parent — non-blocking reads
        os.set_blocking(fd, False)
        return PtySession(
            session_id=session_id,
            pid=pid,
            fd=fd,
            last_input=time.time(),
        )


async def _bridge(ws: WebSocket, session: PtySession) -> None:
    """Bidirectional bridge between WebSocket and PTY."""
    import time

    loop = asyncio.get_event_loop()

    async def read_pty():
        """Read PTY output → send to WebSocket."""
        while True:
            try:
                data = await loop.run_in_executor(
                    None, lambda: os.read(session.fd, 4096)
                )
                if not data:
                    break
                await ws.send_bytes(data)
            except OSError:
                break

    async def write_pty():
        """Read WebSocket input → write to PTY."""
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if "bytes" in msg:
                data = msg["bytes"]
            elif "text" in msg:
                text = msg["text"]
                # Handle resize events (JSON: {"type":"resize","rows":N,"cols":N})
                if text.startswith("{"):
                    import json
                    try:
                        event = json.loads(text)
                        if event.get("type") == "resize":
                            session.resize(event["rows"], event["cols"])
                            continue
                    except json.JSONDecodeError:
                        pass
                data = text.encode()
            else:
                continue
            os.write(session.fd, data)
            session.last_input = time.time()

    async def idle_watchdog():
        """Kill PTY after 15 minutes of no input."""
        while True:
            await asyncio.sleep(60)
            if time.time() - session.last_input > IDLE_TIMEOUT:
                log.info(f"PTY idle timeout: {session.session_id}")
                session.kill()
                break

    # Run all three concurrently; any exit stops all
    done, pending = await asyncio.wait(
        [
            asyncio.create_task(read_pty()),
            asyncio.create_task(write_pty()),
            asyncio.create_task(idle_watchdog()),
        ],
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()


def _cleanup(session: PtySession) -> None:
    """Kill PTY and remove from registry."""
    session.kill()
    _pty_sessions.pop(session.session_id, None)
    log.info(f"PTY cleaned up: {session.session_id}")
```

**app.py modifications:**
1. Import and include the terminal router
2. Add static file mount for `ui/dist/` (production) with HTML fallback
3. Add filesystem access endpoints (static mounts + directory listing)

```python
# In app.py, after existing router includes:
from cambium.server import terminal as terminal_module
app.include_router(terminal_module.router)

# At the bottom, after all API routes — static UI serving for production:
import os
ui_dist = Path(__file__).parent.parent.parent.parent / "ui" / "dist"
if ui_dist.exists():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=str(ui_dist), html=True), name="ui")
```

**Validation:**
1. Start Cambium server with `--live` flag
2. Connect via `websocat ws://127.0.0.1:8350/terminal/new?routine=interlocutor`
3. Verify bidirectional I/O — type input, see Claude Code output
4. Verify idle timeout kills process after 15 minutes
5. Verify resize events propagate

---

### Step 5: xterm.js Terminal Component (Frontend)

**Goal:** React component wrapping xterm.js with WebSocket connection to the PTY bridge.

**New dependencies:**

```json
{
  "@xterm/xterm": "^5.5.0",
  "@xterm/addon-attach": "^0.11.0",
  "@xterm/addon-fit": "^0.10.0",
  "@xterm/addon-web-links": "^0.11.0"
}
```

**Files to create:**

```
ui/src/
├── components/
│   └── Terminal.tsx             # xterm.js wrapper with WebSocket lifecycle
└── hooks/
    └── useTerminal.ts           # WebSocket connection + xterm.js setup
```

**Terminal.tsx:**

Core responsibilities:
- Mount xterm.js instance into a div ref
- Open WebSocket to `/api/terminal/new?routine=X` or `/api/terminal/{session_id}`
- Attach WebSocket to xterm via `AttachAddon`
- Fit terminal to container via `FitAddon` (+ ResizeObserver)
- Send resize events as JSON `{"type":"resize","rows":N,"cols":N}` on fit
- Handle WebSocket close/error states
- Clean up on unmount

**xterm.js theme** (matches the CSS variables):

```typescript
const theme: ITheme = {
  background: "#0a0a0f",
  foreground: "#e0e0e8",
  cursor: "#d4a843",
  cursorAccent: "#0a0a0f",
  selectionBackground: "#d4a84344",
  black: "#0a0a0f",
  brightBlack: "#1e1e2e",
  // ... full 16-color palette matching the design system
};
```

**Connection states displayed to user:**
- Connecting: subtle amber spinner in terminal area
- Connected: terminal renders immediately
- Disconnected: "Session ended" overlay with option to reconnect or go back
- Error: "Connection failed" with retry button

**Validation:**
1. Start Cambium server with `--live`
2. Open UI → Chat → "+ New Chat"
3. Claude Code CLI renders in browser terminal
4. Type messages, see streaming responses
5. Resize browser window → terminal reflows
6. Close tab → PTY stays alive for 15 min → eventually cleans up

---

### Step 6: Chat Page Assembly

**Goal:** Wire together SessionList + Terminal + ObservationView into the Chat page.

**Files to create/modify:**

```
ui/src/
├── pages/
│   └── ChatPage.tsx            # MODIFY — compose session list + main area
├── components/
│   ├── ObservationView.tsx     # Lightweight SSE transcript
│   └── TranscriptMessage.tsx   # Single message in observation mode
└── hooks/
    └── useSessionStream.ts     # EventSource hook for SSE observation
```

**ChatPage layout:**

```
┌────────────────┬───────────────────────────────────────┐
│  SessionList   │  Terminal / ObservationView / Empty    │
│  (280px fixed) │  (flex-1)                             │
│                │                                       │
│  [+ New Chat]  │                                       │
└────────────────┴───────────────────────────────────────┘
```

**State machine for main area:**

```
No session selected  →  Empty state ("Select a session or start a new chat")
                         ↓ click session
Active + system      →  ObservationView (SSE transcript, "Drop In" button)
Active + user        →  Terminal (WebSocket PTY, interactive)
Completed + user     →  Terminal (WebSocket PTY, --resume)
Paused               →  ObservationView + "Resume" button (for Phase 2)
```

Note: "Drop In" button in ObservationView is visible but disabled in Phase 1.
The cancel-then-resume machinery is Phase 2. For now, clicking it shows a tooltip:
"Drop-in available in a future update."

**ObservationView:**
- Opens `EventSource` to `GET /api/sessions/{id}/stream`
- Renders each `TranscriptEvent.content` as a `TranscriptMessage`
- Auto-scrolls to bottom on new events
- Shows routine name and "observing" badge in header
- Displays "Session completed" when stream ends

**TranscriptMessage:**
- Role-based styling: `assistant` (left-aligned, off-white), `user` (right-aligned,
  amber tint), `system` (centered, muted), `tool` (hidden in observation mode)
- Timestamp on hover
- Content rendered as plain text (no markdown in v1 observation — keep it simple)

**"+ New Chat" button:**
1. Calls terminal WebSocket: `WS /api/terminal/new?routine=interlocutor`
2. Adds the new session to the session list (optimistic update or refetch)
3. Switches main area to Terminal mode

**Session switching:**
- Click a different session in the list
- Previous terminal stays alive (no explicit disconnect — idle timeout handles cleanup)
- New session opens in appropriate mode (terminal or observation)

**Validation:**
1. Full flow: open UI → see session list → click "+ New Chat" → Claude Code terminal
2. Open a second browser tab → start Cambium server with `--live` → trigger a
   system session → observe it refreshing in the session list → click to observe
3. Switch between sessions → terminals persist → idle ones clean up after 15 min
4. Observation view shows live streaming transcript for active system sessions
5. Empty state renders when no session is selected

---

### Step 7: FastAPI Static File Serving + Filesystem Access

**Goal:** Production build serving and read-only filesystem access for future phases.

**Files to modify:**

```
src/cambium/server/app.py       # Static file mount + fs endpoints
```

**Static UI serving (production):**

Already outlined in Step 4. The `StaticFiles` mount with `html=True` serves
`index.html` as fallback for all unmatched routes — enabling client-side routing.

Important: This mount MUST be the last mount in the app, after all API routes,
because it acts as a catch-all.

**Filesystem access endpoints:**

```python
@app.get("/fs/ls")
def list_directory(root: str, path: str = ""):
    """List files in memory or config directory.
    
    root: "memory" or "config"
    path: relative subpath
    """
    # Resolve root to actual directory
    # Return: { entries: [{ name, type, size, modified }] }
    # Path traversal protection: resolve and verify within root
```

Plus static mounts for file content:
```python
app.mount("/memory", StaticFiles(directory=memory_dir), name="memory")
app.mount("/config", StaticFiles(directory=config_dir), name="config")
```

Note: In dev mode, the Vite proxy handles `/api/memory/*` → `/memory/*`.
In production, these mounts coexist with the UI static mount.

**Validation:**
1. `cd ui && npm run build` produces `ui/dist/`
2. Start server without Vite → open `http://localhost:8350` → UI loads
3. Navigate between routes → client-side routing works (no 404)
4. `GET /fs/ls?root=memory&path=knowledge` returns directory listing
5. `GET /memory/knowledge/user/preferences/some-file.md` returns raw content

---

## Dependency Summary

**Python (add to pyproject.toml):**
- `ptyprocess` — PTY management (or use stdlib `pty` module directly)
- `websockets` — already a uvicorn dependency, but ensure it's available

**Node (ui/package.json):**
- `react`, `react-dom` (^19.0.0)
- `react-router` (^7.1.0)
- `@tanstack/react-query` (^5.90.0)
- `@xterm/xterm` (^5.5.0)
- `@xterm/addon-attach` (^0.11.0)
- `@xterm/addon-fit` (^0.10.0)
- `@xterm/addon-web-links` (^0.11.0)
- `lucide-react` (icons)
- `vite`, `@vitejs/plugin-react`, `typescript`, `tailwindcss`, `@tailwindcss/vite` (dev)
- Type packages: `@types/react`, `@types/react-dom`

**No additional system dependencies.** PTY support is native on macOS/Linux.

---

## Order of Operations

```
Step 1: Frontend scaffold          [no backend changes]
Step 2: Layout shell + routing     [no backend changes]
Step 3: Session list component     [no backend changes, needs running server]
Step 4: WebSocket PTY bridge       [backend only]
Step 5: xterm.js terminal          [frontend only, needs Step 4]
Step 6: Chat page assembly         [ties everything together]
Step 7: Static serving + fs access [backend, can parallel with Step 6]
```

Steps 1-3 are frontend-only and can be built against a running Cambium server.
Step 4 is backend-only. Steps 5-6 integrate them. Step 7 is independent and can
be done in parallel with Step 6.

**Estimated total: 7 distinct implementation tasks, each independently testable.**

---

## Testing Strategy

**Manual testing** is primary for Phase 1 — we're building a visual interface.

Checklist:
- [ ] UI loads at `http://localhost:5173` (dev) and `http://localhost:8350` (prod)
- [ ] Sidebar navigation works across all routes
- [ ] Session list populates from live server data
- [ ] New interlocutor chat opens Claude Code in terminal
- [ ] Terminal input/output works bidirectionally
- [ ] Terminal resizes with browser window
- [ ] Active system sessions appear in session list
- [ ] Observation view shows live streaming transcript
- [ ] Session switching works without killing previous terminals
- [ ] Idle terminals clean up after 15 minutes
- [ ] Production build serves correctly from FastAPI
- [ ] Filesystem endpoints return memory/config directory contents

**Automated tests** (minimal for Phase 1):
- `terminal.py`: Unit test for `_spawn_pty` (mock PTY, verify command construction)
- `terminal.py`: Integration test for WebSocket connection lifecycle
- `app.py`: Test that filesystem endpoints resolve paths correctly and reject traversal
