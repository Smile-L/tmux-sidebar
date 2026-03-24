# Project Status

Last updated: 2026-03-24

## Overview

This repo is a locally modified copy of `tmux-sidebar`, a tmux plugin that renders a persistent interactive sidebar for sessions, windows, and panes.

The current working branch has moved the UI away from the original tree-heavy layout toward a flatter panel-style sidebar with richer summaries and stronger status signaling.

## Current Git State

- Repo path: `/Users/lisimin/.tmux/plugins/tmux-sidebar`
- Branch: `codex/sidebar-width-separators`
- Working tree: clean at the time this file was written
- Recent commits:
  - `64fc7c5` `feat: infer script execution status from tmux panes`
  - `9def179` `refactor: reduce duplicate pane labels in sidebar`
  - `cd0ef7a` `refactor: hide redundant window rows in sidebar`
  - `0570e1c` `feat: upgrade sidebar panel layout and status summaries`

## What Has Been Added

- Sidebar default width increased from `25` to `50`
- Session headers now render as full-width visual dividers
- Sidebar UI changed from classic tmux tree connectors to a flatter panel-style layout
- Selected pane expands into a richer card-like block with path/meta and preview lines
- Claude and Codex status handling improved
- Added `done-unread` status with yellow `✓`
- Added pure sidebar/tmux inference for common script execution states
  - `⏳ running`
  - `✓ done-unread`
  - `✅ done`
- Reduced redundant duplicated labels such as repeated `zsh` / `python3.12` window-and-pane rows

## Current UI Behavior

- Sessions are shown as lightweight section headers
- Window rows are shown only when they add useful structure
- Pane rows are the main navigation targets
- The selected pane expands to show:
  - title line
  - path or meta line
  - two preview/summary lines
- Summary extraction is panel-specific:
  - `codex`
  - `claude`
  - `shell`
  - `generic`

## Status Semantics

- `⏳` = `running`
- `❓` = `needs-input`
- `✓` = `done-unread`
- `✅` = `done`
- `❌` = `error`

### Current status sources

- Claude/Codex hooks can write explicit state via `scripts/features/state/update-pane-state.sh`
- Focusing a pane converts:
  - `needs-input -> idle`
  - `done-unread -> done`
- Common script/task commands are now inferred directly from tmux pane state
  - This is heuristic, not shell-hook based
  - Claude/Codex explicit states take priority over script inference

## Key Files

### Main runtime/UI

- `sidebar.tmux`
- `scripts/ui/sidebar-ui.py`
- `scripts/ui/sidebar_ui_lib/core.py`
- `scripts/ui/sidebar_ui_lib/render.py`
- `scripts/ui/sidebar_ui_lib/status.py`
- `scripts/ui/sidebar_ui_lib/tree.py`

### State and hooks

- `scripts/core/lib.sh`
- `scripts/core/hook-parser.py`
- `scripts/features/state/update-pane-state.sh`
- `scripts/features/state/clear-pane-state.sh`
- `scripts/features/sidebar/on-pane-focus.sh`
- `scripts/features/hooks/hook-codex.sh`

### Sidebar lifecycle

- `scripts/features/sidebar/toggle-sidebar.sh`
- `scripts/features/sidebar/ensure-sidebar-pane.sh`
- `scripts/features/sidebar/render-sidebar.sh`
- `scripts/features/sidebar/reload-sidebar-panes.sh`

## Local Machine Paths Related To This Setup

- tmux config: `/Users/lisimin/.tmux.conf`
- Codex config: `/Users/lisimin/.codex/config.toml`
- Claude config: `/Users/lisimin/.claude/settings.json`
- backup snapshots:
  - `/Users/lisimin/.tmux-backups/20260323-215052`
  - `/Users/lisimin/.tmux-backups/20260323-223921`

## Development Workflow

### Run all tests

```bash
bash tests/run.sh
```

### Run a single test

```bash
bash tests/run.sh tests/ui/sidebar_ui_state_test.sh
```

### Syntax checks often used during development

```bash
python3 -m py_compile scripts/ui/sidebar-ui.py scripts/ui/sidebar_ui_lib/*.py
bash -n scripts/features/sidebar/ensure-sidebar-pane.sh
```

### Live verification in tmux

```bash
bash scripts/install-live.sh
```

Then close and reopen the sidebar in tmux:

```text
prefix + t
prefix + t
```

This is necessary because an already-open sidebar pane does not hot-reload the UI code automatically.

## Testing Notes

- The repo contains both fake-tmux tests and real-tmux integration tests
- `tests/testlib.sh` provides the fake tmux harness
- `tests/integration/sidebar_real_tmux_e2e_test.sh` exercises a real tmux server
- A dedicated summary test exists at `tests/ui/sidebar_ui_summary_test.sh`

## Current Known Risks / Caveats

- Script execution badges are heuristic
  - They can still misclassify some REPL or long-lived command scenarios
  - They are best-effort for task/script panes, not strict process monitoring
- Pure tmux inference is intentionally lower confidence than explicit hook-based state writes
- Remote push from this machine may fail until GitHub credentials are configured
  - earlier push attempt failed with HTTPS auth missing

## Good Next Steps

- Further reduce false positives in script inference
  - especially Python REPL / Node REPL / nested shells
- Make selected pane styling even more card-like
- Optionally weaken window rows further
- If preparing upstream contribution:
  - verify UI in a live tmux session
  - push branch `codex/sidebar-width-separators`
  - open a PR from that branch
