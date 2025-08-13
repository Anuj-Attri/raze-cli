# raze_cli/main.py
from __future__ import annotations
import argparse, json, time, os, sys
from pathlib import Path

# Core pipeline (single call that does: ingest -> extract -> LLM discover -> graph -> plan)
try:
    from .pipeline import run_pipeline  # preferred unified path
except Exception:
    # fallback if pipeline isn't created yet: raise a helpful error
    raise SystemExit(
        "[ERROR] raze_cli.pipeline.run_pipeline not found.\n"
        "Create raze_cli/pipeline.py as discussed, or run the older CLI version."
    )

def write_file(path: str, obj) -> None:
    Path(path).write_text(json.dumps(obj, indent=2), encoding="utf-8")

def main():
    ap = argparse.ArgumentParser(
        description="RAZE — offline copilot to organize, cluster, and refactor files (Ollama/GPT-OSS optional)."
    )
    # I/O
    ap.add_argument("--path", help="Folder to scan (ignored if --ui without prompt)", default=None)
    ap.add_argument("--out", default="graph.json", help="Output graph JSON")
    ap.add_argument("--plan", default="plan.json", help="Output plan JSON")
    ap.add_argument("--summaries", default="summaries.json", help="Output summaries JSON")
    # LLM (optional)
    ap.add_argument("--llm-endpoint", help="OpenAI-compatible base URL (e.g., http://localhost:11434/v1)")
    ap.add_argument("--llm-model", help="Model name served at the endpoint (e.g., llama3 or gpt-oss-20b)")
    ap.add_argument("--api-key", default=os.getenv("OPENAI_API_KEY", ""), help="Bearer token if required by your server")
    # Costing
    ap.add_argument("--rate", type=float, default=0.0, help="Storage cost per GB per month (e.g., 0.023 for S3)")
    # UI
    ap.add_argument("--ui", action="store_true", help="Launch the native UI (PySide6).")
    # Prompt mode (future: free-form prompt; for now we accept path via CLI or UI)
    args = ap.parse_args()

    if args.ui:
        # Launch the native PySide6 app; it imports run_pipeline and calls it internally.
        try:
            from raze_app.ui import main as ui_main
        except Exception as e:
            raise SystemExit(
                "[ERROR] Native UI not found or PySide6 missing.\n"
                "Install PySide6:  pip install PySide6\n"
                f"Import error: {e}"
            )
        ui_main()
        return

    if not args.path:
        raise SystemExit("[ERROR] --path is required in CLI mode (or pass --ui to launch the native app).")

    t0 = time.time()
    result = run_pipeline(
        path=args.path,
        llm_endpoint=args.llm_endpoint,
        llm_model=args.llm_model,
        api_key=args.api_key or None,
        storage_rate_per_gb=args.rate,
    )

    write_file(args.out, result["graph"])
    write_file(args.plan, result["plan"])
    write_file(args.summaries, result["summaries"])

    elapsed = round(time.time() - t0, 2)
    print(f"[OK] Graph     -> {args.out}")
    print(f"[OK] Plan      -> {args.plan}")
    print(f"[OK] Summaries -> {args.summaries}")
    print(f"[INFO] Scanned '{args.path}' in {elapsed}s")
    if args.llm_endpoint and args.llm_model:
        print(f"[INFO] LLM categories: endpoint={args.llm_endpoint} model={args.llm_model}")
    if args.rate:
        print(f"[INFO] Costing at ${args.rate}/GB applied")

if __name__ == "__main__":
    main()
