"""Check out a public PR (base and head) so an arm can review it locally."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

_PR = re.compile(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)")


def parse_pr_url(url: str) -> tuple[str, str, int]:
    m = _PR.search(url)
    if not m:
        raise ValueError(f"not a GitHub PR URL: {url}")
    return m.group(1), m.group(2), int(m.group(3))


def slug(url: str) -> str:
    o, r, n = parse_pr_url(url)
    return f"{o}__{r}__{n}"


def _git(cwd: Path, *args: str) -> str:
    p = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {p.stderr.strip()[:300]}")
    return p.stdout.strip()


def checkout(url: str, root: Path) -> dict:
    """Return {repo, base, head, pr_url} with a clean worktree at head. Reused across arms and runs."""
    owner, repo, num = parse_pr_url(url)
    cache = root / "repos" / f"{owner}__{repo}"
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        p = subprocess.run(["git", "clone", "--quiet", "--filter=blob:none", "--no-checkout",
                            f"https://github.com/{owner}/{repo}.git", str(cache)], capture_output=True, text=True)
        if p.returncode:
            raise RuntimeError(f"clone failed: {p.stderr.strip()[:300]}")
    ref = f"refs/rbk/pr{num}"
    _git(cache, "fetch", "--quiet", "origin", f"+pull/{num}/head:{ref}")
    head = _git(cache, "rev-parse", ref)
    info = subprocess.run(["gh", "api", f"repos/{owner}/{repo}/pulls/{num}", "--jq", ".base.sha"],
                          capture_output=True, text=True)
    if info.returncode:
        raise RuntimeError(f"gh api failed (is gh authenticated?): {info.stderr.strip()[:300]}")
    _git(cache, "fetch", "--quiet", "origin", info.stdout.strip())
    base = _git(cache, "merge-base", info.stdout.strip(), head)
    wt = root / "worktrees" / slug(url)
    if not wt.exists():
        wt.parent.mkdir(parents=True, exist_ok=True)
        _git(cache, "worktree", "add", "--quiet", "--detach", str(wt), head)
    else:
        _git(wt, "checkout", "--quiet", "--force", head)
        _git(wt, "clean", "-fdxq")
    return {"repo": str(wt), "base": base, "head": head, "pr_url": url}


def result_files(d: Path) -> list[Path]:
    """The r<k>.json result files of one PR and arm (arms may leave other files beside them)."""
    return sorted((f for f in d.glob("r*.json") if re.fullmatch(r"r\d+", f.stem)), key=lambda f: int(f.stem[1:]))
