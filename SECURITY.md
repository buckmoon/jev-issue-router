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

The router sends the supplied Issue title, body, and explicit context to the selected
evaluator: TypeSafe/Jev (default), Cloudflare Workers AI/Clef, or a Clef server you
configure. A local Clef server on loopback (the default `CLEF_URL`) receives the data
without it leaving the machine; any other Clef server must use https. Workers AI
processing follows Cloudflare's terms and logging settings and incurs Cloudflare usage.
With `--repo` (or a repository folder in the macOS app) it also sends repository metadata:
file counts, path names, branch name and recent commit subjects. File contents are not read.
Use only data you are authorized to send.

Credentials per evaluator: `TYPESAFE_API_KEY` (Keychain `local.jev.typesafe`) for Jev;
`CLOUDFLARE_API_TOKEN` (Keychain `local.clef.cloudflare` on macOS and iOS) plus the
non-secret `CLOUDFLARE_ACCOUNT_ID` for Workers AI; optionally `CLEF_API_KEY` for a
local server that requires one. Scope the Cloudflare token to Workers AI on the target
account only. In GitHub Actions, pass the token as an Actions Secret and the account ID
as a variable; the Action requires only the selected evaluator's secret and stops
before reading the Issue when it is missing. Keep API keys in environment variables,
GitHub Actions Secrets, or the supported Keychain entries; never commit them. Tokens
and the account ID are never written to results, drafts, settings files or logs, and
error messages carry HTTP status or Cloudflare's numeric error codes only, never
response bodies. There is no automatic fallback between Jev and Clef.
The optional model watcher reads provider model lists with `OPENAI_API_KEY`,
`ANTHROPIC_API_KEY` and `XAI_API_KEY`; it never sends Issue text to those providers.
If a real credential leaks, revoke or rotate it at its issuer first. Deleting the
file or Git history alone does not invalidate the credential.

The router recommends models; it does not execute the recommended providers.
See [security operations](docs/security.md) for setup and maintainer checks.
