from __future__ import annotations
from typing import Dict, List
from .ingest import FileMeta

MAX_SNIPPET = 800  # chars per cluster summary

def summarize_cluster(file_ids: List[str],
                      file_lookup: Dict[str, FileMeta],
                      snippets: Dict[str, str]) -> str:
    lines = []
    total = len(file_ids)
    sizes = sum((file_lookup[fid].size for fid in file_ids if fid in file_lookup), 0)
    lines.append(f"Files: {total}, Total bytes: {sizes}")
    # include up to first 2 text snippets
    count = 0
    for fid in file_ids:
        snip = snippets.get(fid)
        if snip:
            s = snip.strip().replace("\n", " ")
            if s:
                lines.append(f"Snippet[{fid[:6]}]: {s[:160]}")
                count += 1
        if count >= 2:
            break
    out = " | ".join(lines)
    return out[:MAX_SNIPPET]
