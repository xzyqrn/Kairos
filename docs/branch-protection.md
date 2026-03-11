# Branch Protection Checklist

Use this in GitHub repository settings for your default branch (typically
`main`) to enforce quality gates.

## Recommended Settings

- Require a pull request before merging
- Require approvals: at least 1
- Dismiss stale pull request approvals when new commits are pushed
- Require review from code owners (if CODEOWNERS is configured)
- Require conversation resolution before merging
- Require status checks to pass before merging
- Require branches to be up to date before merging
- Do not allow force pushes
- Do not allow deletions

## Required Status Checks

After CI runs at least once, add these checks:

- `quality (3.11)`
- `quality (3.12)`

These map to `.github/workflows/ci.yml`.

## Optional Hardening

- Include administrators in branch protection
- Enable merge queue for high-traffic repos
- Restrict who can push to matching branches

