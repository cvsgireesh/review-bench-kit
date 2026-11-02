# Review file format (generic)

An arm writes this JSON to `{out}`:

```json
{
  "comments": [
    {"path": "src/a.py", "line": 42, "body": "what is wrong and why", "severity": "high", "category": "bug"}
  ],
  "usage": {"input_tokens": 120000, "output_tokens": 4000, "cache_read_tokens": 0, "cost_usd": 0.41}
}
```

- `path` and `body` are required; `line` defaults to 0; `severity` and `category` are optional.
- `usage` is optional. Token counts with a `price` block in `arms.yaml` give cost; wall time is always measured.
- Exit non-zero (or time out) to record a failed run. Failed runs are excluded and reported, never scored as "no findings".
- An empty `comments` list is a valid review ("nothing found").

`normalize: ocr` reads `ocr review --format json` directly (comments[].path/content/start_line/severity/category, summary tokens).
