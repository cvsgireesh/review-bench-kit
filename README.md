# review-bench-kit

Measure any code-review bot, model or effort setting, and decide a switch from numbers.
It does not reinvent the benchmarks: it runs your reviewer on the public [Martian offline benchmark](https://github.com/withmartian/code-review-benchmark) (MIT, 50 PRs, 173 golden comments) using that project's own extract / dedup / judge steps, then adds what it lacks: repeats, paired confidence intervals, cost and latency, and a switch/keep rule you write before running.

```
arms.yaml ──► rbk run ──► runs/<arm>/<pr>/r<k>.json   (one normalized review per PR, repeat, arm)
                              │
                       rbk score  (Martian steps 2, 2.5, 3 with your judge models)
                              │
decision.yaml ───────► rbk compare ──► report.md / report.json   SWITCH or KEEP per candidate

live PRs of any repo ──► rbk live (before)  ┐
                         rbk live (after)   ┴► rbk live-compare   what happened to the bot's real comments
```

## Quick start

```bash
uv sync
uv run rbk deps                                   # clones the Martian scorer at a pinned commit into work/third_party
cp examples/arms.example.yaml arms.yaml           # define your baseline and candidate arms
cp examples/decision.example.yaml decision.yaml   # write the switch rule first
export JUDGE_BASE_URL=... JUDGE_API_KEY=...       # any OpenAI-compatible endpoint
uv run rbk run     --config arms.yaml --reps 3 --jobs 2
uv run rbk score   --config arms.yaml
uv run rbk compare --config arms.yaml --decision decision.yaml --out report
```

Needs `git`, an authenticated `gh`, and whatever your reviewer needs. `rbk run --limit N` runs the first N PRs only.

## Plug in a reviewer (an "arm")

An arm is a shell command run inside a checkout of the PR; it writes a review file to `{out}`.
Placeholders: `{repo} {base} {head} {out} {pr_url}`. Env values accept `${VAR}`, so keys stay out of the file.

| Your reviewer | What to do |
|---|---|
| A CLI (e.g. OpenCodeReview `ocr`) | `normalize: ocr` or `generic`; vary model and effort through `env` and flags, one arm each. |
| A script or SDK | Wrap it so it prints the [generic format](docs/formats.md); `normalize: generic`. |
| A hosted bot (GitHub App) | Use the Martian pipeline's fork step (`step0_fork_prs`) to open the benchmark PRs where the bot is installed, then write each bot comment into the generic format with a small collector script and run it as the arm command. Change the bot's model between collections. |

Only change one thing between arms. Different harnesses make the comparison about products, not models.

## Decide a switch

`decision.yaml` holds the rules. Differences are candidate minus baseline with a 95% paired bootstrap over PRs.
A candidate is `SWITCH` only if every `require` rule passes under **every** judge and one `any_superior` rule passes
(a switch needs a reason: cheaper, faster or better). Failed or timed-out runs are excluded and reported, never counted as empty reviews.

## Measure the production bot on real PRs

```bash
uv run rbk live --repo owner/name --bot LOGIN --until 2026-10-31 --out before.json
uv run rbk live --repo owner/name --bot LOGIN --since 2026-11-01 --out after.json --audit 25
uv run rbk live-compare before.json after.json
```

Per bot thread: accepted (author replied fixed/confirmed), rejected, code changed afterwards (outdated or resolved), no reply.
Plus a recall proxy: share of human-started review threads within `--window` lines of a bot thread. These are proxies:
reply wording is matched with regexes, so read the `--audit` sample before quoting a rate. Pass other bots with `--also-bot`
so they are not counted as humans. For a GitHub App, pass its login without `[bot]`.

## What is and is not here

- Implemented and tested: arm runner, normalizers, Martian export, comparison and decision rules, live scorer and its comparison.
- Plumbing smoke-tested on a real benchmark PR with a stub reviewer. The judge steps (`rbk score`) run the unmodified Martian code and have **not** been exercised end to end here (they need your judge key).
- Not implemented: other public datasets (SWR-Bench, SWE-PRBench, ReviewBench, c-CRAB). Their data and harnesses are public; each needs a dataset adapter that produces the same normalized reviews and reads their judge output. See [docs/methodology.md](docs/methodology.md).
- Limits inherited from the benchmark: 50 static PRs (leakage risk), gold set capped at human recall, judge not calibrated against humans. Use two judge families and treat small gaps as noise.
