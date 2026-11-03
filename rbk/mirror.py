"""Open a benchmark PR inside a repository where your hosted review bot is installed.

Hosted bots only review PRs in repositories they are installed on, so each benchmark PR is replayed there:
the base and head commits are pushed as branches of `target` and a PR head -> base is opened. Point `target`
at a scratch repository you own and install the bot on it. Re-running reuses an existing PR.
"""

from __future__ import annotations

import json
import subprocess

from . import workspace


def _run(args: list[str], cwd=None) -> str:
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(f"{' '.join(args[:3])}: {p.stderr.strip()[:300]}")
    return p.stdout.strip()


def open_pr(pr_url: str, target: str, root) -> str:
    pr = workspace.checkout(pr_url, root)
    key = workspace.slug(pr_url)
    base_br, head_br = f"rbk/{key}/base", f"rbk/{key}/head"
    url = f"https://github.com/{target}.git"
    for br, sha in ((base_br, pr["base"]), (head_br, pr["head"])):
        _run(["git", "push", "--force", url, f"{sha}:refs/heads/{br}"], cwd=pr["repo"])
    found = _run(["gh", "pr", "list", "-R", target, "--head", head_br, "--base", base_br, "--state", "all",
                  "--json", "url", "--jq", ".[0].url // empty"])
    if found:
        return found
    title = json.loads(_run(["gh", "api", f"repos/{'/'.join(workspace.parse_pr_url(pr_url)[:2])}/pulls/{workspace.parse_pr_url(pr_url)[2]}"])).get("title", key)
    return _run(["gh", "pr", "create", "-R", target, "--head", head_br, "--base", base_br, "--title", title,
                 "--body", f"Replay of {pr_url} for review-bench-kit."])
