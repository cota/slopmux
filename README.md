# slopmux - the slop-generator multiplexer

Slopmux creates small, independent Git checkouts for coding agents and opens
them in tmux windows. Each agent repository has its own objects, refs, config,
index, HEAD, and reflogs; it has no remote or alternate object store pointing
back to the parent repository.

Run the commands from a Git working tree:

```sh
slopmux-new foo main --tool codex
slopmux-new bar main -t claude
slopmux-ls
slopmux-sync foo bar
slopmux-rm foo bar
```

`slopmux-new NAME [BASE_BRANCH]` creates the checkout and publishes its initial
assigned branch in the parent. `slopmux-sync [NAME...]` explicitly publishes
new commits. Publication is fast-forward-only: rebased, reset, amended, or
otherwise divergent agent history is refused. With no names, `slopmux-sync`
synchronizes every registered agent.

`slopmux-ls` is observational and reports each agent as `ok`, `different`,
`unpublished`, or `missing`. It never synchronizes anything.

`slopmux-rm` performs a final synchronization before deleting a checkout. It
refuses dirty checkouts, detached or unexpected HEADs, extra refs, missing
repositories, and attempts made from inside the checkout. Ignored files are
disposable. Use `-b` or `--delete-branch` to also delete the synchronized
parent branch:

```sh
slopmux-rm --delete-branch foo
```

## Requirements

Git, tmux, Bash, and `flock`.

## Configuration

Slopmux reads these Git settings:

- `slopmux.baseBranch` (default: `master`)
- `slopmux.branchPrefix` (default: empty)
- `slopmux.checkoutRoot` (default: `~/.slopmux/checkouts`)
- `slopmux.sandboxCommand` (default: unset)

Settings may be global or local to a parent repository:

```sh
git config --global slopmux.checkoutRoot ~/agent-checkouts
git config slopmux.baseBranch main
git config slopmux.branchPrefix slop/
```

Changing `slopmux.checkoutRoot` affects only new agents. Existing agents remain
discoverable through the registry in `.git/slopmux`. Checkout paths in that
registry are absolute, so moving the parent directory also leaves existing
agents usable.

Checkout roots are partitioned by the parent's basename. A
`.slopmux-parent` ownership file prevents two live parents with the same
basename from sharing one root. If the recorded parent path no longer exists,
Slopmux treats the repository as moved and updates the ownership file during
the next agent creation.

### Sandbox configuration

For protection from an untrusted agent, configure a sandbox which exposes only
the agent checkout read/write and hides the parent, registry, and sibling
checkouts:

```sh
git config --local slopmux.sandboxCommand /absolute/path/to/launcher
```

The launcher receives the selected tool as its argument and starts from the
agent checkout. It owns the complete sandbox policy, including mounts,
networking, environment variables, and agent-specific safety flags. The path
must be absolute (a leading `~` is expanded by Git), executable, and preferably
outside repository-controlled content.

Without a sandbox, Git state is isolated but the checkout is not an operating
system security boundary: a same-user process can still open other paths.

## Installation

```sh
mkdir -p "$HOME/.local/bin"
ln -s "$PWD/slopmux-new" "$PWD/slopmux-ls" "$PWD/slopmux-sync" \
    "$PWD/slopmux-rm" "$HOME/.local/bin/"
```

The commands resolve their shared helper through these symlinks, so leave the
Slopmux checkout in place. Ensure `~/.local/bin` is in `PATH`. Use `-h` or
`--help` with any command for usage.
