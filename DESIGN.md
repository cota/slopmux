# Slopmux design

Slopmux gives every agent an independent Git repository and explicitly
publishes its assigned branch into the parent. User-facing behavior is in
[README.md](README.md); this file records the invariants behind it.

## Invariants

- A checkout owns its objects, refs, config, index, HEAD, and reflogs.
- It has no alternates or persistent remote pointing to slopmux state.
- The parent registry is authoritative; checkout metadata and root scans are
  not used for discovery.
- The checkout branch is authoritative. Its parent branch is only a published
  copy, updated by fast-forward unless the user explicitly requests force.
- Failed or interrupted operations prefer visible stale state over forgotten or
  destroyed work.

This isolates Git operations, not filesystem access. Untrusted agents still
need a sandbox hiding the parent, registry, and sibling paths.

## State

```text
parent/.git/slopmux/
├── version
├── lock
└── agents/<name>/{checkout,branch,tool}

<checkoutRoot>/<parent-basename>/
├── .slopmux-parent
├── .slopmux-lock
└── <agent>/.git/
```

Registry checkout paths are absolute. Changing `slopmux.checkoutRoot` therefore
affects only new agents, and moving the parent leaves existing records valid.

The ownership file stores the parent's canonical path. A different live path
is a basename collision and is refused; a missing old path is treated as a
move. Copying a parent with active slopmux metadata is unsupported.

Mutations hold the parent registry `flock`; creation also holds the basename
lock. Records and ownership files are installed through temporary-file renames.
Missing checkouts remain registered and visible.

## Lifecycle

Creation initializes a temporary repository, fetches only the selected parent
branch, resets the assigned branch to `FETCH_HEAD`, installs the checkout, and
registers it. The initial branch is published before tmux starts. A launch
failure leaves the valid checkout registered.

Publication fetches exactly the assigned checkout branch into its matching
parent branch. By default, Git permits creation and fast-forwards while
refusing divergence and checked-out destinations. `slopmux-sync --force`
allows non-fast-forward updates; creation and removal still publish without
force.

Removal requires a valid repository on its assigned branch, a clean working
tree, no extra refs, a caller outside the checkout, and a successful final
publication. Ignored files are disposable. The checkout is deleted before its
record. `--delete-branch` uses the synchronized OID as the expected old value.

## Deliberate limits

Version 1 has no object cache, alternates, automatic publication,
linked-worktree migration, or special handling for LFS, submodules, shallow
clones, and partial clones. These features are deferred to keep the design
simple.
