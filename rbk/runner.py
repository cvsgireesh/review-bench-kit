"""Run each arm on each PR and store normalized reviews under runs/<arm>/<pr-slug>/r<k>.json.

An arm is a shell command. It is run inside the PR checkout and must write a review file to {out}.
Placeholders: {repo} {base} {head} {out} {pr_url}. Existing results are kept, so a run can be resumed.
A failed or timed-out run is recorded as status "error"; it is never read as "no comments".
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config, normalize, workspace


def cost_usd(usage: dict, price: dict | None) -> float | None:
    if not price:
        return None
    per = 1_000_000
    return (usage.get("input_tokens", 0) * price.get("input_per_mtok", 0)
            + usage.get("output_tokens", 0) * price.get("output_per_mtok", 0)
            + usage.get("cache_read_tokens", 0) * price.get("cache_read_per_mtok", 0)) / per


def run_one(name: str, arm: dict, pr: dict, out_file: Path, timeout: int) -> dict:
    raw = out_file.with_suffix(".rawout")  # must not match the r*.json glob the readers use
    env = {**os.environ, **{k: config.expand(str(v)) for k, v in (arm.get("env") or {}).items()}}
    cmd = config.expand(arm["cmd"]).format(repo=pr["repo"], base=pr["base"], head=pr["head"],
                                           out=raw, pr_url=pr["pr_url"])
    t0 = time.monotonic()
    status, err = "ok", ""
    try:
        p = subprocess.run(cmd, shell=True, cwd=pr["repo"], env=env, capture_output=True, text=True, timeout=timeout)
        if p.returncode:
            status, err = "error", f"exit {p.returncode}: {p.stderr.strip()[-400:]}"
    except subprocess.TimeoutExpired:
        status, err = "error", f"timeout after {timeout}s"
    seconds = time.monotonic() - t0
    res = {"arm": name, "pr_url": pr["pr_url"], "status": status, "error": err, "seconds": round(seconds, 1),
           "comments": [], "usage": {}}
    if status == "ok":
        try:
            res.update(normalize.load_output(raw, arm.get("normalize", "generic")))
        except (OSError, ValueError, KeyError) as e:
            res["status"], res["error"] = "error", f"unreadable review output: {e}"
    res["usage"]["cost_usd"] = res["usage"].get("cost_usd", cost_usd(res["usage"], arm.get("price")))
    out_file.write_text(json.dumps(res, indent=1))
    return res


def run(cfg: dict, pr_urls: list[str], arms: list[str], reps: int, root: Path, jobs: int, timeout: int) -> list[Path]:
    failed: list[Path] = []

    def per_pr(url: str) -> None:
        for name in arms:
            for k in range(1, reps + 1):
                out = root / "runs" / name / workspace.slug(url) / f"r{k}.json"
                if out.exists() and json.loads(out.read_text()).get("status") == "ok":
                    continue
                out.parent.mkdir(parents=True, exist_ok=True)
                pr = workspace.checkout(url, root)  # also resets the worktree between arms and repeats
                res = run_one(name, cfg["arms"][name], pr, out, timeout)
                print(f"{name:24} {workspace.slug(url):40} r{k} {res['status']} {res['seconds']}s {res['error'][:80]}")
                if res["status"] != "ok":
                    failed.append(out)

    with ThreadPoolExecutor(max_workers=jobs) as ex:
        list(ex.map(per_pr, pr_urls))
    return failed
