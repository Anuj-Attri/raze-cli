# RAZE (Reasoning AI Zero-Evidence) — Starter (CLI MVP)

This is a **minimal, offline** starter for the RAZE project. It scans a folder, builds a simple **reasoning graph JSON** (nodes + edges + stub rationales), and prints a **plan** for potential deletions (duplicates/temp files).

> Next step: swap `reasoner_stub.py` with a call to your **local GPT-OSS** endpoint and wire in the React/Tauri UI.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run on the included demo corpus
python -m raze_cli.main --path demo_data --out graph.json --plan plan.json

# View results
jq '.' graph.json | head -n 80
jq '.' plan.json
```
*(If you don't have `jq`, just open the JSON files.)*

## What this MVP does
- Metadata-first scan (path, size, mtime, mime guess)
- Clusters: by file type, by age (new/stale/ancient), and by exact duplicate (content hash)
- Produces `graph.json` with nodes/edges and **stub reasoning** per node (replace later)
- Produces `plan.json` suggesting deletions for duplicates and temp files (dry-run only)

## Next steps (you can implement after confirming MVP)
1. Replace `reasoner_stub.suggest()` with a call to your **local GPT-OSS**:
   - e.g., `http://127.0.0.1:8000/v1/chat/completions` (vLLM OpenAI-compatible API)
   - Pass cluster summaries; receive structured JSON for rationales and confidences
2. Add **two-person approval** and **quarantine** behavior for deletes
3. Build **React + react-flow** UI to render `graph.json` (Simulink-style)
4. Package as **Tauri** desktop app (offline) and add installer targets

## Safety
- This MVP **does not delete** anything. It only suggests in `plan.json`.
- Always test on sample data first.
