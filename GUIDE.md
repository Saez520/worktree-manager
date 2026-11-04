# Worktree manager guide

Before you touch the main branch, offer to create an isolated worktree: create it with worktree_create, do all the work inside it, and close it with worktree_complete to integrate or worktree_cleanup to discard. If the worktree cannot be created or closed, correct the cause named in the error message before retrying.

## The flow

1. List the worktrees registered for the repository with `worktree_list` and reuse an existing work identifier when one is already open.
2. Before changing anything, create the isolated worktree and its branch with `worktree_create`. The main branch stays untouched while the work is in progress.
3. Do the work inside the worktree and commit there. The main branch does not receive the changes until the work is closed.
4. Close the work: use `worktree_complete` to integrate the commits into the base branch or `worktree_cleanup` to discard them without integrating. Check `worktree_status` before closing and use `worktree_recover` when an earlier create or complete was interrupted.

## The seven operations

The MCP service exposes exactly seven operations:

- `worktree_create`: Creates an isolated worktree and its branch for a work identifier; use it before starting a change, spec, or flow so the base branch stays untouched.
- `worktree_complete`: Integrates the worktree into the base branch and removes it; use it when the isolated work is finished and should land on the base branch.
- `worktree_cleanup`: Removes the worktree and its branch without integrating; use it to discard abandoned work and, with discard and discard_consent, its uncommitted changes.
- `worktree_recover`: Continues a pending transaction by its identifier; use it after an interrupted create or complete before starting another operation.
- `worktree_list`: Lists the worktrees registered for the repository; use it to find existing work identifiers before creating or closing one.
- `worktree_prune`: Removes worktree records whose directories no longer exist; use it after deleting a worktree by hand to clean the stale registration.
- `worktree_status`: Reports one work item's worktree, journal transactions, and pending intervention; use it before completing or cleaning up to confirm the current state.

All of them require an absolute Git repository path in `repo`.

## Launch without shortcuts

The package exposes no shortcut launcher. The MCP service is launched with Node and the absolute package path:

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

## When a call fails

### The repository path is not absolute

Symptom: the call returns `isError: true`, `error.code` is `invalid_request`, and `error.message` is `repo_must_be_absolute`.

Correction: pass the absolute path of the repository in `repo`. The operation creates nothing when the path is relative.

### The worktree has uncommitted changes

Symptom: the closing call returns `error.code` `intervention_required`, the message reports uncommitted changes in the worktree, and the worktree is retained.

Correction: commit the changes inside the worktree and retry `worktree_complete`. To throw the changes away instead, use `worktree_cleanup` with `discard: true` and `discard_consent: true`.

### The call has no authorization

Symptom: the call returns `error.code` `authorization_required` and nothing is mutated.

Correction: send `authorization: "I_AUTHORIZE_THIS_CALL"` or `confirm: true` in the same call. Authorization is not retained between calls, so every mutating call needs its own.
