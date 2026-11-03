#!/bin/sh
# Reviewer arm that uses the Claude Code CLI (works with a Claude subscription or an API key).
# usage: claude_arm.sh REPO BASE HEAD OUT      env: CLAUDE_MODEL (alias or id), CLAUDE_EFFORT (low|medium|high|...)
# Runs in the PR checkout; the model may read files read-only. Writes the generic format to OUT.
set -eu
OUT="$4"
SCHEMA='{"type":"object","required":["comments"],"properties":{"comments":{"type":"array","items":{"type":"object","required":["path","line","body"],"properties":{"path":{"type":"string"},"line":{"type":"integer"},"body":{"type":"string"},"severity":{"type":"string"}}}}}}'
PROMPT="You are a code reviewer. Review the change between git revisions $2 and $3 in this checkout (use git diff $2...$3 and read surrounding code as needed). Report only real defects (bugs, security, data loss, broken contracts). No style nits. Each comment: file path, line in the new file, and a concise explanation of what is wrong and why. Return an empty list if you find nothing."
RAW="$OUT.claude.json"
claude -p "$PROMPT" --output-format json --json-schema "$SCHEMA" \
  ${CLAUDE_MODEL:+--model "$CLAUDE_MODEL"} ${CLAUDE_EFFORT:+--effort "$CLAUDE_EFFORT"} \
  --allowedTools "Read Grep Glob Bash(git diff:*) Bash(git log:*) Bash(git show:*)" > "$RAW"
python3 - "$RAW" "$OUT" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))
u = r.get("usage", {})
out = {"comments": (r.get("structured_output") or {}).get("comments", []),
       "usage": {"input_tokens": u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0),
                 "output_tokens": u.get("output_tokens", 0), "cache_read_tokens": u.get("cache_read_input_tokens", 0),
                 "cost_usd": r.get("total_cost_usd", 0)}}
if r.get("is_error") or "structured_output" not in r:
    sys.exit("claude run failed: " + str(r.get("result", ""))[:300])
json.dump(out, open(sys.argv[2], "w"))
PY
