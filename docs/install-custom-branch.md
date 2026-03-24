# Install Your Custom tmux-sidebar Build

This guide shows how to save your current sidebar changes, publish them, and
install that exact build on another machine.

The examples below use the current working branch:

```text
codex/sidebar-width-separators
```

## Option 1: Publish to your own Git remote

This is the best option if you want the second machine to be able to `git
clone` or `git pull` updates later.

### 1. Commit your documentation or code changes

From the repo root:

```bash
git status
git add README.md docs/install-custom-branch.md
git commit -m "docs: add custom branch installation guide"
```

If the working tree is already clean, you can skip this step.

### 2. Push the branch to a fork or your own repository

If you already have a writable remote, push the branch:

```bash
git push -u <your-remote> codex/sidebar-width-separators
```

If `origin` still points at the upstream project and you do not have push
permission there, create your own fork first and then either:

```bash
git remote rename origin upstream
git remote add origin git@github.com:<your-user>/tmux-sidebar.git
git push -u origin codex/sidebar-width-separators
```

or keep the upstream remote and add a second one:

```bash
git remote add myfork git@github.com:<your-user>/tmux-sidebar.git
git push -u myfork codex/sidebar-width-separators
```

### 3. Install that branch on another machine

On the second machine:

```bash
mkdir -p ~/.tmux/plugins
git clone --branch codex/sidebar-width-separators --single-branch \
  git@github.com:<your-user>/tmux-sidebar.git \
  ~/.tmux/plugins/tmux-sidebar
```

Add this line to `~/.tmux.conf` if it is not already present:

```tmux
source-file ~/.tmux/plugins/tmux-sidebar/sidebar.tmux
```

Reload tmux:

```bash
tmux source-file ~/.tmux.conf
```

Then open the sidebar with:

```text
prefix + T
```

## Option 2: Save and move the branch with a git bundle

Use this if you want a single portable file and do not want to publish to
GitHub yet.

### 1. Create the bundle on the source machine

```bash
git bundle create tmux-sidebar.bundle codex/sidebar-width-separators
```

Copy `tmux-sidebar.bundle` to the second machine with AirDrop, `scp`, a shared
folder, or any other file transfer method.

### 2. Clone from the bundle on the second machine

```bash
mkdir -p ~/.tmux/plugins
git clone --branch codex/sidebar-width-separators \
  ./tmux-sidebar.bundle \
  ~/.tmux/plugins/tmux-sidebar
```

Then add the same tmux config line:

```tmux
source-file ~/.tmux/plugins/tmux-sidebar/sidebar.tmux
```

Reload tmux:

```bash
tmux source-file ~/.tmux.conf
```

## Requirements on the second machine

- `tmux` 3.0 or newer
- `python3`
- `bash` 4.0 or newer
- A Nerd Font or Unicode-capable terminal is recommended for the badges and
  divider characters

## Optional: agent status hooks

The sidebar works without hook setup, but explicit Claude/Codex badges are more
accurate when you wire the hooks in.

- Codex hook: `scripts/features/hooks/hook-codex.sh`
- Claude hook: `scripts/features/hooks/hook-claude.sh`
- Minimal examples: `examples/codex-hook.sh`, `examples/claude-hook.sh`

If you only want the sidebar itself on the second machine, you can skip this
part and add hook integration later.

## Quick verification checklist

After installation on the second machine:

1. Run `tmux source-file ~/.tmux.conf`
2. Press `prefix + T` to open the sidebar
3. Press `prefix + t` to move focus between the sidebar and the main pane
4. If the sidebar was already open before reinstalling, close and reopen it
