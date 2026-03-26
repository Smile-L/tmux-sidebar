#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
SCRIPTS_DIR="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
. "$SCRIPTS_DIR/core/lib.sh"

pane_id="${1:-}"
window_id="${2:-}"

enabled="$(tmux show-options -gv @tmux_sidebar_enabled 2>/dev/null || printf '0\n')"
previous_main_pane="$(tmux show-options -gv @tmux_sidebar_main_pane 2>/dev/null || true)"

if [ -n "$pane_id" ]; then
  pane_title="$(tmux display-message -p -t "$pane_id" '#{pane_title}' 2>/dev/null || true)"
  pane_command="$(tmux display-message -p -t "$pane_id" '#{pane_current_command}' 2>/dev/null || true)"
  pane_path="$(tmux display-message -p -t "$pane_id" '#{pane_current_path}' 2>/dev/null || true)"
  if [[ "$pane_id" =~ ^%[0-9]+$ ]]; then
    append_pane_event_log "$pane_id" "$(printf '{\"ts\":%d,\"pane_id\":\"%s\",\"pane_name\":\"%s\",\"pane_path\":\"%s\",\"app\":\"\",\"component\":\"on-pane-focus\",\"event\":\"进入pane\",\"window_id\":\"%s\",\"previous_status\":\"\",\"requested_status\":\"focus\",\"next_status\":\"\"}' "$(date +%s)" "$(json_escape "$pane_id")" "$(json_escape "$pane_title")" "$(json_escape "$pane_path")" "$(json_escape "$window_id")")"
  fi
  if ! printf '%s\n' "$pane_title" | grep -Eq "$(sidebar_title_pattern)"; then
    tmux set-option -g @tmux_sidebar_main_pane "$pane_id"
  fi

  if [[ "$pane_id" =~ ^%[0-9]+$ ]]; then
    state_dir="$(print_state_dir)"
    state_file="$state_dir/pane-$pane_id.json"
    if [ -f "$state_file" ]; then
      app="$(json_get_string "$state_file" "app")"
      if [ "$app" = "codex" ]; then
        mark_terminal_pane_state_unread_on_blur "$state_file" || true
      else
        mark_terminal_pane_state_read_on_focus "$state_file" || true
      fi
    elif printf '%s\n' "$pane_title" | grep -qE '(: (done|needs-input|error))\s*$'; then
      tmp_file="$(mktemp "$state_dir/.pane-state.XXXXXX")"
      printf '{"pane_id":"%s","app":"claude","status":"idle","updated_at":%d}\n' \
        "$pane_id" "$(date +%s)" > "$tmp_file"
      mv "$tmp_file" "$state_file"
      append_pane_event_log "$pane_id" "$(printf '{\"ts\":%d,\"pane_id\":\"%s\",\"pane_name\":\"%s\",\"pane_path\":\"%s\",\"app\":\"claude\",\"component\":\"on-pane-focus\",\"event\":\"标题推断补状态\",\"window_id\":\"%s\",\"previous_status\":\"\",\"requested_status\":\"focus\",\"next_status\":\"idle\"}' "$(date +%s)" "$(json_escape "$pane_id")" "$(json_escape "$pane_title")" "$(json_escape "$pane_path")" "$(json_escape "$window_id")")"
      signal_sidebar_refresh
    fi
  fi
fi

if [ -n "$previous_main_pane" ] && [ "$previous_main_pane" != "$pane_id" ] && [[ "$previous_main_pane" =~ ^%[0-9]+$ ]]; then
  previous_title="$(tmux display-message -p -t "$previous_main_pane" '#{pane_title}' 2>/dev/null || true)"
  previous_window_id="$(tmux display-message -p -t "$previous_main_pane" '#{window_id}' 2>/dev/null || true)"
  previous_path="$(tmux display-message -p -t "$previous_main_pane" '#{pane_current_path}' 2>/dev/null || true)"
  append_pane_event_log "$previous_main_pane" "$(printf '{\"ts\":%d,\"pane_id\":\"%s\",\"pane_name\":\"%s\",\"pane_path\":\"%s\",\"app\":\"\",\"component\":\"on-pane-focus\",\"event\":\"离开pane\",\"window_id\":\"%s\",\"previous_status\":\"\",\"requested_status\":\"blur\",\"next_status\":\"\"}' "$(date +%s)" "$(json_escape "$previous_main_pane")" "$(json_escape "$previous_title")" "$(json_escape "$previous_path")" "$(json_escape "$previous_window_id")")"
  if ! printf '%s\n' "$previous_title" | grep -Eq "$(sidebar_title_pattern)"; then
    state_dir="$(print_state_dir)"
    previous_state_file="$state_dir/pane-$previous_main_pane.json"
    if [ -f "$previous_state_file" ]; then
      mark_terminal_pane_state_unread_on_blur "$previous_state_file" || true
    fi
  fi
fi

[ "$enabled" = "1" ] || exit 0
exec bash "$SCRIPT_DIR/ensure-sidebar-pane.sh" "$pane_id" "$window_id"
