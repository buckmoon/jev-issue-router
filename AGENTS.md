# Working on Jev Issue Router

- Read README.md, then the relevant guide in docs/. Start with `git status --short`.
- Keep recommendation logic in issue_router/core.py. CLI, Slack and Actions share that engine.
- The iOS app in ios/ is a Swift port of that engine. Update ios/JevIssueRouter/Engine/ and ios/sync-catalog.sh whenever rubrics, policies, the catalog, the evaluators (issue_router/evaluators.py) or the result JSON change, and keep tests/test_ios.py green.
- The evaluator (Jev, or Clef on Workers AI or a local server) selects typed choices. Never fabricate recommendations or convert confidence into success probability. Keep the Jev and Clef request bodies identical except for `model`, and never add automatic fallback between them.
- Catalog model IDs, supported effort settings and source dates require official documentation evidence. Routing descriptions are hypotheses until calibrated.
- Do not print keys, tokens, raw external error bodies or private Issue text in logs. Never add secrets to tests.
- Normal tests use fake transports. A real Jev or Clef Workers AI evaluation sends data externally and incurs usage; use synthetic examples for smoke tests. Clef on a local loopback server sends nothing externally, but tests still use fakes and never connect to Ollama or other local servers.
- Validate with `python -m unittest discover -s tests -v`, `ruff check .`, `actionlint`, and a package build when packaging changes.
- Preserve unrelated edits. Do not post Issue/Slack messages as a side effect of tests.

- Maintainer commits to this public repository must use the configured GitHub noreply email. Check author and committer metadata before pushing. Never merge or push the old private repository history into this repository; transfer changes as reviewed patches instead.
