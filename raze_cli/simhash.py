from __future__ import annotations
import re
from typing import Iterable, List, Tuple

WORD_RE = re.compile(r"[A-Za-z0-9_]+")

def tokenize(text: str) -> List[str]:
    return [w.lower() for w in WORD_RE.findall(text)]

def shingles(tokens: List[str], k: int = 3) -> Iterable[str]:
    if len(tokens) < k:
        yield " ".join(tokens)
    else:
        for i in range(len(tokens) - k + 1):
            yield " ".join(tokens[i:i+k])

def _hash64(s: str) -> int:
    # 64-bit FNV-1a
    h = 0xcbf29ce484222325
    for b in s.encode("utf-8"):
        h ^= b
        h = (h * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return h

def simhash64(text: str, k: int = 3) -> int:
    vec = [0] * 64
    for sh in shingles(tokenize(text), k=k):
        h = _hash64(sh)
        for bit in range(64):
            vec[bit] += 1 if (h >> bit) & 1 else -1
    out = 0
    for bit, v in enumerate(vec):
        if v >= 0:
            out |= (1 << bit)
    return out

def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()

def cluster_near_dups(items: List[Tuple[str, int]], threshold: int = 8) -> List[List[str]]:
    """
    Naive O(n^2) clustering of items by Hamming distance <= threshold.
    items: [(file_id, simhash64), ...]
    """
    n = len(items)
    visited = [False] * n
    clusters: List[List[str]] = []
    for i in range(n):
        if visited[i]:
            continue
        base_id, base_h = items[i]
        cluster = [base_id]
        visited[i] = True
        for j in range(i+1, n):
            if visited[j]:
                continue
            fid, h = items[j]
            if hamming(base_h, h) <= threshold:
                cluster.append(fid)
                visited[j] = True
        if len(cluster) > 1:
            clusters.append(cluster)
    return clusters
