from __future__ import annotations

import json
import re
import time

from .core import STATE_DIR, run_tmux, tmux_option


SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
NON_AGENT_COMMANDS = {
    "",
    "ash",
    "bash",
    "fish",
    "htop",
    "ksh",
    "less",
    "nano",
    "nvim",
    "sh",
    "ssh",
    "tail",
    "tmux",
    "top",
    "vi",
    "vim",
    "yazi",
    "zsh",
}
SHELL_COMMANDS = {
    "ash",
    "bash",
    "fish",
    "ksh",
    "sh",
    "zsh",
}
SCRIPT_RUNNER_COMMANDS = {
    "bun",
    "cargo",
    "deno",
    "go",
    "just",
    "lua",
    "make",
    "node",
    "npm",
    "perl",
    "php",
    "pnpm",
    "pytest",
    "python",
    "ruby",
    "uv",
    "yarn",
}
SCRIPT_STATE_APP = "script"
DEFAULT_BADGES: dict[str, str] = {
    "running": "⏳",
    "needs-input": "❓",
    "done": "✅",
    "done-unread": "✓",
    "error": "❌",
}
BADGE_OPTIONS: dict[str, str] = {
    "running": "@tmux_sidebar_badge_running",
    "needs-input": "@tmux_sidebar_badge_needs_input",
    "done": "@tmux_sidebar_badge_done",
    "done-unread": "@tmux_sidebar_badge_done_unread",
    "error": "@tmux_sidebar_badge_error",
}

_badge_cache: dict[str, str] | None = None
_SHELL_PROMPT_RE = re.compile(
    r"^(?:\([^)]*\)\s*)?(?:(?:[A-Za-z0-9._-]+@)?[A-Za-z0-9._~/-]+\s+)?[%#$]\s*$"
)
_PYTHON_REPL_PROMPT_RE = re.compile(r"^(>>>|\.\.\.)\s*$")
_IPYTHON_REPL_PROMPT_RE = re.compile(r"^In \[\d+\]:\s*$")
_NODE_REPL_PROMPT_RE = re.compile(r"^>\s*$")


def configured_badges() -> dict[str, str]:
    global _badge_cache
    if _badge_cache is not None:
        return _badge_cache
    badges = dict(DEFAULT_BADGES)
    for status, option in BADGE_OPTIONS.items():
        custom = tmux_option(option)
        if custom:
            badges[status] = custom
    _badge_cache = badges
    return badges


def badge_for_status(status: str) -> str:
    return configured_badges().get(status, "")


def titlecase_agent_name(command: str, title: str, state: dict | None) -> str:
    live_app = live_agent_app(command, title, state)
    if live_app == "codex":
        return "Codex"
    if live_app == "claude":
        return "Claude"
    return ""


def normalize_token(value: str) -> str:
    token = value.strip().lower()
    if "/" in token:
        token = token.rsplit("/", 1)[-1]
    return token


def _capture_tail_lines(pane_id: str, limit: int = 4) -> list[str]:
    if not pane_id:
        return []
    try:
        capture = run_tmux("capture-pane", "-pt", pane_id)
    except Exception:
        return []
    return [line.rstrip() for line in capture.splitlines() if line.strip()][-limit:]


def _looks_like_shell_prompt(line: str) -> bool:
    stripped = line.strip()
    if stripped in {"$", "%", "#"}:
        return True
    return bool(_SHELL_PROMPT_RE.match(stripped))


def _looks_like_repl_prompt(command: str, line: str) -> bool:
    token = normalize_token(command)
    stripped = line.strip()
    if token.startswith("python") and (_PYTHON_REPL_PROMPT_RE.match(stripped) or _IPYTHON_REPL_PROMPT_RE.match(stripped)):
        return True
    if token == "node" and _NODE_REPL_PROMPT_RE.match(stripped):
        return True
    return False


def looks_like_script_runner(command: str) -> bool:
    token = normalize_token(command)
    if token in SCRIPT_RUNNER_COMMANDS:
        return True
    if token.startswith("python") and re.match(r"^python\d+(?:\.\d+)*$", token):
        return True
    return False


def infer_script_runtime_status(pane_id: str, command: str, active: bool, state: dict | None) -> str:
    token = normalize_token(command)
    existing_app = str((state or {}).get("app", "")).strip().lower()
    existing_status = str((state or {}).get("status", "")).strip().lower()
    existing_script_state = existing_app == SCRIPT_STATE_APP and existing_status in ("running", "done", "done-unread")

    if existing_app in ("claude", "codex") or looks_like_codex(command) or looks_like_claude(command):
        return ""

    if looks_like_script_runner(command):
        if token in SHELL_COMMANDS:
            tail_lines = _capture_tail_lines(pane_id)
            if tail_lines and any(_looks_like_shell_prompt(line) for line in tail_lines[-2:]):
                if existing_status == "running":
                    return "done" if active else "done-unread"
                return existing_status if existing_script_state else ""
            return "running"
        tail_lines = _capture_tail_lines(pane_id)
        if tail_lines and any(_looks_like_repl_prompt(command, line) for line in tail_lines[-2:]):
            if existing_status == "running":
                return "done" if active else "done-unread"
            return existing_status if existing_script_state else ""
        return "running"

    if existing_status == "running":
        return "done" if active else "done-unread"
    if existing_script_state:
        return existing_status
    return ""


def sync_inferred_script_states(sessions: dict, pane_states: dict[str, dict]) -> dict[str, dict]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    updated_states = dict(pane_states)
    for session in sessions.values():
        for window in session["windows"].values():
            for pane in window["panes"]:
                pane_state = updated_states.get(pane["id"], {})
                inferred_status = infer_script_runtime_status(pane["id"], pane["label"], pane["active"], pane_state)
                if not inferred_status:
                    continue
                message = str(pane_state.get("message", "")).strip() or pane["label"]
                if (
                    str(pane_state.get("app", "")).strip().lower() == SCRIPT_STATE_APP
                    and str(pane_state.get("status", "")).strip().lower() == inferred_status
                    and str(pane_state.get("pane_current_command", "")).strip() == pane["label"]
                    and str(pane_state.get("pane_title", "")).strip() == pane["title"]
                ):
                    continue
                next_state = {
                    "pane_id": pane["id"],
                    "session_name": pane["session"],
                    "window_id": pane["window"],
                    "window_name": window["name"],
                    "pane_title": pane["title"],
                    "pane_current_command": pane["label"],
                    "app": SCRIPT_STATE_APP,
                    "status": inferred_status,
                    "message": message,
                    "updated_at": int(time.time()),
                }
                state_path = STATE_DIR / f"pane-{pane['id']}.json"
                tmp_path = state_path.with_suffix(".tmp")
                try:
                    tmp_path.write_text(json.dumps(next_state, separators=(",", ":")) + "\n")
                    tmp_path.rename(state_path)
                except OSError:
                    continue
                updated_states[pane["id"]] = next_state
    return updated_states


def looks_like_codex(value: str) -> bool:
    return normalize_token(value).startswith("codex")


def looks_like_claude(value: str) -> bool:
    token = normalize_token(value)
    if token == "claude" or token.startswith("claude-") or token.startswith("claude_"):
        return True
    return bool(re.search(r"\bclaude\b", value, re.IGNORECASE))


def looks_like_semver(value: str) -> bool:
    return bool(SEMVER_PATTERN.match(normalize_token(value)))


def should_preserve_live_label(command: str, title: str) -> bool:
    command_token = normalize_token(command)
    title_token = normalize_token(title)
    return command_token in NON_AGENT_COMMANDS or title_token in NON_AGENT_COMMANDS


def state_agent_app(command: str, title: str, state: dict | None) -> str:
    app = str((state or {}).get("app", "")).strip().lower()
    status = str((state or {}).get("status", "")).strip().lower()
    if app not in ("claude", "codex"):
        return ""
    if should_preserve_live_label(command, title):
        return ""
    if app == "claude" and (looks_like_semver(command) or looks_like_semver(title)):
        return "claude"
    if status and status != "idle":
        return app
    return ""


def claude_title_status(title: str) -> str:
    match = re.search(r":\s*([a-z_-]+)\s*$", title.strip().lower())
    if match:
        suffix = match.group(1)
        return {
            "done": "done",
            "error": "error",
            "needs-input": "needs-input",
            "running": "running",
        }.get(suffix, "")
    if re.match(r"^[\u2800-\u28FF]", title.strip()):
        return "running"
    return ""


def live_agent_app(command: str, title: str, state: dict | None) -> str:
    if looks_like_codex(command) or looks_like_codex(title):
        return "codex"
    if looks_like_claude(command) or looks_like_claude(title):
        return "claude"
    if looks_like_semver(command) and not should_preserve_live_label(command, title):
        return "claude"
    return state_agent_app(command, title, state)


def codex_terminal_status(pane_id: str) -> str:
    if not pane_id:
        return ""
    try:
        capture = run_tmux("capture-pane", "-pt", pane_id)
    except Exception:
        return ""
    if re.search(r"^\s*[•·]\s+Working \([^)]*esc to interrupt\)\s*$", capture, re.MULTILINE):
        return "running"
    return ""


def effective_pane_status(pane_id: str, command: str, title: str, state: dict | None) -> str:
    live_app = live_agent_app(command, title, state)
    if not live_app:
        script_app = str((state or {}).get("app", "")).strip().lower()
        script_status = str((state or {}).get("status", "")).strip().lower()
        if script_app == SCRIPT_STATE_APP and script_status in ("running", "done", "done-unread"):
            return script_status
        return ""

    status = str((state or {}).get("status", "")).strip().lower()
    if live_app == "codex":
        if status in ("running", "needs-input", "error", "done", "done-unread"):
            return status
        terminal_status = codex_terminal_status(pane_id)
        if terminal_status:
            return terminal_status
        return ""

    if status == "idle":
        return ""
    title_status = claude_title_status(title)
    if title_status:
        return title_status
    if status in ("running", "needs-input", "error", "done", "done-unread"):
        return status
    return ""


def pane_display_label(command: str, title: str, state: dict | None) -> str:
    live_app = live_agent_app(command, title, state)
    if live_app:
        return live_app
    return command


def auto_window_name(window_name: str, panes: list[dict]) -> bool:
    if looks_like_semver(window_name) or looks_like_codex(window_name) or looks_like_claude(window_name):
        return True
    active_pane = next((pane for pane in panes if pane["active"]), panes[0] if panes else None)
    if active_pane is None:
        return False
    return normalize_token(window_name) == normalize_token(active_pane["label"])


def window_display_name(window_name: str, panes: list[dict], pane_states: dict[str, dict]) -> str:
    if not auto_window_name(window_name, panes):
        return window_name

    for pane in sorted(panes, key=lambda p: not p["active"]):
        pane_state = pane_states.get(pane["id"], {})
        label = pane_display_label(pane["label"], pane["title"], pane_state)
        if label != pane["label"]:
            return label

    return window_name
