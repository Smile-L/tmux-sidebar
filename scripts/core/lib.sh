#!/usr/bin/env bash
set -euo pipefail

tmux_sidebar_state_dir_option() {
  printf '%s\n' '@tmux_sidebar_state_dir'
}

_state_dir_is_writable() {
  local candidate="${1:-}" probe
  [ -n "$candidate" ] || return 1
  mkdir -p "$candidate" 2>/dev/null || true
  probe="$candidate/.write-test.$$"
  if { : > "$probe"; } 2>/dev/null; then
    rm -f "$probe"
    return 0
  fi
  return 1
}

persist_tmux_sidebar_state_dir() {
  local candidate="${1:-}"
  [ -n "$candidate" ] || return 0
  tmux set-option -g "$(tmux_sidebar_state_dir_option)" "$candidate" 2>/dev/null || true
}

print_state_dir() {
  local preferred fallback candidate stored_option
  stored_option="$(tmux show-options -gv "$(tmux_sidebar_state_dir_option)" 2>/dev/null || true)"
  if _state_dir_is_writable "$stored_option"; then
    printf '%s\n' "$stored_option"
    return 0
  fi
  fallback="/tmp/tmux-sidebar-$(id -u)"
  if [ -n "${TMUX_SIDEBAR_STATE_DIR:-}" ]; then
    preferred="$TMUX_SIDEBAR_STATE_DIR"
  elif [ -n "${XDG_STATE_HOME:-}" ]; then
    preferred="$XDG_STATE_HOME/tmux-sidebar"
  else
    preferred="$fallback"
  fi
  for candidate in "$preferred" "$fallback"; do
    if _state_dir_is_writable "$candidate"; then
      persist_tmux_sidebar_state_dir "$candidate"
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  printf '%s\n' "$preferred"
}

sidebar_pane_title() {
  printf '%s\n' 'Sidebar'
}

sidebar_legacy_pane_title() {
  printf '%s\n' 'tmux-sidebar'
}

sidebar_title_pattern() {
  printf '%s\n' "^($(sidebar_pane_title)|$(sidebar_legacy_pane_title))$"
}

is_sidebar_pane_title() {
  local title="${1:-}"
  local sidebar_titles
  sidebar_titles="$(sidebar_title_pattern)"
  [[ "$title" =~ $sidebar_titles ]]
}

sidebar_pane_border_format() {
  local pattern
  pattern="$(sidebar_title_pattern)"
  printf '#{?#{m/r:%s,#{pane_title}},#{pane_title},#{E:@tmux_sidebar_base_pane_border_format}}\n' "$pattern"
}

sidebar_ui_command() {
  local scripts_dir="$1"
  printf 'python3 %q' "$scripts_dir/ui/sidebar-ui.py"
}

json_escape() {
  local value="${1:-}"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\n'/\\n}"
  printf '%s' "$value"
}

json_get_string() {
  local path="$1"
  local key="$2"
  sed -n "s/.*\"$key\":\"\\([^\"]*\\)\".*/\\1/p" "$path"
}

json_get_number() {
  local path="$1"
  local key="$2"
  sed -n "s/.*\"$key\":\\([0-9][0-9]*\\).*/\\1/p" "$path"
}

pane_event_log_dir() {
  printf '%s/events\n' "$(print_state_dir)"
}

pane_event_log_path() {
  local pane_id="${1:-}"
  printf '%s/pane-%s.ndjson\n' "$(pane_event_log_dir)" "${pane_id//%/}"
}

_rotate_event_log_if_needed() {
  local path="$1"
  [ -f "$path" ] || return 0
  local size
  size="$(wc -c < "$path" 2>/dev/null || printf '0')"
  [ "$size" -lt 262144 ] || {
    mv "$path" "$path.1" 2>/dev/null || true
    : > "$path"
  }
}

append_pane_event_log() {
  local pane_id="${1:-}"
  local payload="${2:-}"
  [ -n "$pane_id" ] || return 0
  [ -n "$payload" ] || return 0

  local dir path
  dir="$(pane_event_log_dir)"
  mkdir -p "$dir" 2>/dev/null || return 0
  path="$(pane_event_log_path "$pane_id")"
  _rotate_event_log_if_needed "$path" || true

  printf '%s\n' "$payload" >> "$path" 2>/dev/null || true
}

mark_terminal_pane_state_read_on_focus() {
  local state_file="$1"
  [ -f "$state_file" ] || return 1

  local status app state_dir tmp_file replacement_status
  status="$(json_get_string "$state_file" "status")"
  app="$(json_get_string "$state_file" "app")"
  case "$status" in
    needs-input)
      if [ "$app" = "codex" ]; then
        return 1
      fi
      replacement_status="idle"
      ;;
    done-unread)
      if [ "$app" = "codex" ]; then
        return 1
      fi
      replacement_status="done"
      ;;
    done)
      if [ "$app" = "codex" ]; then
        return 1
      fi
      ;;
    *)
      return 1
      ;;
  esac

  state_dir="$(dirname "$state_file")"
  tmp_file="$(mktemp "$state_dir/.pane-state.XXXXXX")"
  sed "s/\"status\":\"[^\"]*\"/\"status\":\"$replacement_status\"/" "$state_file" > "$tmp_file"
  mv "$tmp_file" "$state_file"

  pane_id="$(json_get_string "$state_file" "pane_id")"
  if [ -n "$pane_id" ]; then
    append_pane_event_log "$pane_id" "$(printf '{\"ts\":%d,\"pane_id\":\"%s\",\"app\":\"%s\",\"component\":\"lib\",\"event\":\"进入pane清已读/输入\",\"window_id\":\"\",\"previous_status\":\"%s\",\"requested_status\":\"focus\",\"next_status\":\"%s\"}' "$(date +%s)" "$(json_escape "$pane_id")" "$(json_escape "$app")" "$(json_escape "$status")" "$(json_escape "$replacement_status")")"
  fi

  signal_sidebar_refresh
  return 0
}

mark_terminal_pane_state_unread_on_blur() {
  local state_file="$1"
  [ -f "$state_file" ] || return 1

  local status app state_dir tmp_file
  status="$(json_get_string "$state_file" "status")"
  app="$(json_get_string "$state_file" "app")"
  [ "$app" = "codex" ] || return 1
  [ "$status" = "done" ] || return 1

  state_dir="$(dirname "$state_file")"
  tmp_file="$(mktemp "$state_dir/.pane-state.XXXXXX")"
  sed 's/"status":"done"/"status":"done-unread"/' "$state_file" > "$tmp_file"
  mv "$tmp_file" "$state_file"

  pane_id="$(json_get_string "$state_file" "pane_id")"
  if [ -n "$pane_id" ]; then
    append_pane_event_log "$pane_id" "$(printf '{\"ts\":%d,\"pane_id\":\"%s\",\"app\":\"%s\",\"component\":\"lib\",\"event\":\"离开pane标未读\",\"window_id\":\"\",\"previous_status\":\"done\",\"requested_status\":\"blur\",\"next_status\":\"done-unread\"}' "$(date +%s)" "$(json_escape "$pane_id")" "$(json_escape "$app")")"
  fi

  signal_sidebar_refresh
  return 0
}

window_key_for_id() {
  local window_id="$1"
  printf '%s\n' "${window_id//@/w}"
}

sidebar_window_option() {
  local suffix="$1"
  local window_id="$2"
  local window_key
  window_key="$(window_key_for_id "$window_id")"
  printf '@tmux_sidebar_%s_%s\n' "$suffix" "$window_key"
}

sidebar_focus_request_option() {
  local window_id="$1"
  sidebar_window_option "focus" "$window_id"
}

option_is_enabled() {
  local value="${1:-}"
  local default_value="${2:-0}"
  local normalized

  if [ -z "$value" ]; then
    value="$default_value"
  fi

  normalized="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')"
  case "$normalized" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

window_non_sidebar_panes_csv() {
  local window_id="$1"
  local sidebar_titles
  sidebar_titles="$(sidebar_title_pattern)"
  tmux list-panes -a -F '#{pane_id}|#{pane_title}|#{window_id}' \
    | awk -F'|' -v current_window="$window_id" -v sidebar_titles="$sidebar_titles" \
        '$3 == current_window && $2 !~ sidebar_titles { print $1 }' \
    | LC_ALL=C sort \
    | paste -sd ',' -
}

list_sidebar_panes() {
  local sidebar_titles
  sidebar_titles="$(sidebar_title_pattern)"
  tmux list-panes -a -F '#{pane_id}|#{pane_title}|#{window_id}' \
    | awk -F'|' -v sidebar_titles="$sidebar_titles" '$2 ~ sidebar_titles { print $1 "|" $3 }'
}

list_sidebar_panes_in_window() {
  local window_id="$1"
  local sidebar_titles
  sidebar_titles="$(sidebar_title_pattern)"
  tmux list-panes -a -F '#{pane_id}|#{pane_title}|#{window_id}' \
    | awk -F'|' -v target_window="$window_id" -v sidebar_titles="$sidebar_titles" \
        '$2 ~ sidebar_titles && $3 == target_window { print $1 "|" $3 }'
}

list_sidebar_panes_in_session() {
  local session_name="$1"
  local sidebar_titles
  sidebar_titles="$(sidebar_title_pattern)"
  tmux list-panes -a -F '#{pane_id}|#{pane_title}|#{session_name}|#{window_id}' \
    | awk -F'|' -v target_session="$session_name" -v sidebar_titles="$sidebar_titles" \
        '$2 ~ sidebar_titles && $3 == target_session { print $1 "|" $4 }'
}

clear_sidebar_state_options() {
  tmux show-options -g 2>/dev/null \
    | awk '/^@tmux_sidebar_(pane|creating|layout|panes|focus)_w/ { print $1 }' \
    | while IFS= read -r option_name; do
        [ -n "$option_name" ] || continue
        tmux set-option -g -u "$option_name"
      done
}

clear_sidebar_window_state_options() {
  local window_id="$1"
  tmux set-option -g -u "$(sidebar_window_option "pane" "$window_id")" 2>/dev/null || true
  tmux set-option -g -u "$(sidebar_window_option "creating" "$window_id")" 2>/dev/null || true
  tmux set-option -g -u "$(sidebar_window_option "focus" "$window_id")" 2>/dev/null || true
  clear_sidebar_window_snapshot "$window_id"
}

save_sidebar_window_snapshot() {
  local window_id="$1"
  local target_pane="${2:-}"
  local layout_option panes_option current_layout current_panes layout_target

  layout_option="$(sidebar_window_option "layout" "$window_id")"
  panes_option="$(sidebar_window_option "panes" "$window_id")"
  layout_target="$window_id"
  if [ -n "$target_pane" ]; then
    layout_target="$target_pane"
  fi
  current_layout="$(tmux display-message -p -t "$layout_target" '#{window_layout}' 2>/dev/null || true)"
  current_panes="$(window_non_sidebar_panes_csv "$window_id")"

  if [ -n "$current_layout" ]; then
    tmux set-option -g "$layout_option" "$current_layout"
  else
    tmux set-option -g -u "$layout_option" 2>/dev/null || true
  fi

  if [ -n "$current_panes" ]; then
    tmux set-option -g "$panes_option" "$current_panes"
  else
    tmux set-option -g -u "$panes_option" 2>/dev/null || true
  fi
}

clear_sidebar_window_snapshot() {
  local window_id="$1"
  tmux set-option -g -u "$(sidebar_window_option "layout" "$window_id")" 2>/dev/null || true
  tmux set-option -g -u "$(sidebar_window_option "panes" "$window_id")" 2>/dev/null || true
}

restore_sidebar_window_snapshot_if_unchanged() {
  local window_id="$1"
  local layout_option panes_option saved_layout saved_panes current_panes

  layout_option="$(sidebar_window_option "layout" "$window_id")"
  panes_option="$(sidebar_window_option "panes" "$window_id")"
  saved_layout="$(tmux show-options -gv "$layout_option" 2>/dev/null || true)"
  saved_panes="$(tmux show-options -gv "$panes_option" 2>/dev/null || true)"
  current_panes="$(window_non_sidebar_panes_csv "$window_id")"

  if [ -n "$saved_layout" ] && [ -n "$saved_panes" ] && [ "$current_panes" = "$saved_panes" ]; then
    tmux select-layout -t "$window_id" "$saved_layout" 2>/dev/null || true
  fi

  clear_sidebar_window_snapshot "$window_id"
}

signal_sidebar_refresh() {
  local state_dir pid_file pid
  state_dir="$(print_state_dir)"
  for pid_file in "$state_dir"/sidebar-*.pid; do
    [ -e "$pid_file" ] || continue
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    [ -n "$pid" ] || continue
    kill -USR1 "$pid" 2>/dev/null || true
  done
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  "$@"
fi
