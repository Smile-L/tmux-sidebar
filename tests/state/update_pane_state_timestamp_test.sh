#!/usr/bin/env bash
set -euo pipefail

. "$(dirname "$0")/testlib.sh"

export TMUX_SIDEBAR_STATE_DIR="$TEST_TMP/state"
fake_tmux_register_pane "%7" "work" "@2" "editor" "Claude"

bash scripts/features/state/update-pane-state.sh \
  --pane "%7" \
  --app claude \
  --status done \
  --updated-at 200

bash scripts/features/state/update-pane-state.sh \
  --pane "%7" \
  --app claude \
  --status running \
  --updated-at 100

assert_file_contains "$TMUX_SIDEBAR_STATE_DIR/pane-%7.json" '"status":"done-unread"'
assert_file_contains "$TMUX_SIDEBAR_STATE_DIR/events/pane-7.ndjson" '"event":"旧时间戳丢弃"'

cat > "$TMUX_SIDEBAR_STATE_DIR/pane-%8.json" <<'EOF'
{"pane_id":"%8","app":"codex","status":"done","updated_at":200}
EOF

bash scripts/features/state/update-pane-state.sh \
  --pane "%8" \
  --app codex \
  --status idle \
  --updated-at 300

assert_file_contains "$TMUX_SIDEBAR_STATE_DIR/pane-%8.json" '"status":"done-unread"'
assert_file_contains "$TMUX_SIDEBAR_STATE_DIR/events/pane-8.ndjson" '"event":"Codex空闲转未读"'

fake_tmux_register_pane "%9" "work" "@2" "editor" "Codex"

cat > "$TMUX_SIDEBAR_STATE_DIR/pane-%9.json" <<'EOF'
{"pane_id":"%9","app":"codex","status":"running","source":"app-server","updated_at":400}
EOF

bash scripts/features/state/update-pane-state.sh \
  --pane "%9" \
  --app codex \
  --status needs-input \
  --source notify \
  --updated-at 400

assert_file_contains "$TMUX_SIDEBAR_STATE_DIR/pane-%9.json" '"status":"running"'
assert_file_contains "$TMUX_SIDEBAR_STATE_DIR/pane-%9.json" '"source":"app-server"'
assert_file_contains "$TMUX_SIDEBAR_STATE_DIR/events/pane-9.ndjson" '"event":"低优先级丢弃"'

cat > "$TMUX_SIDEBAR_STATE_DIR/pane-%10.json" <<'EOF'
{"pane_id":"%10","app":"codex","status":"needs-input","source":"notify","updated_at":500}
EOF

fake_tmux_register_pane "%10" "work" "@2" "editor" "Codex"

bash scripts/features/state/update-pane-state.sh \
  --pane "%10" \
  --app codex \
  --status running \
  --source app-server \
  --updated-at 500

assert_file_contains "$TMUX_SIDEBAR_STATE_DIR/pane-%10.json" '"status":"running"'
assert_file_contains "$TMUX_SIDEBAR_STATE_DIR/pane-%10.json" '"source":"app-server"'
