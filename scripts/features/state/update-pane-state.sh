#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
SCRIPTS_DIR="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
. "$SCRIPTS_DIR/core/lib.sh"
pane_id=""
app=""
status=""
message=""
updated_at=""
source=""

source_priority() {
  case "${1:-}" in
    app-server)
      printf '30\n'
      ;;
    notify|hook)
      printf '20\n'
      ;;
    *)
      printf '10\n'
      ;;
  esac
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --pane)
      pane_id="${2:-}"
      shift 2
      ;;
    --app)
      app="${2:-}"
      shift 2
      ;;
    --status)
      status="${2:-}"
      shift 2
      ;;
    --message)
      message="${2:-}"
      shift 2
      ;;
    --updated-at)
      updated_at="${2:-}"
      shift 2
      ;;
    --source)
      source="${2:-}"
      shift 2
      ;;
    *)
      printf 'unknown arg: %s\n' "$1" >&2
      exit 1
      ;;
  esac
done

if [ -z "$pane_id" ]; then
  pane_id="$(tmux display-message -p '#{pane_id}' 2>/dev/null || true)"
fi

[ -n "$pane_id" ] || exit 0
[[ "$pane_id" =~ ^%[0-9]+$ ]] || { printf 'invalid pane_id: %s\n' "$pane_id" >&2; exit 1; }

state_dir="$(print_state_dir)"
mkdir -p "$state_dir"
state_file="$state_dir/pane-$pane_id.json"

if [ -z "$updated_at" ]; then
  updated_at="$(date +%s)"
fi
[[ "$updated_at" =~ ^[0-9]+$ ]] || { printf 'invalid updated_at: %s\n' "$updated_at" >&2; exit 1; }

existing_app=""
existing_status=""
existing_source=""
existing_updated_at=""
if [ -f "$state_file" ]; then
  existing_updated_at="$(json_get_number "$state_file" "updated_at")"
  existing_app="$(json_get_string "$state_file" "app")"
  existing_status="$(json_get_string "$state_file" "status")"
  existing_source="$(json_get_string "$state_file" "source")"
fi

if [ -n "$existing_updated_at" ] && [ "$existing_updated_at" -gt "$updated_at" ]; then
  append_pane_event_log "$pane_id" "$(printf '{\"ts\":%d,\"pane_id\":\"%s\",\"app\":\"%s\",\"component\":\"update-pane-state\",\"event\":\"旧时间戳丢弃\",\"window_id\":\"\",\"previous_status\":\"%s\",\"requested_status\":\"%s\",\"next_status\":\"%s\"}' "$(date +%s)" "$(json_escape "$pane_id")" "$(json_escape "$app")" "$(json_escape "$existing_status")" "$(json_escape "$status")" "$(json_escape "$existing_status")")"
  exit 0
fi

if [ -n "$existing_updated_at" ] && [ "$existing_updated_at" -eq "$updated_at" ]; then
  if [ "$(source_priority "$existing_source")" -gt "$(source_priority "$source")" ]; then
    append_pane_event_log "$pane_id" "$(printf '{\"ts\":%d,\"pane_id\":\"%s\",\"app\":\"%s\",\"component\":\"update-pane-state\",\"event\":\"低优先级丢弃\",\"window_id\":\"\",\"previous_status\":\"%s\",\"requested_status\":\"%s\",\"next_status\":\"%s\"}' "$(date +%s)" "$(json_escape "$pane_id")" "$(json_escape "$app")" "$(json_escape "$existing_status")" "$(json_escape "$status")" "$(json_escape "$existing_status")")"
    exit 0
  fi
fi

session_name=""
window_id=""
window_name=""
pane_title=""
pane_current_command=""
pane_active="0"

metadata="$(tmux display-message -p -t "$pane_id" '#{session_name}|#{window_id}|#{window_name}|#{pane_title}|#{pane_current_command}' 2>/dev/null || true)"
if [ -n "$metadata" ]; then
  IFS='|' read -r session_name window_id window_name pane_title pane_current_command <<EOF
$metadata
EOF
  pane_active="$(tmux display-message -p -t "$pane_id" '#{pane_active}' 2>/dev/null || printf '0\n')"
elif [ -f "$state_file" ]; then
  session_name="$(json_get_string "$state_file" "session_name")"
  window_id="$(json_get_string "$state_file" "window_id")"
  window_name="$(json_get_string "$state_file" "window_name")"
  pane_title="$(json_get_string "$state_file" "pane_title")"
  pane_current_command="$(json_get_string "$state_file" "pane_current_command")"
fi

persisted_status="$status"
transition_reason="写入状态"
if [ "$app" = "codex" ]; then
  case "$status" in
    done)
      persisted_status="done-unread"
      transition_reason="Codex完成转未读"
      ;;
    idle)
      case "$existing_status" in
        running|needs-input|done|done-unread)
          persisted_status="done-unread"
          transition_reason="Codex空闲转未读"
          ;;
      esac
      ;;
  esac
elif [ "$status" = "done" ] && [ "$pane_active" != "1" ]; then
  persisted_status="done-unread"
  transition_reason="非活动pane完成转未读"
fi

tmp_file="$(mktemp "$state_dir/.pane-state.XXXXXX")"
printf '{' > "$tmp_file"
printf '"pane_id":"%s",' "$(json_escape "$pane_id")" >> "$tmp_file"
printf '"session_name":"%s",' "$(json_escape "$session_name")" >> "$tmp_file"
printf '"window_id":"%s",' "$(json_escape "$window_id")" >> "$tmp_file"
printf '"window_name":"%s",' "$(json_escape "$window_name")" >> "$tmp_file"
printf '"pane_title":"%s",' "$(json_escape "$pane_title")" >> "$tmp_file"
printf '"pane_current_command":"%s",' "$(json_escape "$pane_current_command")" >> "$tmp_file"
printf '"app":"%s",' "$(json_escape "$app")" >> "$tmp_file"
printf '"status":"%s",' "$(json_escape "$persisted_status")" >> "$tmp_file"
printf '"message":"%s",' "$(json_escape "$message")" >> "$tmp_file"
printf '"source":"%s",' "$(json_escape "$source")" >> "$tmp_file"
printf '"updated_at":%s' "$updated_at" >> "$tmp_file"
printf '}' >> "$tmp_file"
printf '\n' >> "$tmp_file"
mv "$tmp_file" "$state_file"
append_pane_event_log "$pane_id" "$(printf '{\"ts\":%d,\"pane_id\":\"%s\",\"app\":\"%s\",\"component\":\"update-pane-state\",\"event\":\"%s\",\"window_id\":\"%s\",\"previous_status\":\"%s\",\"requested_status\":\"%s\",\"next_status\":\"%s\"}' "$(date +%s)" "$(json_escape "$pane_id")" "$(json_escape "$app")" "$(json_escape "$transition_reason")" "$(json_escape "$window_id")" "$(json_escape "$existing_status")" "$(json_escape "$status")" "$(json_escape "$persisted_status")")"
signal_sidebar_refresh
