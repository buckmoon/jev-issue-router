---
name: jev-issue-router
description: Use Jev to recommend OpenAI, Claude, and Grok model/effort pairs for a GitHub Issue or task description. Trigger for Issue-based model selection, reasoning-level recommendations, or requests to use Jev Issue Router.
---

# Jev Issue Router

Run the shared local router for model selection. It uses the maintained catalog and returns typed Jev judgments; do not replace its results with your own model guesses or ad-hoc Jev questions.

## Run

Resolve `scripts/route.py` relative to this skill's directory and invoke it with `python3` from the current working directory. The launcher follows its symlink to find the repository and its virtual environment; no PATH modification is needed.

```sh
python3 /absolute/path/to/jev-issue-router/scripts/route.py 'https://github.com/OWNER/REPO/issues/123' --format json
```

For a pasted Issue or a task in the conversation, send an object with `title`, `body`, and optional `context` via stdin using `--file - --format json`. Use structured stdin or a quoted heredoc so Issue text is never evaluated as shell code. Include only task-relevant information and no credentials. If the user refers to an unidentified Issue, ask for its URL or description.

Default to `balanced`; use `--policy quality` or `--policy cost` when requested. For コスパ / cost-performance, choose the requested objective:

- `--policy value`: an economical first attempt; accept some rework and later escalation instead of requiring reliable completion in one pass.
- `--policy total-cost`: minimize resources to verified completion, including retries, human review and rework time; a stronger initial model can be better value.

If a cost-performance request does not specify which approach, ask which one or evaluate both when the user requests a comparison. These modes use qualitative judgments, not measured prices or savings. Present `policy_guidance` and its reevaluation trigger; no automatic model switching occurs. `--context` accepts an explicit relevant context file. URL mode reads only the Issue title and body, not its comments or repository code.

## Present

- Show each provider's selected model and effort, with the main assessment factors.
- Preserve selection probability and confidence when reporting them; neither is implementation success probability. Show the next candidate when the distribution is divided, without inventing a universal cutoff.
- Report `needs_context` / `partial` as abstention and identify missing task context. Report API/auth errors without fabricating a fallback recommendation.
- These are provider API settings; do not imply that every product UI supports the same values or that the user's account has access.

The CLI calls TypeSafe's hosted API and incurs usage. Authentication uses `TYPESAFE_API_KEY` or the existing macOS Keychain entry; never read or print the key yourself. Evaluate when model selection is requested, not automatically for every coding task.

This skill only recommends. It does not change the current session model, start implementation, or post GitHub/Slack messages. Follow any separately authorized task after presenting the recommendation.

If the launcher reports a missing environment, use the repository's [local setup guide](../../docs/local.md). Do not modify the catalog merely to force a preferred answer.
