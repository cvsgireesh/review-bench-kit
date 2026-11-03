# review-bench-kit

Measure any code-review bot, model or effort setting on public benchmarks and on live PRs, then decide a switch from numbers instead of impressions.

You bring a reviewer (a CLI, a script, an SDK call, or a GitHub App). The kit runs it on benchmark PRs, has LLM judges score its findings against human-verified ground truth, and compares arms with paired confidence intervals, cost and latency under a switch/keep rule you write **before** running.

```
arms.yaml ──► rbk run ──► runs/<arm>/<pr>/r<k>.json     one normalized review per PR, arm and repeat
                             │
                      rbk score   judge model(s) match findings to the golden set
                             │
decision.yaml ───────► rbk compare ──► report.md / .json     SWITCH or KEEP per candidate

real PRs of any repo ──► rbk live (before) ┐
                         rbk live (after)  ┴► rbk live-compare   what happened to the bot's real comments
```

## Datasets

All are reduced to one shape, so one judge pipeline (the [Martian](https://github.com/withmartian/code-review-benchmark) extract / dedup / judge steps, pinned) scores every dataset the same way. Pick one with `--dataset`.

| `--dataset` | PRs | Golden findings | Source (pinned commit) |
|---|---:|---|---|
| `martian` (default) | 50 | 173 human-curated | [withmartian/code-review-benchmark](https://github.com/withmartian/code-review-benchmark), MIT |
| `reviewbench` | 219 | 2,623 verified true positives, with severity | [review-bench/ReviewBench](https://github.com/review-bench/ReviewBench), MIT |
| `prbench` | 350 | 510 changes human reviewers required | [SWE-PRBench](https://huggingface.co/datasets/foundry-ai/swe-prbench) |
| `swr` | 1,000 (500 clean) | 949 bug-introducing changes | [SWR-Bench](https://github.com/ZZR0/SWRench), MIT |
| `ccrab` | 410 | 595 reference review comments | [c-CRAB](https://github.com/c-CRAB-Benchmark/dataset) |

Clean PRs (no golden findings) count every comment as a false positive, which measures noise. `recall(high)` is only meaningful on datasets that label severity (`martian`, `reviewbench`); the others label everything `Medium`.
c-CRAB's own score is test-based (a coding agent must fix the code); here it is judged like the others, by matching findings, so it is not comparable with its paper numbers.

## Install

Needs Python 3.11+, [uv](https://docs.astral.sh/uv/), `git`, and an authenticated [`gh`](https://cli.github.com/) (`gh auth login`).

```bash
git clone https://github.com/cvsgireesh/review-bench-kit && cd review-bench-kit
uv sync
uv run rbk deps --dataset martian        # clones the pinned scorer (+ the dataset source for other datasets)
```

## 1. Define your arms

An **arm** is one way of producing a review. Change one thing per arm (model, effort, prompt, tool version) and keep the rest identical.

```bash
cp examples/arms.example.yaml arms.yaml        # reviewers + judge
cp examples/decision.example.yaml decision.yaml  # the switch rule
```

An arm is a shell command run inside a checkout of the PR that writes a review file to `{out}`. Placeholders: `{repo} {base} {head} {out} {pr_url}`. `${VAR}` in `env` is read from your environment, so keys never live in the file.

| Your reviewer | What to do |
|---|---|
| **A CLI** (OpenCodeReview `ocr`, others) | `normalize: ocr` for `ocr review --format json`, otherwise `generic`. Vary model/effort with `env` and flags, one arm each. See `examples/arms.example.yaml`. |
| **Claude Code CLI** (subscription or API key) | `examples/claude_arm.sh {repo} {base} {head} {out}` with `CLAUDE_MODEL` and `CLAUDE_EFFORT` in `env`. |
| **A script or SDK** | Print the [generic format](docs/formats.md) to `{out}` and use `normalize: generic`. `examples/fake_arm.sh` is the smallest example. |
| **A hosted bot** (GitHub App / Action) | See [Hosted bots](#hosted-bots-github-apps). |

A review file is `{"comments": [{"path", "line", "body", "severity?"}], "usage": {...}}`. Exit non-zero or time out to record a failed run. **Failed runs are excluded and reported, never scored as "found nothing".**

## 2. Judges

Findings are matched to the golden set by an LLM judge. Use two judge models from different families, so one model's bias does not decide the outcome.

```yaml
judge:
  base_url: ${JUDGE_BASE_URL}     # any OpenAI-compatible endpoint
  api_key: ${JUDGE_API_KEY}
  models: [judge-a, judge-b]
```

**No API key? Use a Claude subscription.** `rbk judge-proxy` serves an OpenAI-compatible endpoint backed by your logged-in `claude` CLI (tool calls are emulated by prompting, so agent-style reviewers like `ocr` can use it as their LLM too):

```bash
uv run rbk judge-proxy --port 8799 --jobs 4 &
export JUDGE_BASE_URL=http://127.0.0.1:8799/v1 JUDGE_API_KEY=any    # models: [sonnet, haiku] ...
```

## 3. Run, score, compare

```bash
uv run rbk run     --config arms.yaml --dataset martian --reps 3 --jobs 2    # --limit 5 for a trial
uv run rbk score   --config arms.yaml --dataset martian
uv run rbk compare --config arms.yaml --dataset martian --decision decision.yaml --out report
```

- `run` is resumable: finished results are kept, failed ones retried. `--reps 3` measures run-to-run noise.
- `compare` reports precision, recall, F1/F2, recall on high-severity findings, comments per PR, seconds and dollars per PR, per judge, each difference as candidate minus baseline with a 95% paired bootstrap over PRs.
- A candidate is **SWITCH** only if every `require` rule passes under **every** judge and one `any_superior` rule passes (a switch needs a reason: cheaper, faster or better). Otherwise **KEEP**.
- Cost comes from the review's `usage.cost_usd`, or from token counts and the arm's `price` block.

Start with `--limit 5` and one judge to check cost, then run the full dataset. A 50-PR run with 3 repeats and 2 judges is hundreds of judge calls.

## Hosted bots (GitHub Apps)

A hosted bot reviews only PRs in repositories where it is installed, so each benchmark PR is replayed in a scratch repo you own:

```bash
# 1. install your bot on a scratch repo (e.g. you/review-bench-scratch), then per PR:
uv run rbk mirror  --pr-url https://github.com/keycloak/keycloak/pull/37429 --target you/review-bench-scratch
# 2. wait for the bot, then write its comments as a review file (fails if it never posts):
uv run rbk collect --pr-url <the PR url mirror printed> --bot your-bot-login --timeout 900 --out review.json
```

Wrap those two commands in a small script and use it as the arm's `cmd` (`{pr_url}` is the benchmark PR; keep the mirror URL in the script). Switch the bot's model between collections to get one arm per setting. `collect` matches inline comments, review summaries and PR comments by login (`[bot]` suffix optional). Mirrored PRs live in your scratch repo; delete it when done.

## Measure the production bot on real PRs

The offline benchmarks are static and public. To see what your bot's real comments led to, before and after a switch:

```bash
uv run rbk live --repo owner/name --bot LOGIN --until 2026-10-31 --out before.json
uv run rbk live --repo owner/name --bot LOGIN --since 2026-11-01 --out after.json --audit 25
uv run rbk live-compare before.json after.json
```

Per bot thread: accepted (author replied fixed/confirmed), rejected, code changed afterwards (outdated or resolved), no reply. Plus a recall proxy: the share of human-started review threads within `--window` lines of a bot thread. These are proxies: reply wording is matched with regexes, so read the `--audit` sample before quoting a rate. Pass other bots with `--also-bot` so they are not counted as humans. For a GitHub App, pass its login without `[bot]`.

## Honest limits

- Judge matching is an LLM call, not ground truth. Use two judge families and treat small gaps as noise; `--reps 3` shows how much a single arm moves on its own.
- Static public PRs can leak into model training data. Prefer relative comparisons between arms over absolute scores, and confirm a decision with `rbk live`.
- Golden sets are capped by what human reviewers wrote; a real finding outside the golden set counts as a false positive.
- Different harnesses make a comparison about products, not models. Hold everything but one factor fixed per arm.

Why these methods, and what review-bot vendors publish about model and effort changes: [docs/methodology.md](docs/methodology.md). Review file format: [docs/formats.md](docs/formats.md).

## Development

```bash
uv run pytest -q && uv run ruff check .
```

License: MIT.
