"""Collect what a hosted review bot (a GitHub App or Action) posted on a PR, in the generic review format.

Use it as the body of an arm for a bot you cannot run locally: the arm opens the PR where the bot is
installed (`rbk mirror`), waits for the bot, and writes its comments to the review file.
"""

from __future__ import annotations

import json
import subprocess
import time

from . import workspace


def _gh(path: str) -> list:
    p = subprocess.run(["gh", "api", "--paginate", "--slurp", path], capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(f"gh api {path}: {p.stderr.strip()[:200]}")
    return [x for page in json.loads(p.stdout) for x in page]


def fetch(pr_url: str, bots: set[str]) -> list[dict]:
    """Inline review comments, review summaries and PR comments written by any of `bots`."""
    o, r, n = workspace.parse_pr_url(pr_url)
    mine = lambda x: ((x.get("user") or {}).get("login", "").removesuffix("[bot]")) in bots
    out = [{"path": c["path"], "line": c.get("line") or c.get("original_line") or 0, "body": c["body"]}
           for c in _gh(f"repos/{o}/{r}/pulls/{n}/comments") if mine(c)]
    out += [{"path": "", "line": 0, "body": c["body"]} for c in _gh(f"repos/{o}/{r}/pulls/{n}/reviews") if mine(c) and c.get("body")]
    out += [{"path": "", "line": 0, "body": c["body"]} for c in _gh(f"repos/{o}/{r}/issues/{n}/comments") if mine(c)]
    return out


def wait(pr_url: str, bots: set[str], timeout: int, quiet: int, poll: int = 15) -> list[dict]:
    """Poll until the bot has posted and then stayed quiet for `quiet` seconds. No output by `timeout` is an error
    (a bot that never ran must not be scored as a review that found nothing)."""
    deadline, seen, stable_since = time.time() + timeout, -1, time.time()
    while True:
        comments = fetch(pr_url, bots)
        if len(comments) != seen:
            seen, stable_since = len(comments), time.time()
        if comments and time.time() - stable_since >= quiet:
            return comments
        if time.time() > deadline:
            raise TimeoutError(f"{', '.join(sorted(bots))} posted nothing on {pr_url} within {timeout}s")
        time.sleep(poll)
