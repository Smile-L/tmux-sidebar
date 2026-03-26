#!/usr/bin/env bash
set -euo pipefail

. "$(dirname "$0")/testlib.sh"

unset TMUX_SIDEBAR_STATE_DIR
unset XDG_STATE_HOME
run_script scripts/core/lib.sh print_state_dir
case "$output" in
  /tmp/tmux-sidebar-* ) ;;
  * ) fail "expected fallback state dir under /tmp, got [$output]" ;;
esac

rm -f "$TEST_TMUX_DATA_DIR/option__tmux_sidebar_state_dir.txt"
export XDG_STATE_HOME="/tmp/xdg-state-test"
run_script scripts/core/lib.sh print_state_dir
assert_eq "$output" "/tmp/xdg-state-test/tmux-sidebar"
unset XDG_STATE_HOME
