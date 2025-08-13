#!/usr/bin/env bash
set -e
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m raze_cli.main --path demo_data --out graph.json --plan plan.json
echo '--- graph.json (head) ---'
python - <<'PY'
import json; print(json.dumps(json.load(open('graph.json')), indent=2)[:1200] + '...')
PY
echo '--- plan.json ---'
cat plan.json
