#!/usr/bin/env bash
set -euo pipefail

. "$(dirname "$0")/testlib.sh"

export TMUX_SIDEBAR_STATE_DIR="$TEST_TMP/state"
mkdir -p "$TMUX_SIDEBAR_STATE_DIR"

fake_tmux_no_sidebar
fake_tmux_register_pane "%1" "work" "@1" "editor" "nvim"
fake_tmux_register_pane "%2" "work" "@1" "server" "bash" "bash"
printf '1\n' > "$TEST_TMUX_DATA_DIR/option__tmux_sidebar_enabled.txt"

bash scripts/features/sidebar/on-pane-focus.sh "%1" "@1"

assert_file_contains "$TEST_TMUX_DATA_DIR/commands.log" 'set-option -g @tmux_sidebar_main_pane %1'
assert_file_contains "$TEST_TMUX_DATA_DIR/commands.log" 'split-window -t %1 -h -b -d -f -l 50'

fake_tmux_no_sidebar
fake_tmux_register_pane "%1" "work" "@1" "editor" "nvim"

bash scripts/features/sidebar/on-pane-focus.sh "%1" "@1"

assert_file_not_contains "$TEST_TMUX_DATA_DIR/commands.log" 'split-window'

fake_tmux_no_sidebar
fake_tmux_register_pane "%1" "work" "@1" "editor" "nvim"
printf '1\n' > "$TEST_TMUX_DATA_DIR/option__tmux_sidebar_enabled.txt"

cat > "$TMUX_SIDEBAR_STATE_DIR/pane-%1.json" <<'EOF'
{"pane_id":"%1","app":"claude","status":"needs-input","updated_at":100}
EOF

bash scripts/features/sidebar/on-pane-focus.sh "%1" "@1"

assert_file_contains "$TMUX_SIDEBAR_STATE_DIR/pane-%1.json" '"status":"idle"'
assert_file_contains "$TEST_TMUX_DATA_DIR/commands.log" 'set-option -g @tmux_sidebar_main_pane %1'
assert_file_contains "$TMUX_SIDEBAR_STATE_DIR/events/pane-1.ndjson" '"event":"进入pane清已读/输入"'

fake_tmux_no_sidebar
fake_tmux_register_pane "%1" "work" "@1" "editor" "nvim"
printf '1\n' > "$TEST_TMUX_DATA_DIR/option__tmux_sidebar_enabled.txt"

cat > "$TMUX_SIDEBAR_STATE_DIR/pane-%1.json" <<'EOF'
{"pane_id":"%1","app":"claude","status":"running","updated_at":100}
EOF

bash scripts/features/sidebar/on-pane-focus.sh "%1" "@1"

assert_file_contains "$TMUX_SIDEBAR_STATE_DIR/pane-%1.json" '"status":"running"'

fake_tmux_no_sidebar
fake_tmux_register_pane "%6" "work" "@1" "editor" "codex --full-auto" "codex-aarch64-apple-darwin"
printf '1\n' > "$TEST_TMUX_DATA_DIR/option__tmux_sidebar_enabled.txt"

cat > "$TMUX_SIDEBAR_STATE_DIR/pane-%6.json" <<'EOF'
{"pane_id":"%6","app":"codex","status":"done","updated_at":100}
EOF

bash scripts/features/sidebar/on-pane-focus.sh "%6" "@1"

assert_file_contains "$TMUX_SIDEBAR_STATE_DIR/pane-%6.json" '"status":"done-unread"'

fake_tmux_no_sidebar
fake_tmux_register_pane "%16" "work" "@1" "editor" "codex --full-auto" "codex-aarch64-apple-darwin"
printf '1\n' > "$TEST_TMUX_DATA_DIR/option__tmux_sidebar_enabled.txt"

cat > "$TMUX_SIDEBAR_STATE_DIR/pane-%16.json" <<'EOF'
{"pane_id":"%16","app":"codex","status":"done-unread","updated_at":100}
EOF

bash scripts/features/sidebar/on-pane-focus.sh "%16" "@1"

assert_file_contains "$TMUX_SIDEBAR_STATE_DIR/pane-%16.json" '"status":"done-unread"'

fake_tmux_no_sidebar
fake_tmux_register_main_pane "%21"
fake_tmux_register_pane "%21" "work" "@1" "editor" "codex --full-auto" "codex-aarch64-apple-darwin"
fake_tmux_register_pane "%22" "work" "@1" "shell" "bash" "bash"
printf '1\n' > "$TEST_TMUX_DATA_DIR/option__tmux_sidebar_enabled.txt"

cat > "$TMUX_SIDEBAR_STATE_DIR/pane-%21.json" <<'EOF'
{"pane_id":"%21","app":"codex","status":"done","updated_at":100}
EOF

bash scripts/features/sidebar/on-pane-focus.sh "%22" "@1"

assert_file_contains "$TMUX_SIDEBAR_STATE_DIR/pane-%21.json" '"status":"done-unread"'
assert_file_contains "$TEST_TMUX_DATA_DIR/commands.log" 'set-option -g @tmux_sidebar_main_pane %22'
assert_file_contains "$TMUX_SIDEBAR_STATE_DIR/events/pane-21.ndjson" '"event":"离开pane标未读"'

fake_tmux_no_sidebar
fake_tmux_register_main_pane "%31"
fake_tmux_register_pane "%31" "work" "@1" "editor" "codex --full-auto" "codex-aarch64-apple-darwin"
fake_tmux_register_pane "%32" "work" "@1" "shell" "bash" "bash"
printf '1\n' > "$TEST_TMUX_DATA_DIR/option__tmux_sidebar_enabled.txt"

cat > "$TMUX_SIDEBAR_STATE_DIR/pane-%31.json" <<'EOF'
{"pane_id":"%31","app":"codex","status":"done-unread","updated_at":100}
EOF

bash scripts/features/sidebar/on-pane-focus.sh "%32" "@1"

assert_file_contains "$TMUX_SIDEBAR_STATE_DIR/pane-%31.json" '"status":"done-unread"'

fake_tmux_no_sidebar
fake_tmux_register_pane "%90" "work" "@1" "editor" "Sidebar" "python3"
fake_tmux_add_sidebar_pane "%90" "@1"
printf '%%90\n' > "$TEST_TMUX_DATA_DIR/current_pane.txt"
printf '1\n' > "$TEST_TMUX_DATA_DIR/option__tmux_sidebar_enabled.txt"

bash scripts/features/sidebar/on-pane-focus.sh "%90" "@1"

assert_file_not_contains "$TEST_TMUX_DATA_DIR/commands.log" 'set-option -g @tmux_sidebar_main_pane %90'

fake_tmux_no_sidebar
fake_tmux_register_pane "%5" "work" "@1" "editor" "● project: done" "2.1.76"
printf '1\n' > "$TEST_TMUX_DATA_DIR/option__tmux_sidebar_enabled.txt"
rm -f "$TMUX_SIDEBAR_STATE_DIR/pane-%5.json"

bash scripts/features/sidebar/on-pane-focus.sh "%5" "@1"

assert_file_contains "$TMUX_SIDEBAR_STATE_DIR/pane-%5.json" '"status":"idle"'
assert_file_contains "$TMUX_SIDEBAR_STATE_DIR/pane-%5.json" '"app":"claude"'
assert_file_contains "$TMUX_SIDEBAR_STATE_DIR/events/pane-5.ndjson" '"event":"标题推断补状态"'
