You are going to implement a change, run a spec, or start a flow. Do you want to create a worktree to work in isolation?

This guide explains how to use the `worktree-for-agents` manager to work
isolated in a worktree before touching the main branch.

## The seven tools

The MCP service exposes exactly seven tools:

- `worktree_create`: creates a worktree and its branch for a work identifier.
- `worktree_complete`: merges the worktree into the base branch and removes the worktree.
- `worktree_cleanup`: removes the worktree and its branch without merging.
- `worktree_recover`: recovers a pending transaction by its identifier.
- `worktree_list`: lists the repository worktrees.
- `worktree_prune`: prunes worktree information that no longer exists.
- `worktree_status`: shows the status of a work item.

All of them require an absolute Git repository path in `repo`.

## When to offer the worktree

Before working on the main branch, offer to create a worktree with
`worktree_create`. Work inside the worktree and then merge with
`worktree_complete`. If the work is discarded, use `worktree_cleanup`.

## Launch without bin

The package exposes no bin or `npx`. The MCP service is launched with Node and the
absolute package path:

```sh
node <package>/mcp-server.mjs
```

The CLI is launched the same way:

```sh
node <package>/worktree.mjs --version
```

The installation diagnostics are obtained with:

```sh
node <package>/setup.mjs
```
