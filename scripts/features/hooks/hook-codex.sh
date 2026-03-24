#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
SCRIPTS_DIR="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
. "$SCRIPTS_DIR/core/hook-lib.sh"
update_helper="${TMUX_SIDEBAR_UPDATE_HELPER:-$SCRIPTS_DIR/features/state/update-pane-state.sh}"
forward_notify="${TMUX_SIDEBAR_CODEX_NOTIFY_FORWARD:-${CLAUDE_CONFIG_DIR:-$HOME/.claude}/hooks/peon-ping/adapters/codex.sh}"

legacy_event="${CODEX_EVENT:-}"
legacy_status="${CODEX_STATUS:-}"
legacy_message="${CODEX_MESSAGE:-}"

resolve_hook_input "${1:-}" "${2:-}"

if [ -x "$forward_notify" ]; then
  printf '%s' "$hook_payload" | "$forward_notify" "$hook_event" || true
fi

if [ -n "$legacy_event$legacy_status$legacy_message" ]; then
  hook_status=""
  case "$legacy_event" in
    agent-turn-complete|complete|completed|done|finish|finished|stop|stopped|task-complete|turn-complete|session-end)
      hook_status="done"
      ;;
    error|fail|failure)
      hook_status="error"
      ;;
    permission*|approve*|approval-requested|input-required)
      hook_status="needs-input"
      ;;
    idle-prompt)
      hook_status="idle"
      ;;
  esac

  if [ -z "$hook_status" ]; then
    case "$legacy_status" in
      running)
        hook_status="running"
        ;;
      error|failed)
        hook_status="error"
        ;;
      done|completed|finished|stopped)
        hook_status="done"
        ;;
      needs-input)
        hook_status="needs-input"
        ;;
      idle)
        hook_status="idle"
        ;;
    esac
  fi

  [ -n "$hook_status" ] || exit 0

  exec "$update_helper" \
    --pane "${TMUX_PANE:-}" \
    --app codex \
    --status "$hook_status" \
    --message "$legacy_message"
fi

parse_hook_result codex "$hook_event"
[ -n "$hook_status" ] || exit 0

exec "$update_helper" \
  --pane "${TMUX_PANE:-}" \
  --app codex \
  --status "$hook_status" \
  --message "$hook_message"
