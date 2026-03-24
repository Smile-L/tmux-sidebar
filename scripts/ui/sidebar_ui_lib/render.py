from __future__ import annotations

import curses
import json
import os
import re
import shlex
import subprocess
from pathlib import Path

from .core import STATE_DIR, run_tmux, tmux_option
from .tree import find_selected_row_index, truncate_line
from .status import badge_for_status


COLOR_PAIR_SESSION = 1
COLOR_PAIR_WINDOW = 2
COLOR_PAIR_PANE = 3
COLOR_PAIR_SELECTED = 4
COLOR_PAIR_SECTION = 5
COLOR_PAIR_DIVIDER = 6
COLOR_PAIR_MUTED = 7
COLOR_PAIR_PREVIEW = 8
COLOR_PAIR_PILL = 9
COLOR_PAIR_BADGE_RUNNING = 10
COLOR_PAIR_BADGE_NEEDS_INPUT = 11
COLOR_PAIR_BADGE_DONE = 12
COLOR_PAIR_BADGE_DONE_UNREAD = 13
COLOR_PAIR_BADGE_ERROR = 14
COLOR_PAIR_SELECTED_MUTED = 15
COLOR_PAIR_SELECTED_PILL = 16
COLOR_PAIR_SELECTED_BADGE_RUNNING = 17
COLOR_PAIR_SELECTED_BADGE_NEEDS_INPUT = 18
COLOR_PAIR_SELECTED_BADGE_DONE = 19
COLOR_PAIR_SELECTED_BADGE_DONE_UNREAD = 20
COLOR_PAIR_SELECTED_BADGE_ERROR = 21
DEFAULT_COLOR_FG = "d6dfeb"
_HEX_COLOR_RE = re.compile(r"#([0-9a-fA-F]{6})")
_CUBE_VALUES = [0, 95, 135, 175, 215, 255]
_last_row_map_json = ""
_badge_attrs: dict[str, int] = {}
_role_attrs: dict[str, int] = {}
_selected_role_attrs: dict[str, int] = {}
_color_slots: dict[str, int] = {}
_next_color_slot = 16
_PROMPT_RE = re.compile(
    r"^(?:\([^)]*\)\s*)?(?P<user>[A-Za-z0-9._-]+)@(?P<host>[A-Za-z0-9._-]+)\s+(?P<cwd>[^\s]+)\s*[%#$]\s*(?P<cmd>.*)$"
)
_LOW_SIGNAL_PATTERNS = [
    re.compile(r"^now using node v[\w.+-]+", re.IGNORECASE),
    re.compile(r"^(?:base|venv|conda|python3(?:\.\d+)?)$", re.IGNORECASE),
    re.compile(r"^[A-Za-z0-9._-]+$"),
]
_CODEX_WORKING_RE = re.compile(r"^\s*[•·]\s+working \([^)]*esc to interrupt\)\s*$", re.IGNORECASE)
_CLAUDE_STATUS_TITLE_RE = re.compile(r"^[●⠂]\s+.*:\s*(done|error|needs-input|running)\s*$", re.IGNORECASE)


def _scripts_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def _normalize_preview_line(line: str) -> str:
    return " ".join(line.strip().split())


def _extract_prompt_info(line: str) -> tuple[str, str]:
    match = _PROMPT_RE.match(line)
    if not match:
        return "", ""
    cwd = match.group("cwd").strip()
    cmd = match.group("cmd").strip()
    return cwd, cmd


def _panel_type(row: dict) -> str:
    agent_name = str(row.get("agent_name", "")).lower()
    label = str(row.get("label", "")).lower()
    command = str(row.get("pane_command", "")).lower()
    if agent_name == "codex" or label == "codex" or command.startswith("codex"):
        return "codex"
    if agent_name == "claude" or label == "claude" or command.startswith("claude"):
        return "claude"
    if command in {"bash", "zsh", "fish", "sh"} or label in {"bash", "zsh", "fish", "sh"}:
        return "shell"
    return "generic"


def _line_score(line: str, row: dict) -> int:
    score = len(line)
    lowered = line.lower()
    if any(pattern.match(lowered) for pattern in _LOW_SIGNAL_PATTERNS):
        score -= 30
    if line == row.get("pane_command", "") or line == row.get("label", ""):
        score -= 20
    if line == row.get("window_name", ""):
        score -= 10
    if "/" in line or "\\" in line:
        score += 8
    if " " in line:
        score += 6
    if any(token in lowered for token in ("error", "failed", "done", "running", "working", "permission", "approval", "complete")):
        score += 10
    if len(line) < 6:
        score -= 12
    return score


def _captured_candidates(pane_id: str) -> tuple[list[str], str, list[str]]:
    if not pane_id:
        return [], "", []
    try:
        capture = run_tmux("capture-pane", "-pt", pane_id)
    except Exception:
        return [], "", []
    raw_lines = [_normalize_preview_line(line) for line in capture.splitlines()]
    prompt_cwd = ""
    commands: list[str] = []
    content: list[str] = []
    for line in raw_lines:
        if not line:
            continue
        cwd, cmd = _extract_prompt_info(line)
        if cwd and not prompt_cwd:
            prompt_cwd = cwd
        if cmd:
            commands.append(cmd)
            continue
        if cwd:
            continue
        content.append(line)
    return raw_lines, prompt_cwd, list(dict.fromkeys(commands + content))


def _ranked_unique_candidates(candidates: list[str], row: dict, limit: int = 3) -> list[str]:
    unique_candidates: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = _normalize_preview_line(candidate)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique_candidates.append(normalized)
    unique_candidates.sort(key=lambda line: (_line_score(line, row), len(line)), reverse=True)
    return unique_candidates[:limit]


def _shell_preview_lines(row: dict) -> list[str]:
    _, prompt_cwd, candidates = _captured_candidates(row.get("pane_id", ""))
    commands: list[str] = []
    output_lines: list[str] = []
    for candidate in candidates:
        cwd, cmd = _extract_prompt_info(candidate)
        if cmd:
            commands.append(cmd)
            continue
        if cwd:
            continue
        output_lines.append(candidate)
    ranked_output = _ranked_unique_candidates(list(reversed(output_lines)), row, limit=2)
    result: list[str] = []
    if commands:
        result.append(commands[-1])
    result.extend(ranked_output)
    if prompt_cwd and not result:
        result.append(prompt_cwd)
    if prompt_cwd and prompt_cwd not in result:
        result.append(prompt_cwd)
    return result[:2]


def _codex_preview_lines(row: dict) -> list[str]:
    _, _, candidates = _captured_candidates(row.get("pane_id", ""))
    preferred: list[str] = []
    fallback: list[str] = []
    for candidate in candidates:
        lowered = candidate.lower()
        if _CODEX_WORKING_RE.match(candidate):
            fallback.append("Working")
            continue
        if any(token in lowered for token in ("implement", "refactor", "fix", "update", "add ", "search", "running", "complete", "error", "approval", "permission")):
            preferred.append(candidate)
        else:
            fallback.append(candidate)
    result = _ranked_unique_candidates(list(reversed(preferred)), row, limit=2)
    if len(result) < 2:
        for candidate in _ranked_unique_candidates(list(reversed(fallback)), row, limit=3):
            if candidate not in result:
                result.append(candidate)
            if len(result) >= 2:
                break
    return result[:2]


def _claude_preview_lines(row: dict) -> list[str]:
    _, _, candidates = _captured_candidates(row.get("pane_id", ""))
    preferred: list[str] = []
    fallback: list[str] = []
    for candidate in candidates:
        if _CLAUDE_STATUS_TITLE_RE.match(candidate):
            continue
        lowered = candidate.lower()
        if any(token in lowered for token in ("permission", "approval", "writing", "updating", "analy", "implement", "finished", "error", "tool")):
            preferred.append(candidate)
        else:
            fallback.append(candidate)
    result = _ranked_unique_candidates(list(reversed(preferred)), row, limit=2)
    if len(result) < 2:
        for candidate in _ranked_unique_candidates(list(reversed(fallback)), row, limit=3):
            if candidate not in result:
                result.append(candidate)
            if len(result) >= 2:
                break
    return result[:2]


def _generic_preview_lines(row: dict) -> list[str]:
    _, prompt_cwd, candidates = _captured_candidates(row.get("pane_id", ""))
    result = _ranked_unique_candidates(list(reversed(candidates)), row, limit=2)
    if prompt_cwd and len(result) < 2 and prompt_cwd not in result:
        result.append(prompt_cwd)
    return result[:2]


def _panel_specific_preview_lines(row: dict) -> list[str]:
    panel_type = _panel_type(row)
    if panel_type == "codex":
        return _codex_preview_lines(row)
    if panel_type == "claude":
        return _claude_preview_lines(row)
    if panel_type == "shell":
        return _shell_preview_lines(row)
    return _generic_preview_lines(row)


def _selected_preview_lines(row: dict) -> list[str]:
    snippets: list[str] = []
    seen: set[str] = set()
    meta_hint = row.get("path", "") or row.get("meta", "")
    for candidate in (
        row.get("preview_message", ""),
        *_panel_specific_preview_lines(row),
        row.get("pane_title", ""),
        meta_hint,
    ):
        normalized = _normalize_preview_line(str(candidate))
        if not normalized:
            continue
        cwd, cmd = _extract_prompt_info(normalized)
        if cmd:
            normalized = cmd
        elif cwd:
            normalized = cwd
        if normalized == row.get("window_name", "") or normalized == row.get("label", ""):
            continue
        if any(pattern.match(normalized.lower()) for pattern in _LOW_SIGNAL_PATTERNS):
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        snippets.append(normalized)
        if len(snippets) >= 2:
            break
    while len(snippets) < 2:
        snippets.append("")
    return snippets


def _session_header_segments(title: str, max_width: int | None = None) -> tuple[list[tuple[str, str]], str]:
    normalized_title = str(title).upper()
    prefix = "  "
    title_block = f"{normalized_title} "
    divider = "━"
    if max_width is None:
        divider_width = 6
    else:
        divider_width = max(2, max_width - len(prefix) - len(title_block))
    divider_block = divider * divider_width
    return (
        [
            (prefix, "base"),
            (title_block, "section"),
            (divider_block, "divider"),
        ],
        truncate_line(prefix + title_block + divider_block, max_width),
    )


def build_visual_lines(rows: list[dict], selected_pane_id: str, max_width: int | None = None) -> list[dict]:
    visual_lines: list[dict] = []
    selected_row = find_selected_row_index(rows, selected_pane_id)
    for row_index, row in enumerate(rows):
        is_selected = selected_row is not None and row_index == selected_row
        prefix = "▶ " if is_selected else "  "
        if row["kind"] == "session":
            segments, text = _session_header_segments(str(row["text"]), max_width)
            visual_lines.append(
                {
                    "row_index": row_index,
                    "kind": row["kind"],
                    "selected": False,
                    "segments": segments,
                    "text": text,
                }
            )
            continue
        if row["kind"] == "window":
            visual_lines.append(
                {
                    "row_index": row_index,
                    "kind": row["kind"],
                    "selected": is_selected,
                    "segments": [(prefix + str(row["text"]), "window_label")],
                    "text": truncate_line(prefix + str(row["text"]), max_width),
                }
            )
            continue
        if row["kind"] == "pane":
            badge = badge_for_status(row.get("status", ""))
            base_segments = [(prefix, "base")]
            if row.get("agent_name"):
                base_segments.append((f"[{row['agent_name']}] ", "pill"))
            title_label = row.get("label") or row.get("window_name") or row.get("pane_command") or row.get("text") or ""
            base_segments.append((title_label, "title"))
            if badge:
                base_segments.append((f" [{badge}]", f"badge:{row.get('status', '')}"))
            visual_lines.append(
                {
                    "row_index": row_index,
                    "kind": row["kind"],
                    "selected": is_selected,
                    "segments": base_segments,
                    "text": truncate_line(prefix + row["text"], max_width),
                }
            )
            if is_selected:
                meta_bits = []
                if row.get("path"):
                    meta_bits.append(str(row["path"]))
                else:
                    meta_bits.append(row.get("session", ""))
                    label = row.get("label", "")
                    if label and label != title_label:
                        meta_bits.append(label)
                meta_text = " · ".join(bit for bit in meta_bits if bit)
                indent = "   "
                visual_lines.append(
                    {
                        "row_index": row_index,
                        "kind": row["kind"],
                        "selected": is_selected,
                        "segments": [(indent + meta_text, "muted")],
                        "text": truncate_line(indent + meta_text, max_width),
                    }
                )
                for preview in _selected_preview_lines(row):
                    visual_lines.append(
                        {
                            "row_index": row_index,
                            "kind": row["kind"],
                            "selected": is_selected,
                            "segments": [(indent + preview, "preview")],
                            "text": truncate_line(indent + preview, max_width),
                        }
                    )
            continue
    return visual_lines


def row_visual_span(visual_lines: list[dict], row_index: int | None) -> tuple[int, int]:
    if row_index is None:
        return 0, 0
    indices = [index for index, line in enumerate(visual_lines) if line["row_index"] == row_index]
    if not indices:
        return 0, 0
    return indices[0], indices[-1] + 1


def _write_row_map(visual_lines: list[dict], scroll_offset: int) -> None:
    global _last_row_map_json
    sidebar_pane = os.environ.get("TMUX_PANE", "")
    if not sidebar_pane:
        return
    data = {"scroll_offset": scroll_offset, "rows": []}
    for line in visual_lines:
        entry: dict = {"kind": line["kind"]}
        row = line.get("row", {})
        if row:
            entry["session"] = row.get("session", "")
            if "window" in row:
                entry["window"] = row["window"]
            if "pane_id" in row:
                entry["pane_id"] = row["pane_id"]
        data["rows"].append(entry)
    json_str = json.dumps(data)
    if json_str == _last_row_map_json:
        return
    map_path = STATE_DIR / f"rowmap-{sidebar_pane}.json"
    try:
        tmp = map_path.with_suffix(".tmp")
        tmp.write_text(json_str)
        tmp.rename(map_path)
        _last_row_map_json = json_str
    except OSError:
        return


def _run_context_menu(mouse_y: int) -> None:
    sidebar_pane = os.environ.get("TMUX_PANE", "")
    if not sidebar_pane:
        return
    menu_file = STATE_DIR / "menu-cmd.tmux"
    try:
        pane_metrics = subprocess.check_output(
            ["tmux", "display-message", "-p", "-t", sidebar_pane, "#{pane_left}|#{pane_top}|#{pane_width}|#{session_name}"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        pane_left_raw, pane_top_raw, pane_width_raw, session_name = pane_metrics.split("|", 3)
        menu_x = str(int(pane_left_raw) + max(0, int(pane_width_raw) - 1))
        menu_y = str(int(pane_top_raw) + max(0, mouse_y))
        target_client = subprocess.check_output(
            ["tmux", "list-clients", "-t", session_name, "-F", "#{client_name}"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).splitlines()[0].strip()
        if not target_client:
            return
    except (subprocess.CalledProcessError, ValueError):
        return
    try:
        menu_file.unlink(missing_ok=True)
    except OSError:
        pass
    subprocess.run(
        [
            "bash",
            str(_scripts_dir() / "features/context-menu/show-context-menu.sh"),
            sidebar_pane,
            str(mouse_y),
            menu_x,
            menu_y,
            target_client,
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if not menu_file.exists():
        return
    try:
        menu_command = shlex.split(menu_file.read_text().strip())
    except (OSError, ValueError):
        return
    if not menu_command:
        return
    subprocess.run(
        ["tmux", *menu_command],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def parse_fg_hex(style: str) -> str:
    match = re.search(r"fg=#([0-9a-fA-F]{6})", style)
    return match.group(1) if match else ""


def hex_to_256(hex_color: str) -> int:
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    ri = min(range(6), key=lambda i: abs(_CUBE_VALUES[i] - r))
    gi = min(range(6), key=lambda i: abs(_CUBE_VALUES[i] - g))
    bi = min(range(6), key=lambda i: abs(_CUBE_VALUES[i] - b))
    return 16 + 36 * ri + 6 * gi + bi


def _option_hex(option: str) -> str:
    raw = tmux_option(option)
    if raw:
        match = _HEX_COLOR_RE.search(raw)
        return match.group(1) if match else ""
    return ""


def _theme_hex(option: str, default: str) -> str:
    return _option_hex(option) or default


def _reset_color_slots() -> None:
    global _color_slots, _next_color_slot
    _color_slots = {}
    _next_color_slot = 16


def _define_color(hex_color: str) -> int:
    global _next_color_slot
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    if curses.can_change_color():
        cached_slot = _color_slots.get(hex_color)
        if cached_slot is not None:
            return cached_slot
        if _next_color_slot >= getattr(curses, "COLORS", 0):
            return hex_to_256(hex_color)
        slot = _next_color_slot
        _next_color_slot += 1
        curses.init_color(slot, r * 1000 // 255, g * 1000 // 255, b * 1000 // 255)
        _color_slots[hex_color] = slot
        return slot
    return hex_to_256(hex_color)


def _parse_border_format_colors() -> dict[str, str]:
    fmt = tmux_option("pane-border-format")
    colors: dict[str, str] = {}
    pattern = r"#\{\?pane_active,#\[fg=#([0-9a-fA-F]{6})\],#\[fg=#([0-9a-fA-F]{6})\]\}"
    matches = list(re.finditer(pattern, fmt))
    if matches:
        colors["inactive_command"] = matches[0].group(2)
    if len(matches) > 1:
        colors["active_path"] = matches[1].group(1)
    return colors


def init_sidebar_colors() -> tuple[int, int, int, int]:
    global _badge_attrs, _role_attrs, _selected_role_attrs
    _badge_attrs = {}
    _role_attrs = {}
    _selected_role_attrs = {}
    try:
        if curses.COLORS < 256:
            return curses.A_REVERSE | curses.A_BOLD, curses.A_BOLD, curses.A_DIM, 0
    except AttributeError:
        return curses.A_REVERSE | curses.A_BOLD, curses.A_BOLD, curses.A_DIM, 0

    _reset_color_slots()

    session_hex = _theme_hex("@tmux_sidebar_color_session", "5b8bd9")
    window_hex = _theme_hex("@tmux_sidebar_color_window", "8fa2ba")
    pane_hex = _theme_hex("@tmux_sidebar_color_pane", DEFAULT_COLOR_FG)
    section_hex = _theme_hex("@tmux_sidebar_color_section", "305ea8")
    divider_hex = _theme_hex("@tmux_sidebar_color_divider", "4d6482")
    muted_hex = _theme_hex("@tmux_sidebar_color_muted", "7d91aa")
    preview_hex = _theme_hex("@tmux_sidebar_color_preview", muted_hex)
    pill_hex = _theme_hex("@tmux_sidebar_color_pill", "7fb3ff")
    selected_fg_hex = _theme_hex("@tmux_sidebar_color_selected_fg", "f3f8ff")
    selected_bg_hex = _theme_hex("@tmux_sidebar_color_selected_bg", "153d73")
    selected_muted_hex = _theme_hex("@tmux_sidebar_color_selected_muted", "bfd4ff")

    curses.init_pair(COLOR_PAIR_SESSION, _define_color(session_hex), -1)
    curses.init_pair(COLOR_PAIR_WINDOW, _define_color(window_hex), -1)
    curses.init_pair(COLOR_PAIR_PANE, _define_color(pane_hex), -1)
    curses.init_pair(COLOR_PAIR_SELECTED, _define_color(selected_fg_hex), _define_color(selected_bg_hex))
    curses.init_pair(COLOR_PAIR_SECTION, _define_color(section_hex), -1)
    curses.init_pair(COLOR_PAIR_DIVIDER, _define_color(divider_hex), -1)
    curses.init_pair(COLOR_PAIR_MUTED, _define_color(muted_hex), -1)
    curses.init_pair(COLOR_PAIR_PREVIEW, _define_color(preview_hex), -1)
    curses.init_pair(COLOR_PAIR_PILL, _define_color(pill_hex), -1)
    curses.init_pair(COLOR_PAIR_SELECTED_MUTED, _define_color(selected_muted_hex), _define_color(selected_bg_hex))
    curses.init_pair(COLOR_PAIR_SELECTED_PILL, _define_color(selected_fg_hex), _define_color(selected_bg_hex))

    badge_colors = {
        "running": _theme_hex("@tmux_sidebar_color_badge_running", "ff8c42"),
        "needs-input": _theme_hex("@tmux_sidebar_color_badge_needs_input", "ffb15c"),
        "done": _theme_hex("@tmux_sidebar_color_badge_done", "16a34a"),
        "done-unread": _theme_hex("@tmux_sidebar_color_badge_done_unread", "f59e0b"),
        "error": _theme_hex("@tmux_sidebar_color_badge_error", "ef4444"),
    }
    badge_pairs = {
        "running": COLOR_PAIR_BADGE_RUNNING,
        "needs-input": COLOR_PAIR_BADGE_NEEDS_INPUT,
        "done": COLOR_PAIR_BADGE_DONE,
        "done-unread": COLOR_PAIR_BADGE_DONE_UNREAD,
        "error": COLOR_PAIR_BADGE_ERROR,
    }
    selected_badge_pairs = {
        "running": COLOR_PAIR_SELECTED_BADGE_RUNNING,
        "needs-input": COLOR_PAIR_SELECTED_BADGE_NEEDS_INPUT,
        "done": COLOR_PAIR_SELECTED_BADGE_DONE,
        "done-unread": COLOR_PAIR_SELECTED_BADGE_DONE_UNREAD,
        "error": COLOR_PAIR_SELECTED_BADGE_ERROR,
    }
    for status, pair_id in badge_pairs.items():
        curses.init_pair(pair_id, _define_color(badge_colors[status]), -1)
        _badge_attrs[status] = curses.color_pair(pair_id) | curses.A_BOLD
        curses.init_pair(selected_badge_pairs[status], _define_color(badge_colors[status]), _define_color(selected_bg_hex))
        _selected_role_attrs[f"badge:{status}"] = curses.color_pair(selected_badge_pairs[status]) | curses.A_BOLD

    _role_attrs = {
        "section": curses.color_pair(COLOR_PAIR_SECTION) | curses.A_BOLD,
        "divider": curses.color_pair(COLOR_PAIR_DIVIDER) | curses.A_DIM,
        "window_label": curses.color_pair(COLOR_PAIR_WINDOW) | curses.A_DIM,
        "title": curses.color_pair(COLOR_PAIR_PANE) | curses.A_BOLD,
        "muted": curses.color_pair(COLOR_PAIR_MUTED) | curses.A_DIM,
        "preview": curses.color_pair(COLOR_PAIR_PREVIEW),
        "pill": curses.color_pair(COLOR_PAIR_PILL) | curses.A_BOLD,
    }
    _selected_role_attrs.update(
        {
            "base": curses.color_pair(COLOR_PAIR_SELECTED),
            "title": curses.color_pair(COLOR_PAIR_SELECTED) | curses.A_BOLD,
            "muted": curses.color_pair(COLOR_PAIR_SELECTED_MUTED),
            "preview": curses.color_pair(COLOR_PAIR_SELECTED_MUTED),
            "pill": curses.color_pair(COLOR_PAIR_SELECTED_PILL) | curses.A_BOLD,
        }
    )

    return (
        curses.color_pair(COLOR_PAIR_SELECTED),
        curses.color_pair(COLOR_PAIR_SESSION),
        curses.color_pair(COLOR_PAIR_WINDOW),
        curses.color_pair(COLOR_PAIR_PANE),
    )


def _line_attr(kind: str, is_selected: bool, is_match: bool, active_attr: int, session_attr: int, window_attr: int, pane_attr: int) -> int:
    if is_selected:
        return active_attr
    if kind == "session":
        return session_attr
    if kind == "window":
        return window_attr
    return pane_attr


def _match_attr(is_match: bool) -> int:
    return getattr(curses, "A_ITALIC", curses.A_UNDERLINE) if is_match else 0


def _segment_attr(role: str, base_attr: int, selected: bool, is_match: bool) -> int:
    match_attr = _match_attr(is_match)
    if selected:
        return (_selected_role_attrs.get(role) or _selected_role_attrs.get("base") or base_attr) | match_attr
    if role.startswith("badge:"):
        return _badge_attrs.get(role.split(":", 1)[1], base_attr | curses.A_BOLD) | match_attr
    if role in _role_attrs:
        return _role_attrs[role] | match_attr
    return base_attr | match_attr


def _render_segments(
    stdscr,
    y: int,
    width: int,
    segments: list[tuple[str, str]],
    base_attr: int,
    selected: bool,
    is_match: bool,
) -> None:
    x = 0
    for text, role in segments:
        if x >= width:
            break
        attr = _segment_attr(role, base_attr, selected, is_match)
        remaining = width - x
        stdscr.addnstr(y, x, text, remaining, attr)
        x += min(len(text), remaining)


def render_screen(
    stdscr,
    rows: list[dict],
    visual_lines: list[dict],
    scroll_offset: int = 0,
    search_query: str = "",
    search_matches: set[int] | None = None,
    search_mode: bool = False,
    active_attr: int = curses.A_BOLD,
    session_attr: int = 0,
    window_attr: int = 0,
    pane_attr: int = 0,
) -> None:
    width = max(0, curses.COLS - 1)
    has_search_bar = search_mode or bool(search_query)
    visible_lines = curses.LINES - (1 if has_search_bar else 0)
    stdscr.erase()
    visible = visual_lines[scroll_offset:scroll_offset + visible_lines]
    for y, line in enumerate(visible):
        if y >= visible_lines:
            break
        row_idx = line["row_index"]
        is_match = bool(search_matches) and row_idx in search_matches
        base_attr = _line_attr(line["kind"], line["selected"], is_match, active_attr, session_attr, window_attr, pane_attr)
        _render_segments(stdscr, y, width, line["segments"], base_attr, line["selected"], is_match)
    if has_search_bar:
        prompt = f"/{search_query}"
        prompt_line = curses.LINES - 1
        stdscr.addnstr(
            prompt_line,
            0,
            truncate_line(prompt, width),
            width,
            0 if search_mode else curses.A_DIM,
        )
        if search_mode:
            curses.curs_set(1)
            stdscr.move(prompt_line, min(len(prompt), width - 1))
        else:
            curses.curs_set(0)
    else:
        curses.curs_set(0)
    stdscr.refresh()
