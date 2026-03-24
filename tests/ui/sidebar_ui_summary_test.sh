#!/usr/bin/env bash
set -euo pipefail

. "$(dirname "$0")/testlib.sh"

output="$(python3 - <<'PY'
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path("scripts/ui")))
from sidebar_ui_lib import render

shell_row = {
    "pane_id": "%1",
    "session": "work",
    "window_name": "poly",
    "label": "zsh",
    "pane_command": "zsh",
    "agent_name": "",
    "path": "/Users/lisimin/project/poly_data",
    "preview_message": "",
    "pane_title": "zsh",
}

render.run_tmux = lambda *args: "\n".join([
    "(base) lisimin@localhost poly_data % cd project/poly_data",
    "Loaded 324 files",
    "(base) lisimin@localhost poly_data %",
])

shell_preview = render._selected_preview_lines(shell_row)

codex_row = {
    "pane_id": "%2",
    "session": "work",
    "window_name": "agent",
    "label": "codex",
    "pane_command": "node",
    "agent_name": "Codex",
    "path": "/Users/lisimin/project/poly_data",
    "preview_message": "Implement sidebar summary ranking",
    "pane_title": "codex --full-auto",
}

render.run_tmux = lambda *args: "\n".join([
    "• Working (15s • esc to interrupt)",
    "Searching the codebase for sidebar summary logic",
    "Updated render pipeline for panel-specific previews",
])
codex_preview = render._selected_preview_lines(codex_row)

claude_row = {
    "pane_id": "%3",
    "session": "work",
    "window_name": "chat",
    "label": "claude",
    "pane_command": "python3.12",
    "agent_name": "Claude",
    "path": "/Users/lisimin/project/poly_data",
    "preview_message": "",
    "pane_title": "● project: running",
}

render.run_tmux = lambda *args: "\n".join([
    "Analyzing failing integration tests for tmux sidebar",
    "Preparing patch for on-pane-focus state transition",
])
claude_preview = render._selected_preview_lines(claude_row)

print(json.dumps({"shell": shell_preview, "codex": codex_preview, "claude": claude_preview}, ensure_ascii=False))
PY
)"

assert_contains "$output" 'Loaded 324 files'
assert_contains "$output" 'cd project/poly_data'
assert_contains "$output" 'Implement sidebar summary ranking'
assert_contains "$output" 'Updated render pipeline for panel-specific previews'
assert_contains "$output" 'Analyzing failing integration tests for tmux sidebar'
assert_not_contains "$output" 'lisimin@localhost poly_data %'
