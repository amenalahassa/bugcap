---
name: validate-pr
description: Validate an external contribution PR to bugcap before approving/merging — reads the diff, cross-checks it against the linked issue, actually applies it locally and runs the test suite and ruff, and reports a clear approve/changes-needed verdict. Use this whenever the user asks to review, check, validate, or "resume" a pull request, or mentions a PR waiting for approval/review — not just for code-style nits, but to verify the contributor's claims (tests pass, lint clean) are actually true on this machine.
metadata:
  author: konrad
---

# Validate a contribution PR

Contributors' PR descriptions make claims ("tests pass", "ruff is clean"). Trust but verify: this
skill's job is to actually reproduce those claims locally, not just read the diff and take their
word for it. A PR can look clean in the diff and still fail in practice (wrong Python version,
stale lockfile, a test that only passes because it was never run).

## Inputs

The user may give a PR number, a branch name, or nothing (if nothing, and there is exactly one
open PR requesting the user's review, use that one; if there are several, ask which).

## Steps

1. **Read the PR and its linked issue.**
   ```
   gh pr view <N>
   gh pr diff <N>
   ```
   If the PR body references an issue (`Fixes #N`, `Closes #N`), run `gh issue view <N>` and check
   the diff actually does what the issue asked — no more, no less. Scope creep (unrelated
   refactors, extra files) is worth flagging even if the code itself is fine.

2. **Get the changes onto disk without touching the user's working tree.**
   Don't assume `git fetch`/`gh pr checkout` will work — SSH remotes often aren't authenticated
   in this environment. The reliable path:
   ```
   git status --short          # must be clean before you touch branches
   git checkout -b pr-<N>-review
   gh pr diff <N> > /tmp/pr<N>.diff
   git apply /tmp/pr<N>.diff
   ```
   If `git apply` fails, fall back to `gh pr checkout <N>` (works when SSH is fine) or ask the user.

3. **Reproduce the contributor's claims.** Run whatever the project uses for tests/lint — check
   `pyproject.toml` / `CONTRIBUTING.md` if unsure, but for bugcap it's:
   ```
   uv run pytest -q
   uv run ruff check src tests
   git diff --check          # trailing whitespace / conflict markers
   ```
   A failure here is only a real finding if it's caused by the PR. Confirm by stashing the
   applied patch and re-running the same failing test on the base branch — if it fails there too,
   it's a pre-existing/environmental issue, not the contributor's fault. Say so explicitly either
   way; don't let an unrelated failure block an otherwise-good PR, and don't wave away a failure
   the PR actually introduced.

4. **Read the actual code change, not just the test result.** Passing tests don't catch everything
   worth catching in a review:
   - Does the fix address the root cause, or just the specific case in the test?
   - Are there other call sites of the same function/pattern that should have gotten the same
     treatment (or that were correctly left alone — say which and why)?
   - Any new dependency, secret, absolute path, or behavior change not called out in the PR body?
   - Do docs/changelog actually match what the code now does?

5. **Clean up.** Return the repo to the state it was in before the review:
   ```
   git checkout <original-branch>
   git branch -D pr-<N>-review
   git checkout -- .          # discard anything the patch left uncommitted
   git status --short         # confirm clean
   ```
   Never leave the applied patch sitting uncommitted on the user's real branch.

## Verdict

End with a short, direct verdict — not a wall of findings. Structure:

- **Approve / Changes needed / Blocked** — one line.
- What you actually verified (tests run, ruff run, issue cross-checked) vs. what you're taking on
  faith (e.g., "didn't test on Linux/macOS, only this Windows host").
- Any concrete blockers, each tied to a file/line.

Keep it to what the user needs to decide — they can read the diff themselves; your value is the
verification they can't easily do by eye.
