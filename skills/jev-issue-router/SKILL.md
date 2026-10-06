---
name: jev-issue-router
description: Use Jev (or Cloudflare Clef when requested) to recommend OpenAI, Claude, and Grok model/effort pairs for a GitHub Issue or task description. Trigger for Issue-based model selection, reasoning-level recommendations, or requests to use Jev Issue Router.
---

# Jev Issue Router

Run the shared local router for model selection. It uses the maintained catalog and returns typed judgments from its evaluator (Jev by default, or Clef); do not replace its results with your own model guesses or ad-hoc Jev questions.

## Run

Always use the launcher below. It fetches `issue_router/catalog.json` from the public repository main on every invocation, bypasses the bundled catalog and stops on fetch/validation failure without stale fallback. Report the resulting catalog version and verification date; latest published catalog does not mean every provider model was verified today. Do not pass `--catalog` or invoke the old private checkout directly.

Resolve `scripts/route.py` relative to this skill's directory and invoke it with `python3` from the current working directory. The launcher follows its symlink to find the repository and its virtual environment; no PATH modification is needed.

```sh
python3 /absolute/path/to/jev-issue-router/scripts/route.py 'https://github.com/OWNER/REPO/issues/123' --format json
```

For a pasted Issue or a task in the conversation, send an object with `title`, `body`, and optional `context` via stdin using `--file - --format json`. Use structured stdin or a quoted heredoc so Issue text is never evaluated as shell code. Include only task-relevant information and no credentials. If the user refers to an unidentified Issue, ask for its URL or description.

Default to `balanced`; use `--policy quality` or `--policy cost` when requested. For コスパ / cost-performance, choose the requested objective:

- `--policy value`: an economical first attempt; accept some rework and later escalation instead of requiring reliable completion in one pass.
- `--policy min-cost`: lowest model spend above all else; accepts retries and partial results. Use only when the user asks to minimize cost outright.
- `--policy max-quality`: design quality above all else, ignoring cost; the model is fixed to each provider's most capable and Jev selects only the effort. Say so when presenting the result.
- `--policy total-cost`: minimize resources to verified completion, including retries, human review and rework time; a stronger initial model can be better value.

If a cost-performance request does not specify which approach, ask which one or evaluate both when the user requests a comparison. These modes use qualitative judgments, not measured prices or savings. Present `policy_guidance` and its reevaluation trigger; no automatic model switching occurs. `--context` accepts an explicit relevant context file. When the task targets a local Git checkout the user is working in, add `--repo PATH` so repository metadata (structure, tests, CI, Git state, paths matching issue terms; never file contents) informs the judgment; path names and commit subjects are sent to the evaluator, so skip it if the user has said the repository must not be shared. URL mode reads only the Issue title and body, not its comments or repository code.

## Evaluator

Jev is the default. Add `--evaluator clef` only when the user asks for Clef; add `--clef-host local` when they want it run on a local System One server (Ollama, vLLM, llama.cpp), which sends nothing externally. Clef on Workers AI sends the Issue to Cloudflare and incurs usage; it needs `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` (or the `local.clef.cloudflare` Keychain entry).

Clef has two models, `clef` (27B) and `clef-flash` (9B). `--clef-model` sets the selection stage and defaults the assessment stage; `--clef-assess-model` overrides the assessment stage only:

- accuracy first (default): no extra flags (`clef` / `clef`); prefer it for weighty policies such as `max-quality` or `total-cost`.
- fast: `--clef-model clef-flash` when the user asks for speed or low cost, e.g. many Issues.
- tiered: `--clef-assess-model clef-flash` (assessment `clef-flash` → selection `clef`) for faster interactive use.

These pairings are uncalibrated hypotheses. Present the result's `evaluator` field and its "uncalibrated" warning as returned. When the user asks to compare Jev and Clef, run both on the same input and show the results side by side; never fall back from one to the other on failure.

## Present

- Show each provider's selected model and effort, with the main assessment factors.
- Preserve selection probability and confidence when reporting them; neither is implementation success probability. Show the next candidate when the distribution is divided, without inventing a universal cutoff.
- Report `needs_context` / `partial` as abstention and identify missing task context. Report API/auth errors without fabricating a fallback recommendation.
- These are provider API settings; do not imply that every product UI supports the same values or that the user's account has access.

The CLI calls TypeSafe's hosted API (or Cloudflare Workers AI with `--evaluator clef`) and incurs usage. Authentication uses `TYPESAFE_API_KEY` / `CLOUDFLARE_API_TOKEN` or the matching macOS Keychain entry; never read or print a key or token yourself. Evaluate when model selection is requested, not automatically for every coding task.

This skill only recommends. It does not change the current session model, start implementation, or post GitHub/Slack messages. Follow any separately authorized task after presenting the recommendation.

If the launcher reports a missing environment, use the repository's [local setup guide](../../docs/local.md). Do not modify the catalog merely to force a preferred answer.
