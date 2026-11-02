#!/bin/sh
# Smoke-test arm: writes one fixed comment in the generic format. Replace with a real reviewer wrapper.
# usage: fake_arm.sh REPO BASE HEAD OUT
cat > "$4" <<'EOF'
{"comments": [{"path": "README.md", "line": 1, "body": "placeholder finding"}],
 "usage": {"input_tokens": 1000, "output_tokens": 100}}
EOF
