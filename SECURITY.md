# Security policy

## Supported versions

Security fixes are made on the latest `main` branch. Update to a reviewed current
commit; older snapshots do not have a separate security maintenance period.

## Reporting a vulnerability

Do not put vulnerabilities, credentials, or private Issue content in a public Issue
or pull request. When private vulnerability reporting is enabled, use
[Report a vulnerability](https://github.com/buckmoon/jev-issue-router/security/advisories/new).
If that form is unavailable (including before this repository becomes public),
contact a repository administrator through an existing private channel to arrange
a private report. Do not publish the details as a workaround.

Include the affected commit, a description of the impact, and minimal reproduction
steps using synthetic data. Remove secrets and personal data from attachments.
Response times are best effort; no fixed response SLA is promised.

## Data and credentials

The router sends the supplied Issue title, body, and explicit context to TypeSafe/Jev.
With `--repo` (or a repository folder in the macOS app) it also sends repository metadata:
file counts, path names, branch name and recent commit subjects. File contents are not read.
Use only data you are authorized to send. Keep API keys in environment variables,
GitHub Actions Secrets, or the supported macOS Keychain entry; never commit them.
If a real credential leaks, revoke or rotate it at its issuer first. Deleting the
file or Git history alone does not invalidate the credential.

The router recommends models; it does not execute the recommended providers.
See [security operations](docs/security.md) for setup and maintainer checks.
