"""A local OpenAI-compatible endpoint that answers with the Claude Code CLI (so a Claude subscription can be the judge).

    rbk judge-proxy --port 8799          then   JUDGE_BASE_URL=http://127.0.0.1:8799/v1  JUDGE_API_KEY=any

The request's `model` is passed to `claude --model` (an alias such as `sonnet` or a full id). Only
/v1/chat/completions is implemented (including tool calls, emulated by prompting), which covers the scorer and OCR-style agents.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _text(m: dict) -> str:
    c = m.get("content") or ""
    body = c if isinstance(c, str) else json.dumps(c)
    for t in m.get("tool_calls") or []:
        body += f"\n(called tool {t['function']['name']} with {t['function']['arguments']})"
    return f"[{m['role']}{' result ' + m['tool_call_id'] if m.get('tool_call_id') else ''}]\n{body}"


TOOL_HELP = ("You can call tools. To call one or more, reply with ONLY a JSON object "
             '{"tool_calls": [{"name": "<tool>", "arguments": {...}}]} and nothing else. '
             "When you need no tool, reply normally. Available tools (JSON schema):\n")


def ask(model: str, messages: list[dict], tools: list[dict] | None = None, timeout: int = 600) -> tuple[str, dict]:
    text = "\n\n".join(_text(m) for m in messages)
    if tools:
        text = TOOL_HELP + json.dumps([t["function"] for t in tools]) + "\n\n" + text
    cmd = ["claude", "-p", text, "--output-format", "json", "--tools", "", "--no-session-persistence"]
    if model:
        cmd += ["--model", model]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    try:
        r = json.loads(p.stdout)
    except ValueError:
        raise RuntimeError(f"claude failed ({p.returncode}): {(p.stderr or p.stdout)[:300]}") from None
    if r.get("is_error"):
        raise RuntimeError(f"claude error: {str(r.get('result'))[:300]}")
    u = r.get("usage", {})
    return r["result"], {"prompt_tokens": u.get("input_tokens", 0), "completion_tokens": u.get("output_tokens", 0)}


def _parse_tool_calls(content: str) -> list[dict] | None:
    t = content.strip()
    if t.startswith("```"):
        t = t.strip("`").removeprefix("json").strip()
    try:
        calls = json.loads(t)["tool_calls"]
        return [{"id": f"call_{i}", "type": "function",
                 "function": {"name": c["name"], "arguments": json.dumps(c.get("arguments", {}))}} for i, c in enumerate(calls)]
    except (ValueError, KeyError, TypeError):
        return None


def serve(port: int, jobs: int) -> None:
    gate = threading.Semaphore(jobs)

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            try:
                with gate:
                    content, usage = ask(body.get("model", ""), body["messages"], body.get("tools"))
                calls = _parse_tool_calls(content) if body.get("tools") else None
                msg = {"role": "assistant", "content": None, "tool_calls": calls} if calls else {"role": "assistant", "content": content}
                out, code = {"id": "rbk", "object": "chat.completion", "created": int(time.time()), "model": body.get("model"),
                             "choices": [{"index": 0, "finish_reason": "tool_calls" if calls else "stop", "message": msg}],
                             "usage": {**usage, "total_tokens": sum(usage.values())}}, 200
            except Exception as e:  # noqa: BLE001  surfaced to the client as an API error, never as an empty completion
                out, code = {"error": {"message": str(e), "type": "server_error"}}, 500
            data = json.dumps(out).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    print(f"judge proxy on http://127.0.0.1:{port}/v1 (claude CLI, {jobs} parallel)", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
