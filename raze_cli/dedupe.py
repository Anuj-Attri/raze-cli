from __future__ import annotations
from typing import List, Dict, Any, DefaultDict
from collections import defaultdict
from .ingest import FileMeta

def cluster_by_duplicate(files: List[FileMeta]) -> Dict[str, list[str]]:
    """Return mapping hash -> list[file_id] for files with same content hash (non-None)."""
    by_hash: DefaultDict[str, list[str]] = defaultdict(list)
    for f in files:
        if f.hash:
            by_hash[f.hash].append(f.id)
    return {h: ids for h, ids in by_hash.items() if len(ids) > 1}

def cluster_by_type(files: List[FileMeta]) -> Dict[str, list[str]]:
    by_type: DefaultDict[str, list[str]] = defaultdict(list)
    for f in files:
        by_type[f.type.split('/')[0]].append(f.id)  # coarse: text, image, audio, video, application
    return dict(by_type)

def cluster_by_age(files: List[FileMeta], now: float) -> Dict[str, list[str]]:
    buckets = {"new(<30d)": [], "stale(30-180d)": [], "old(>180d)": []}
    for f in files:
        age_days = (now - f.mtime)/86400.0
        if age_days < 30: buckets["new(<30d)"].append(f.id)
        elif age_days < 180: buckets["stale(30-180d)"].append(f.id)
        else: buckets["old(>180d)"].append(f.id)
    return buckets

def cluster_near_duplicate_text(simhash_items):
    """
    simhash_items: list of (file_id, simhash64 int)
    Returns list of clusters (list of file_id lists).
    """
    from .simhash import cluster_near_dups
    return cluster_near_dups(simhash_items, threshold=8)

