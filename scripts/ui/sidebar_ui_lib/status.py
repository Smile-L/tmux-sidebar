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
_PROMPT_TITLE_RE = re.compile(r"^(?:\([^)]*\)\s*)?[A-Za-z0-9._-]+@[A-Za-z0-9._-]+:.*$")
_PYTHON_REPL_PROMPT_RE = re.compile(r"^(>>>|\.\.\.)\s*$")
_IPYTHON_REPL_PROMPT_RE = re.compile(r"^In \[\d+\]:\s*$")
_NODE_REPL_PROMPT_RE = re.compile(r"^>\s*$")
_CODEX_BANNER_RE = re.compile(r"OpenAI Codex\s+\(v[^)]+\)")
_CODEX_WORKING_RE = re.compile(r"^\s*[•·]\s+Working \([^)]*esc to interrupt\).*$", re.MULTILINE)
_CODEX_APPROVAL_RE = re.compile(
    r"Would you like to run the following command\?|Press enter to confirm or esc to cancel",
    re.IGNORECASE,
)
_CODEX_APPROVAL_MENU_RE = re.compile(r"^\s*[❯>]?\s*[0-9]+\.\s+", re.MULTILINE)
_CODEX_PROMPT_RE = re.compile(r"^\s*›\s+.+$")
_CODEX_STATUS_LINE_RE = re.compile(r"gpt-[^·]+·")
_CLAUDE_APPROVAL_RE = re.compile(
    r"This command requires approval|Do you want to proceed\?",
    re.IGNORECASE,
)
_CLAUDE_APPROVAL_MENU_RE = re.compile(r"^\s*[❯>]?\s*[0-9]+\.\s+", re.MULTILINE)
INFERRED_CODEX_RUNNING_HOLD_SECONDS = 5
INFERRED_CODEX_NEEDS_INPUT_HOLD_SECONDS = 10


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


def _resolved_live_app(command: str, title: str, state: dict | None, pane_id: str = "") -> str:
    live_app = live_agent_app(command, title, state)
    if live_app != "codex" and pane_id and codex_terminal_signature(pane_id):
        return "codex"
    return live_app


def titlecase_agent_name(command: str, title: str, state: dict | None, pane_id: str = "") -> str:
    live_app = _resolved_live_app(command, title, state, pane_id)
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


def _capture_pane_text(pane_id: str) -> str:
    if not pane_id:
        return ""
    try:
        return run_tmux("capture-pane", "-pt", pane_id)
    except Exception:
        return ""


def _capture_recent_lines(pane_id: str, limit: int = 30) -> list[str]:
    capture = _capture_pane_text(pane_id)
    if not capture:
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


def codex_terminal_signature(pane_id: str) -> bool:
    recent_lines = _capture_recent_lines(pane_id, limit=30)
    if not recent_lines:
        return False
    recent = "\n".join(recent_lines)
    if _CODEX_BANNER_RE.search(recent) or _CODEX_APPROVAL_RE.search(recent) or _CODEX_WORKING_RE.search(recent):
        return True
    tail = [line.strip() for line in recent_lines[-20:]]
    if not tail:
        return False
    has_prompt = any(line.startswith("›") for line in tail)
    has_status_line = any("gpt-" in line and "·" in line for line in tail)
    return has_prompt and has_status_line


def infer_script_runtime_status(pane_id: str, command: str, title: str, active: bool, state: dict | None) -> str:
    token = normalize_token(command)
    if title.strip() == "Sidebar":
        return ""
    existing_app = str((state or {}).get("app", "")).strip().lower()
    existing_status = str((state or {}).get("status", "")).strip().lower()
    existing_script_state = existing_app == SCRIPT_STATE_APP and existing_status in ("running", "done", "done-unread")

    if (
        existing_app in ("claude", "codex")
        or looks_like_codex(command)
        or looks_like_claude(command)
        or codex_terminal_signature(pane_id)
    ):
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
    now = int(time.time())
    for session in sessions.values():
        for window in session["windows"].values():
            for pane in window["panes"]:
                pane_state = updated_states.get(pane["id"], {})
                inferred_status = infer_script_runtime_status(
                    pane["id"], pane["label"], pane["title"], pane["active"], pane_state
                )
                if not inferred_status:
                    if str(pane_state.get("app", "")).strip().lower() == SCRIPT_STATE_APP:
                        state_path = STATE_DIR / f"pane-{pane['id']}.json"
                        try:
                            state_path.unlink()
                        except FileNotFoundError:
                            pass
                        except OSError:
                            pass
                        updated_states.pop(pane["id"], None)
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
    for session in sessions.values():
        for window in session["windows"].values():
            for pane in window["panes"]:
                pane_state = updated_states.get(pane["id"], {})
                live_app = _resolved_live_app(pane["label"], pane["title"], pane_state, pane["id"])
                existing_app = str((pane_state or {}).get("app", "")).strip().lower()
                existing_status = str((pane_state or {}).get("status", "")).strip().lower()
                inferred = bool((pane_state or {}).get("inferred"))
                state_path = STATE_DIR / f"pane-{pane['id']}.json"
                authoritative_codex_state = existing_app == "codex" and existing_status and not inferred

                if live_app != "codex":
                    if inferred and existing_app == "codex":
                        try:
                            state_path.unlink()
                        except FileNotFoundError:
                            pass
                        except OSError:
                            pass
                        updated_states.pop(pane["id"], None)
                    continue

                # App-server and notify writers both emit concrete Codex state files.
                # Once one exists, only fall back to terminal inference for panes with
                # no authoritative external state.
                if authoritative_codex_state:
                    continue

                terminal_status = codex_terminal_status(pane["id"])
                if terminal_status:
                    next_state = {
                        "pane_id": pane["id"],
                        "session_name": pane["session"],
                        "window_id": pane["window"],
                        "window_name": window["name"],
                        "pane_title": pane["title"],
                        "pane_current_command": pane["label"],
                        "app": "codex",
                        "status": terminal_status,
                        "message": str(pane_state.get("message", "")).strip(),
                        "updated_at": now,
                        "inferred": True,
                    }
                    tmp_path = state_path.with_suffix(".tmp")
                    try:
                        tmp_path.write_text(json.dumps(next_state, separators=(",", ":")) + "\n")
                        tmp_path.rename(state_path)
                    except OSError:
                        continue
                    updated_states[pane["id"]] = next_state
                    continue

                if codex_terminal_completed_recently(pane["id"]):
                    completed_status = "done-unread"
                    next_state = {
                        "pane_id": pane["id"],
                        "session_name": pane["session"],
                        "window_id": pane["window"],
                        "window_name": window["name"],
                        "pane_title": pane["title"],
                        "pane_current_command": pane["label"],
                        "app": "codex",
                        "status": completed_status,
                        "message": str(pane_state.get("message", "")).strip(),
                        "updated_at": now,
                        "inferred": True,
                    }
                    tmp_path = state_path.with_suffix(".tmp")
                    try:
                        tmp_path.write_text(json.dumps(next_state, separators=(",", ":")) + "\n")
                        tmp_path.rename(state_path)
                    except OSError:
                        continue
                    updated_states[pane["id"]] = next_state
                    continue

                if inferred and existing_app == "codex":
                    if codex_terminal_idle(pane["id"]):
                        if existing_status in ("running", "needs-input"):
                            completed_status = "done-unread"
                            next_state = {
                                "pane_id": pane["id"],
                                "session_name": pane["session"],
                                "window_id": pane["window"],
                                "window_name": window["name"],
                                "pane_title": pane["title"],
                                "pane_current_command": pane["label"],
                                "app": "codex",
                                "status": completed_status,
                                "message": str(pane_state.get("message", "")).strip(),
                                "updated_at": now,
                                "inferred": True,
                            }
                            tmp_path = state_path.with_suffix(".tmp")
                            try:
                                tmp_path.write_text(json.dumps(next_state, separators=(",", ":")) + "\n")
                                tmp_path.rename(state_path)
                            except OSError:
                                continue
                            updated_states[pane["id"]] = next_state
                            continue
                        continue
                    updated_at = int((pane_state or {}).get("updated_at", 0) or 0)
                    hold_seconds = 0
                    if existing_status == "running":
                        hold_seconds = INFERRED_CODEX_RUNNING_HOLD_SECONDS
                    elif existing_status == "needs-input":
                        hold_seconds = INFERRED_CODEX_NEEDS_INPUT_HOLD_SECONDS
                    if hold_seconds and now - updated_at <= hold_seconds:
                        continue
                    try:
                        state_path.unlink()
                    except FileNotFoundError:
                        pass
                    except OSError:
                        pass
                    updated_states.pop(pane["id"], None)
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


def _path_leaf(path: str) -> str:
    raw = str(path).strip()
    if not raw:
        return ""
    trimmed = raw.rstrip("/\\")
    if not trimmed:
        return ""
    parts = re.split(r"[\\/]+", trimmed)
    return parts[-1] if parts else trimmed


def _path_tail(path: str, parts: int = 2) -> str:
    raw = str(path).strip()
    if not raw:
        return ""
    trimmed = raw.rstrip("/\\")
    if not trimmed:
        return ""
    segments = [segment for segment in re.split(r"[\\/]+", trimmed) if segment]
    if not segments:
        return ""
    if parts <= 1 or len(segments) <= parts:
        return "/".join(segments[-parts:])
    return "/".join(segments[-parts:])


def _looks_like_generic_title(value: str) -> bool:
    token = normalize_token(value)
    if not token:
        return False
    return bool(re.match(r"^v\d+(?:[._-]\d+)*$", token))


def _meaningful_label(candidate: str, command: str) -> str:
    value = str(candidate).strip()
    if not value:
        return ""
    token = normalize_token(value)
    if not token or token == normalize_token(command):
        return ""
    if token in NON_AGENT_COMMANDS or looks_like_semver(value):
        return ""
    if _PROMPT_TITLE_RE.match(value):
        return ""
    return value


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
    recent_lines = _capture_recent_lines(pane_id, limit=20)
    if not recent_lines:
        return ""
    recent = "\n".join(recent_lines)
    if _CODEX_APPROVAL_MENU_RE.search(recent):
        return "needs-input"
    if _CODEX_APPROVAL_RE.search(recent):
        return "needs-input"
    if _CODEX_WORKING_RE.search(recent):
        return "running"
    if any(_CODEX_PROMPT_RE.match(line.strip()) for line in recent_lines[-3:]):
        return ""
    return ""


def claude_terminal_status(pane_id: str) -> str:
    recent_lines = _capture_recent_lines(pane_id, limit=20)
    if not recent_lines:
        return ""
    recent = "\n".join(recent_lines)
    if _CLAUDE_APPROVAL_MENU_RE.search(recent):
        return "needs-input"
    if _CLAUDE_APPROVAL_RE.search(recent):
        return "needs-input"
    return ""


def codex_terminal_idle(pane_id: str) -> bool:
    recent_lines = _capture_recent_lines(pane_id, limit=20)
    if not recent_lines:
        return False
    if codex_terminal_status(pane_id):
        return False
    tail = [line.strip() for line in recent_lines[-5:]]
    has_prompt = any(_CODEX_PROMPT_RE.match(line) for line in tail)
    has_status_line = any("gpt-" in line and "·" in line for line in recent_lines[-8:])
    return has_prompt and has_status_line


def codex_terminal_completed_recently(pane_id: str) -> bool:
    recent_lines = [line.strip() for line in _capture_recent_lines(pane_id, limit=40)]
    if not recent_lines or not codex_terminal_idle(pane_id):
        return False
    prompt_indices = [index for index, line in enumerate(recent_lines) if _CODEX_PROMPT_RE.match(line)]
    if not prompt_indices:
        return False
    last_prompt_index = prompt_indices[-1]
    window = recent_lines[max(0, last_prompt_index - 28):last_prompt_index]
    if not window:
        return False
    for line in reversed(window):
        if not line:
            continue
        if _CODEX_WORKING_RE.match(line):
            return False
        if _CODEX_APPROVAL_RE.search(line):
            return False
        if _CODEX_BANNER_RE.search(line):
            continue
        if _CODEX_STATUS_LINE_RE.search(line):
            continue
        if line == "/status":
            continue
        if line.startswith(("│", "╭", "╰", "─")):
            continue
        if re.match(r"^(Model|Directory|Permissions|Agents\.md|Account|Collaboration mode|Session|Context window|5h limit|Weekly limit|Visit https?://)", line):
            continue
        if _CODEX_PROMPT_RE.match(line):
            continue
        if line.startswith(("• ", "- ", "■ ", "⚠ ")):
            return True
        if re.search(r"[\u4e00-\u9fffA-Za-z]", line):
            return True
    return False


def effective_pane_status(pane_id: str, command: str, title: str, state: dict | None) -> str:
    if title.strip() == "Sidebar":
        return ""
    live_app = live_agent_app(command, title, state)
    if live_app != "codex" and codex_terminal_signature(pane_id):
        live_app = "codex"
    if not live_app:
        script_app = str((state or {}).get("app", "")).strip().lower()
        script_status = str((state or {}).get("status", "")).strip().lower()
        if script_app == SCRIPT_STATE_APP and script_status in ("running", "done", "done-unread"):
            return script_status
        return ""

    status = str((state or {}).get("status", "")).strip().lower()
    if live_app == "codex":
        if bool((state or {}).get("inferred")) and codex_terminal_idle(pane_id) and status in ("running", "needs-input"):
            return "done-unread"
        if status in ("running", "needs-input", "error", "done", "done-unread"):
            if status == "done":
                return "done-unread"
            return status
        terminal_status = codex_terminal_status(pane_id)
        if terminal_status:
            return terminal_status
        return ""

    if status == "idle":
        status = ""
    title_status = claude_title_status(title)
    if title_status:
        return title_status
    terminal_status = claude_terminal_status(pane_id)
    if terminal_status:
        return terminal_status
    if status in ("running", "needs-input", "error", "done", "done-unread"):
        return status
    return ""


def pane_display_label(command: str, title: str, state: dict | None, path: str = "", window_name: str = "", pane_id: str = "") -> str:
    live_app = _resolved_live_app(command, title, state, pane_id)
    path_label = _path_tail(path, parts=2)
    if live_app and path_label:
        return path_label
    if live_app:
        return live_app
    contextual_title = _meaningful_label(title, command)
    if _looks_like_generic_title(contextual_title):
        contextual_title = ""
    if path_label and normalize_token(command) in SHELL_COMMANDS:
        return path_label
    if path_label and looks_like_script_runner(command):
        return path_label
    if contextual_title:
        return contextual_title
    if looks_like_script_runner(command) or looks_like_semver(command):
        contextual_window_name = _meaningful_label(window_name, command)
        if contextual_window_name:
            return contextual_window_name
        if path_label:
            return path_label
    if path_label and _looks_like_generic_title(title):
        return path_label
    return command


def auto_window_name(window_name: str, panes: list[dict]) -> bool:
    if (
        looks_like_semver(window_name)
        or looks_like_codex(window_name)
        or looks_like_claude(window_name)
        or looks_like_script_runner(window_name)
        or normalize_token(window_name) in SHELL_COMMANDS
    ):
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
        label = pane_display_label(pane["label"], pane["title"], pane_state, pane.get("path", ""), window_name, pane["id"])
        if label != pane["label"]:
            return label

    return window_name
