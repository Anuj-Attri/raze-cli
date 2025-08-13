from __future__ import annotations
from pathlib import Path
import time, json, re, os
from typing import Dict, Any, List

from .ingest import scan_directory
from .extract import extract_text_snippet
from .simhash import simhash64
from .dedupe import (
    cluster_by_duplicate, cluster_by_type, cluster_by_age, cluster_near_duplicate_text
)
from .summarize import summarize_cluster
from .graph import build_graph
from .phash import phash64, cluster_phash
from .reasoner_oss import llm_discover_categories

def base_bucket(filetype: str) -> str:
    top = (filetype or "").split("/")[0].lower()
    if top == "image": return "Images"
    if top == "audio": return "Audio"
    if top == "video": return "Video"
    if top in ("text","application"): return "Documents"
    return "Other"

def _slug(s: str) -> str:
    s = s.strip().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "cluster"

def run_pipeline(path: str,
                 llm_endpoint: str | None = None,
                 llm_model: str | None = None,
                 api_key: str | None = None,
                 storage_rate_per_gb: float = 0.0) -> Dict[str, Any]:
    t0 = time.time()
    files = scan_directory(path)
    now = time.time()

    # Heuristics
    dup = cluster_by_duplicate(files)
    typ = cluster_by_type(files)
    age = cluster_by_age(files, now)

    id_to_file = {f.id: f for f in files}
    text_snippets: Dict[str, str] = {}
    simhash_items: List[tuple[str,int]] = []

    for f in files:
        snip = extract_text_snippet(f.path, f.type) or ""
        if snip:
            text_snippets[f.id] = snip[:2000]
            try:
                simhash_items.append((f.id, simhash64(snip)))
            except Exception:
                pass

    near_dup_clusters = cluster_near_duplicate_text(simhash_items) if simhash_items else []

    # Image similarity
    phash_items: List[tuple[str,int]] = []
    for f in files:
        try:
            h = phash64(f.path)
            if h is not None: phash_items.append((f.id, h))
        except Exception:
            pass
    image_sim_clusters = cluster_phash(phash_items) if phash_items else []

    # Summaries
    summaries: Dict[str,str] = {}
    for h, ids in dup.items(): summaries[f"dup:{h[:8]}"] = summarize_cluster(ids, id_to_file, text_snippets)
    for t, ids in typ.items(): summaries[f"type:{t}"]   = summarize_cluster(ids, id_to_file, text_snippets)
    for lb, ids in age.items(): summaries[f"age:{lb}"]  = summarize_cluster(ids, id_to_file, text_snippets)
    for i, ids in enumerate(near_dup_clusters): summaries[f"neardup:{i}"] = summarize_cluster(ids, id_to_file, text_snippets)

    # Bucketize files
    buckets: Dict[str, list] = {"Images":[], "Documents":[], "Audio":[], "Video":[], "Other":[]}
    for f in files: buckets[base_bucket(f.type)].append(f)

    def inventory(subset, max_files=500, max_snip=1000):
        out = []
        for f in subset[:max_files]:
            p = Path(f.path)
            out.append({
                "id": f.id, "name": p.name, "path": f.path,
                "ext": p.suffix.lower().lstrip("."), "mime": f.type, "size": f.size,
                "snippet": (text_snippets.get(f.id,"")[:max_snip] if f.id in text_snippets else "")
            })
        return out

    # LLM category discovery (no hardcoded subcats)
    categories: Dict[str, Dict[str, List[str]]] = {}
    if llm_endpoint and llm_model:
        for bucket, subset in buckets.items():
            if not subset: continue
            inv = inventory(subset)
            try:
                cat_list = llm_discover_categories(llm_endpoint, llm_model, bucket, inv, api_key)
                for c in cat_list:
                    label = (c.label or "Uncategorized")[:80]
                    categories.setdefault(bucket, {}).setdefault(label, []).extend(c.file_ids)
                    summaries[f"sub:{bucket}:{label}"] = f"{c.rationale} (conf {round(c.confidence,2)})"
            except Exception as e:
                summaries[f"sub:{bucket}:Uncategorized"] = f"LLM discovery failed: {e}"
                categories.setdefault(bucket, {})["Uncategorized"] = [f.id for f in subset]
    else:
        # fallback: just base buckets
        for bucket, subset in buckets.items():
            if subset:
                categories.setdefault(bucket, {})[f"All {bucket}"] = [f.id for f in subset]
                summaries[f"sub:{bucket}:All {bucket}"] = f"{len(subset)} files (fallback)."

    # Build graph
    graph = build_graph(
        files, dup, typ, age,
        near_dup_clusters=near_dup_clusters,
        summaries=summaries,
        categories=categories
    )

    # Plan (moves + deletes)
    id_to_path = {f.id: f.path for f in files}
    moves: List[Dict[str, Any]] = []
    deletes: List[Dict[str, Any]] = []

    # Deletes: dups/near-dups/temp/imagesim
    for _, ids in dup.items():
        for fid in ids[1:]:
            deletes.append({"id": fid, "path": id_to_path.get(fid), "reason": "exact_duplicate", "confidence": 0.99})
    for i, ids in enumerate(near_dup_clusters):
        for fid in ids[1:]:
            deletes.append({"id": fid, "path": id_to_path.get(fid), "reason": f"near_duplicate_text:{i}", "confidence": 0.7})
    for i, ids in enumerate(image_sim_clusters):
        for fid in ids[1:]:
            deletes.append({"id": fid, "path": id_to_path.get(fid), "reason": f"near_duplicate_image:{i}", "confidence": 0.7})
    for f in files:
        name = Path(f.path).name.lower()
        if any(name.endswith(suf) for suf in [".tmp",".log",".bak",".old","~"]):
            deletes.append({"id": f.id, "path": f.path, "reason": "temp_suffix", "confidence": 0.6})

    # Moves: discovered categories => <Bucket>/<Label>/
    for bucket, subs in categories.items():
        for sub, ids in subs.items():
            dst = f"{bucket}/{_slug(sub)}/"
            for fid in ids:
                moves.append({"id": fid, "from": id_to_path.get(fid), "to": dst, "reason": f"{bucket}:{sub}"})

    # Size + cost per cluster (for UI)
    def file_size(fid): 
        f = id_to_file.get(fid); return int(getattr(f, "size", 0) or 0)
    cluster_costs: Dict[str, Any] = {}
    if storage_rate_per_gb > 0:
        for bucket, subs in categories.items():
            for sub, ids in subs.items():
                total_bytes = sum(file_size(fid) for fid in ids)
                gb = total_bytes / (1024**3)
                cluster_costs[f"{bucket}:{sub}"] = {
                    "bytes": total_bytes,
                    "gb": round(gb, 4),
                    "monthly_cost": round(gb * storage_rate_per_gb, 4)
                }

    plan = {
        "summary": {
            "files_scanned": len(files),
            "duplicate_clusters": len(dup),
            "near_duplicate_clusters": len(near_dup_clusters),
            "image_similarity_clusters": len(image_sim_clusters),
            "suggested_deletions": len(deletes),
            "suggested_moves": len(moves),
            "elapsed_sec": round(time.time() - t0, 2),
            "storage_rate_per_gb": storage_rate_per_gb,
        },
        "moves": moves,
        "deletes": deletes,
        "cluster_costs": cluster_costs
    }

    return {"graph": graph, "summaries": summaries, "plan": plan}
