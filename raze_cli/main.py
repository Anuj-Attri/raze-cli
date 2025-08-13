from __future__ import annotations
import argparse, json, time
from pathlib import Path
from .ingest import scan_directory
from .dedupe import cluster_by_duplicate, cluster_by_type, cluster_by_age, cluster_near_duplicate_text
from .graph import build_graph
from .extract import extract_text_snippet
from .simhash import simhash64
from .summarize import summarize_cluster

def main():
    ap = argparse.ArgumentParser(description="RAZE CLI — scan folder, build reasoning graph (stub), and plan.")
    ap.add_argument("--path", required=True, help="Folder to scan")
    ap.add_argument("--out", required=True, help="Output graph.json")
    ap.add_argument("--plan", required=True, help="Output plan.json (dry-run suggestions)")
    ap.add_argument("--summaries", default="summaries.json", help="Output summaries.json (cluster summaries)")
    args = ap.parse_args()

    t0 = time.time()
    files = scan_directory(args.path)
    now = time.time()

    dup = cluster_by_duplicate(files)
    typ = cluster_by_type(files)
    age = cluster_by_age(files, now)

    # --- Phase 2: text snippets + simhash for near-dup text ---
    id_to_file = {f.id: f for f in files}
    text_snippets: dict[str, str] = {}
    simhash_items = []
    for f in files:
        snippet = extract_text_snippet(f.path, f.type) or ""
        if snippet:
            text_snippets[f.id] = snippet[:2000]
            try:
                simhash_items.append((f.id, simhash64(snippet)))
            except Exception:
                pass

    near_dup_clusters = cluster_near_duplicate_text(simhash_items) if simhash_items else []

    # Summaries per cluster/node id
    summaries: dict[str, str] = {}
    for h, ids in dup.items():
        summaries[f"dup:{h[:8]}"] = summarize_cluster(ids, id_to_file, text_snippets)
    for t, ids in typ.items():
        summaries[f"type:{t}"] = summarize_cluster(ids, id_to_file, text_snippets)
    for label, ids in age.items():
        summaries[f"age:{label}"] = summarize_cluster(ids, id_to_file, text_snippets)
    for idx, ids in enumerate(near_dup_clusters):
        summaries[f"neardup:{idx}"] = summarize_cluster(ids, id_to_file, text_snippets)

    graph = build_graph(files, dup, typ, age,
                        near_dup_clusters=near_dup_clusters,
                        summaries=summaries)

    # simple plan: suggest deleting duplicates (keep 1), temp files, and near-dups (keep 1)
    suggested_delete_ids = set()
    for h, ids in dup.items():
        for fid in ids[1:]:
            suggested_delete_ids.add(fid)

    # near-duplicate clusters -> keep the first of each
    for ids in near_dup_clusters:
        for fid in ids[1:]:
            suggested_delete_ids.add(fid)

    # temp-ish file names by suffix
    for f in files:
        name = Path(f.path).name.lower()
        if any(name.endswith(suf) for suf in [".tmp", ".log", ".bak", ".old", "~"]):
            suggested_delete_ids.add(f.id)

    # write outputs
    id_to_path = {f.id: f.path for f in files}
    plan = {
        "summary": {
            "files_scanned": len(files),
            "duplicate_clusters": len(dup),
            "near_duplicate_clusters": len(near_dup_clusters),
            "suggested_deletions": len(suggested_delete_ids),
            "elapsed_sec": round(time.time() - t0, 2),
        },
        "items": [{"id": fid, "path": id_to_path.get(fid)} for fid in sorted(suggested_delete_ids)],
    }

    Path(args.out).write_text(json.dumps(graph, indent=2), encoding="utf-8")
    Path(args.plan).write_text(json.dumps(plan, indent=2), encoding="utf-8")
    Path(args.summaries).write_text(json.dumps(summaries, indent=2), encoding="utf-8")

    print(f"[OK] Graph -> {args.out}")
    print(f"[OK] Plan  -> {args.plan}")
    print(f"[OK] Summaries -> {args.summaries}")
    print(f"[INFO] Scanned {len(files)} files in {round(time.time() - t0, 2)}s")

if __name__ == "__main__":
    main()
