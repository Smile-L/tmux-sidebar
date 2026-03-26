#!/usr/bin/env bash
set -euo pipefail

. "$(dirname "$0")/testlib.sh"

output="$(python3 - <<'PY'
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path("scripts/ui")))
from sidebar_ui_lib import status

captures = {
    "%running": "\n".join([
        "› Summarize recent commits",
        "",
        "• Working (18s • esc to interrupt) · 3 background terminals running · /ps to view · /stop to close",
    ]),
    "%idle": "\n".join([
        "■ '/model' is disabled while a task is in progress.",
        "",
        "› Write tests for @filename",
        "",
        "  gpt-5.4 high · 76% left · /mnt/nas205/workspace/simin.li/wechat_robot",
    ]),
    "%approval": "\n".join([
        "Would you like to run the following command?",
        "Press enter to confirm or esc to cancel",
    ]),
}

status.run_tmux = lambda *args: captures.get(args[-1], "")
print(json.dumps({
    "running": status.codex_terminal_status("%running"),
    "idle": status.codex_terminal_status("%idle"),
    "approval": status.codex_terminal_status("%approval"),
    "completed_recently": status.codex_terminal_completed_recently("%idle"),
    "effective_idle_after_running": status.effective_pane_status("%idle", "node", "v4", {
        "app": "codex",
        "status": "running",
        "inferred": True,
    }),
    "effective_done_unread": status.effective_pane_status("%idle", "node", "v4", {
        "app": "codex",
        "status": "done-unread",
    }),
}, ensure_ascii=False))
PY
)"

assert_contains "$output" '"running": "running"'
assert_contains "$output" '"idle": ""'
assert_contains "$output" '"approval": "needs-input"'
assert_contains "$output" '"completed_recently": true'
assert_contains "$output" '"effective_idle_after_running": "done-unread"'
assert_contains "$output" '"effective_done_unread": "done-unread"'
