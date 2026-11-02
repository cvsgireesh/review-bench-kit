"""Score a review bot on real PRs of any GitHub repo, from what happened to its comments.

Per-thread signals (no benchmark needed, works for any bot with a GitHub login):
  accepted      the author or a maintainer replied that it was fixed/confirmed
  rejected      replied that it was wrong, stale or declined
  code_changed  the thread is outdated or resolved (the commented lines changed afterwards)
  no_reply      nobody answered
Recall proxy: share of human-started review threads that sit within `window` lines of a bot thread on the same file.

These are proxies. Replies are matched by wording, so check `--audit N` samples before quoting a number.
Use it before and after a switch (--since/--until) and compare with `rbk live-compare`.
"""

from __future__ import annotations

import json
import random
import re
import subprocess
import time
from pathlib import Path

ACCEPT_OPEN = re.compile(r"^(real|valid|confirmed|agreed|fixed|done|added|pushed|good catch|partly (fixed|done)|yes|right)\b", re.IGNORECASE)
ACCEPT_ANY = re.compile(r"fixed (in|on|at|by|with|and)|\bfixed\b.{0,40}\b[0-9a-f]{7,}\b|done in|pushed in|added in", re.IGNORECASE)
DECLINE = re.compile(r"^(already (fixed|handled|at|in|on|covered)|no change|not changed|not reproduced|declined|left as|"
                     r"acceptable as|i would not|does not reproduce|this does not reproduce|no,|not a bug|intentional|by design|"
                     r"won'?t|not changing|reproduced,? not changed)", re.IGNORECASE)

Q = """query($n:Int!,$after:String,$owner:String!,$name:String!){repository(owner:$owner,name:$name){pullRequest(number:$n){
reviewThreads(first:100,after:$after){pageInfo{hasNextPage endCursor} nodes{isResolved isOutdated
comments(first:50){nodes{author{login} path line originalLine body}}}}}}}"""


def _gh(args: list[str], tries: int = 4) -> str:
    for i in range(tries):
        p = subprocess.run(["gh", *args], capture_output=True, text=True)
        if p.returncode == 0:
            return p.stdout
        time.sleep(2 * (i + 1))
    raise RuntimeError(f"gh {' '.join(args[:3])} failed: {p.stderr.strip()[:300]}")


def search_prs(repo: str, bot: str, since: str | None, until: str | None) -> list[int]:
    """PRs the bot reviewed. A machine user is searched by login; a GitHub App needs the `app/` form."""
    for who in (bot, f"app/{bot}"):
        q = f"repo:{repo} type:pr reviewed-by:{who}"
        if since or until:
            q += f" created:{since or '*'}..{until or '*'}"
        try:
            out = _gh(["api", "-X", "GET", "search/issues", "-f", f"q={q}", "-f", "per_page=100", "--paginate",
                       "--jq", ".items[].number"], tries=1)
        except RuntimeError as e:
            if "cannot be searched" in str(e):  # wrong form for this account type; try the other
                continue
            raise  # rate limits and auth errors must never read as "no PRs"
        if out.split():
            return [int(x) for x in out.split()]
    return []


def threads(repo: str, n: int) -> list[dict]:
    owner, name = repo.split("/")
    out, after = [], None
    while True:
        args = ["api", "graphql", "-f", f"query={Q}", "-F", f"n={n}", "-f", f"owner={owner}", "-f", f"name={name}"]
        if after:
            args += ["-f", f"after={after}"]
        rt = json.loads(_gh(args))["data"]["repository"]["pullRequest"]["reviewThreads"]
        out += rt["nodes"]
        if not rt["pageInfo"]["hasNextPage"]:
            return out
        after = rt["pageInfo"]["endCursor"]


def reply_verdict(text: str) -> str:
    t = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    t = re.sub(r"[*_`]", "", t).strip()
    if DECLINE.match(t):
        return "rejected"
    if ACCEPT_OPEN.match(t) or ACCEPT_ANY.search(t[:400]):
        return "accepted"
    return "other"


def _login(c: dict) -> str:
    return (c.get("author") or {}).get("login", "")


def score_pr(ths: list[dict], bots: set[str], window: int) -> tuple[dict, list[dict]]:
    mine, humans = [], []
    for t in ths:
        cs = t["comments"]["nodes"]
        if not cs:
            continue
        first = cs[0]
        line = first.get("originalLine") or first.get("line") or 0
        if _login(first) in bots:
            replies = [c["body"] for c in cs[1:] if _login(c) not in bots and not _login(c).endswith("[bot]")]
            v = "no_reply" if not replies else reply_verdict(replies[0])
            mine.append({"path": first["path"], "line": line, "verdict": v,
                         "code_changed": t["isOutdated"] or t["isResolved"], "body": first["body"][:300],
                         "reply": replies[0][:300] if replies else ""})
        elif first.get("path") and not _login(first).endswith("[bot]"):
            humans.append({"path": first["path"], "line": line})
    hit = sum(any(m["path"] == h["path"] and abs(m["line"] - h["line"]) <= window for m in mine) for h in humans)
    row = {"threads": len(mine), "accepted": sum(m["verdict"] == "accepted" for m in mine),
           "rejected": sum(m["verdict"] == "rejected" for m in mine),
           "no_reply": sum(m["verdict"] == "no_reply" for m in mine),
           "code_changed": sum(m["code_changed"] for m in mine), "human_threads": len(humans), "human_hit": hit}
    return row, mine


def rates(rows: list[dict]) -> dict:
    s = lambda k: sum(r[k] for r in rows)
    d = lambda a, b: a / b if b else 0.0
    return {"prs": len(rows), "threads_per_pr": d(s("threads"), len(rows)), "accepted_rate": d(s("accepted"), s("threads")),
            "rejected_rate": d(s("rejected"), s("threads")), "no_reply_rate": d(s("no_reply"), s("threads")),
            "code_changed_rate": d(s("code_changed"), s("threads")), "human_overlap_recall": d(s("human_hit"), s("human_threads"))}


def run(repo: str, bot: str, also_bots: list[str], since: str | None, until: str | None, window: int,
        audit: int, out: Path) -> dict:
    bot = bot.removesuffix("[bot]")
    bots = {bot, *(b.removesuffix("[bot]") for b in also_bots)}
    per_pr, audit_pool = {}, []
    for n in search_prs(repo, bot, since, until):
        row, mine = score_pr(threads(repo, n), bots, window)
        per_pr[str(n)] = row
        audit_pool += [{"pr": n, **m} for m in mine]
    res = {"meta": {"repo": repo, "bot": bot, "also_bots": also_bots, "since": since, "until": until, "window": window},
           "prs": per_pr, "summary": rates(list(per_pr.values()))}
    if audit:
        random.Random(1).shuffle(audit_pool)
        res["audit_sample"] = audit_pool[:audit]
    out.write_text(json.dumps(res, indent=1))
    return res


def compare(a: dict, b: dict, boots: int = 2000, seed: int = 7) -> dict:
    """Unpaired bootstrap over PRs: b - a for each rate (a = before / baseline, b = after / candidate)."""
    ra, rb = list(a["prs"].values()), list(b["prs"].values())
    rng, names = random.Random(seed), [k for k in rates(ra) if k != "prs"]
    diffs = {n: [] for n in names}
    for _ in range(boots):
        x = rates([rng.choice(ra) for _ in ra])
        y = rates([rng.choice(rb) for _ in rb])
        for n in names:
            diffs[n].append(y[n] - x[n])
    out = {}
    pa, pb = rates(ra), rates(rb)
    for n in names:
        d = sorted(diffs[n])
        out[n] = {"a": pa[n], "b": pb[n], "diff": pb[n] - pa[n], "ci": [d[int(.025 * boots)], d[int(.975 * boots) - 1]]}
    return {"a_prs": len(ra), "b_prs": len(rb), "metrics": out}
