#!/usr/bin/env bash
set -euo pipefail

. "$(dirname "$0")/testlib.sh"

export TMUX_SIDEBAR_STATE_DIR="$TEST_TMP/state"
fake_tmux_register_pane "%7" "work" "@2" "editor" "Claude"
printf '%%7\n' > "$TEST_TMUX_DATA_DIR/current_pane.txt"

bash scripts/features/state/update-pane-state.sh \
  --pane "%7" \
  --app claude \
  --status needs-input \
  --message "Permission request"

assert_file_contains "$TMUX_SIDEBAR_STATE_DIR/pane-%7.json" '"status":"needs-input"'
assert_file_contains "$TMUX_SIDEBAR_STATE_DIR/pane-%7.json" '"app":"claude"'
assert_file_contains "$TMUX_SIDEBAR_STATE_DIR/pane-%7.json" '"session_name":"work"'
assert_file_contains "$TMUX_SIDEBAR_STATE_DIR/events/pane-7.ndjson" '"event":"写入状态"'
assert_file_contains "$TMUX_SIDEBAR_STATE_DIR/events/pane-7.ndjson" '"requested_status":"needs-input"'
assert_file_contains "$TMUX_SIDEBAR_STATE_DIR/events/pane-7.ndjson" '"next_status":"needs-input"'

bash scripts/features/state/update-pane-state.sh \
  --pane "%8" \
  --app codex \
  --status running \
  --message "Working"

assert_file_contains "$TMUX_SIDEBAR_STATE_DIR/pane-%8.json" '"pane_id":"%8"'
assert_file_contains "$TMUX_SIDEBAR_STATE_DIR/pane-%8.json" '"app":"codex"'
assert_file_contains "$TMUX_SIDEBAR_STATE_DIR/pane-%8.json" '"status":"running"'

bash scripts/features/state/update-pane-state.sh \
  --pane "%8" \
  --app codex \
  --status done \
  --message "Finished in background"

assert_file_contains "$TMUX_SIDEBAR_STATE_DIR/pane-%8.json" '"status":"done-unread"'

cat > "$TMUX_SIDEBAR_STATE_DIR/pane-%8.json" <<'EOF'
{"pane_id":"%8","app":"codex","status":"done-unread","updated_at":100}
EOF

bash scripts/features/state/update-pane-state.sh \
  --pane "%8" \
  --app codex \
  --status done \
  --message "Hook repeated done"

assert_file_contains "$TMUX_SIDEBAR_STATE_DIR/pane-%8.json" '"status":"done-unread"'

bash scripts/features/state/update-pane-state.sh \
  --pane "%8" \
  --app codex \
  --status idle \
  --message "Hook says idle"

assert_file_contains "$TMUX_SIDEBAR_STATE_DIR/pane-%8.json" '"status":"done-unread"'

bash scripts/features/state/update-pane-state.sh \
  --pane "" \
  --app codex \
  --status done \
  --message "Finished"

assert_file_contains "$TMUX_SIDEBAR_STATE_DIR/pane-%7.json" '"pane_id":"%7"'
assert_file_contains "$TMUX_SIDEBAR_STATE_DIR/pane-%7.json" '"app":"codex"'
assert_file_contains "$TMUX_SIDEBAR_STATE_DIR/pane-%7.json" '"status":"done-unread"'
