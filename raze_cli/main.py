
from __future__ import annotations
import argparse, json, time, os
from pathlib import Path

from .ingest import scan_directory
from .dedupe import cluster_by_duplicate, cluster_by_type, cluster_by_age
from .graph import build_graph

# raze --path demo_data --out graph.json --plan plan.json

def main():
    ap = argparse.ArgumentParser(description="RAZE CLI — scan folder, build reasoning graph (stub), and plan.")
    ap.add_argument("--path", required=True, help="Folder to scan")
    ap.add_argument("--out", required=True, help="Output graph.json")
    ap.add_argument("--plan", required=True, help="Output plan.json (dry-run suggestions)")
    args = ap.parse_args()

    t0 = time.time()
    files = scan_directory(args.path)
    now = time.time()
    dup = cluster_by_duplicate(files)
    typ = cluster_by_type(files)
    age = cluster_by_age(files, now)

    graph = build_graph(files, dup, typ, age)

    # simple plan: suggest deleting duplicates (keep 1), and temp files
    suggested_delete_ids = set()
    for h, ids in dup.items():
        # keep the first (arbitrary), suggest deleting others
        for fid in ids[1:]:
            suggested_delete_ids.add(fid)

    # temp files: by name suffix
    for f in files:
        name = Path(f.path).name.lower()
        if any(name.endswith(suf) for suf in [".tmp", ".log", ".bak", ".old", "~"]):
            suggested_delete_ids.add(f.id)

    # map ids -> paths
    id_to_path = {f.id: f.path for f in files}
    plan = {
        "summary": {
            "files_scanned": len(files),
            "duplicate_clusters": len(dup),
            "suggested_deletions": len(suggested_delete_ids),
            "elapsed_sec": round(time.time() - t0, 2)
        },
        "items": [{"id": fid, "path": id_to_path.get(fid)} for fid in sorted(suggested_delete_ids)]
    }

    Path(args.out).write_text(json.dumps(graph, indent=2), encoding="utf-8")
    Path(args.plan).write_text(json.dumps(plan, indent=2), encoding="utf-8")
    print(f"[OK] Graph -> {args.out}")
    print(f"[OK] Plan  -> {args.plan}")
    print(f"[INFO] Scanned {len(files)} files in {round(time.time()-t0,2)}s")

if __name__ == "__main__":
    main()
