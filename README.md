# slopmux - the slop-generator multiplexer

Command-line helpers for running slop generators (agents) in isolated Git
worktrees and tmux windows. Agents can optionally be launched through a
user-provided sandbox command.

Run these tools from a Git repo. `slopmux-new` creates the repo's agent
worktrees, `slopmux-ls` lists them, and `slopmux-rm` removes them.

## Requirements

Git, tmux, and Bash.

## Example

Create two agent worktrees from the `example` repo's `main` branch, launching
Codex in one and Claude in the other:

```sh
cd path/to/example
slopmux-new foo main --tool codex
slopmux-new bar main -t claude
```

Each agent opens in a new, named tmux window. The window section of the tmux
status bar might then look like this:

```text
0:shell  1:[codex]foo  2:[claude]bar
```

List the agent worktrees for the current repository:

```console
$ slopmux-ls
AGENT                     TOOL      BRANCH                            WORKTREE
foo                       codex     slop/foo                          /home/alice/my-worktrees/example/foo
bar                       claude    slop/bar                          /home/alice/my-worktrees/example/bar
```

Remove both worktrees when they are no longer needed:

```sh
slopmux-rm foo bar
```

Pass `-b` or `--delete-branch` to remove their branches as well instead:

```sh
slopmux-rm --delete-branch foo bar
```

## Configuration

Slopmux reads these settings from Git config:

- `slopmux.baseBranch` (default: `master`)
- `slopmux.branchPrefix` (default: empty string)
- `slopmux.worktreeRoot` (default: `~/.slopmux/worktrees`)
- `slopmux.sandboxCommand` (default: unset)

The worktree root controls where new agents are created. Existing agents remain
discoverable by their metadata if it changes.

Slopmux stores that metadata as the worktree-specific `slopmux.name` and
`slopmux.tool` Git config values.

Settings can be global or specific to the current repository:

```sh
git config --global slopmux.worktreeRoot ~/my-worktrees
git config slopmux.baseBranch main
git config slopmux.branchPrefix slop/
```

### Sandbox configuration

To use Bubblewrap, Firejail, or any other sandbox, provide an executable
launcher and select it for the repository:

```sh
git config --local slopmux.sandboxCommand /path/to/my-sandbox-launcher
```

The configured executable receives the agent command as its arguments and is
launched from the worktree. It owns the entire sandbox policy, including
mounts, networking, environment variables, and shell initialization. The path
must be absolute; Git expands a leading `~` when reading the setting. Note that
keeping the launcher inside the repository is dangerous, because
repository-controlled content could modify its own sandbox policy.

The launcher is also responsible for any agent-specific arguments needed to
change the agent's built-in protections; `slopmux-new` never adds such
arguments.

Use `-h` or `--help` with any command to print its usage.

## Installation

```sh
mkdir -p "$HOME/.local/bin"
ln -s "$PWD/slopmux-new" "$PWD/slopmux-ls" "$PWD/slopmux-rm" \
    "$HOME/.local/bin/"
```

Run this from the Slopmux checkout and leave the checkout in place so the
symlinks remain valid. Make sure `~/.local/bin` is in your `PATH`, then
configure Git as described above.
