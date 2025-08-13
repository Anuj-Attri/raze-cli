from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Tuple
from pathlib import Path
import re, math

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from .ingest import FileMeta

@dataclass
class ClusterResult:
    label: str
    file_ids: List[str]
    top_terms: List[str]
    score: float  # silhouette-like quality (approx)

_WORD = re.compile(r"[A-Za-z0-9_]+")

def _normalize(s: str) -> str:
    return " ".join(_WORD.findall(s.lower()))

def build_descriptor(f: FileMeta, snippet: str | None) -> str:
    p = Path(f.path)
    fields = [
        p.name, p.parent.name,
        f.type.split("/")[0],
        p.suffix.lower().lstrip("."),
        (snippet or "")[:2000]
    ]
    return _normalize(" ".join(x for x in fields if x))

def _auto_k(n: int) -> List[int]:
    # candidates; bounded and odd sizes (reduce “split” effect)
    ks = sorted(set([2,3,4,5,6,8,10, max(2, n//6), max(2, n//4), max(2, n//3)]))
    return [k for k in ks if 2 <= k < n]

def cluster_and_label(files: List[FileMeta],
                      text_snippets: Dict[str,str]) -> List[ClusterResult]:
    if len(files) < 3:
        return [ClusterResult("all", [f.id for f in files], [], 1.0)]

    ids, docs = [], []
    for f in files:
        ids.append(f.id)
        docs.append(build_descriptor(f, text_snippets.get(f.id)))

    vec = TfidfVectorizer(max_features=6000, ngram_range=(1,2), min_df=1)
    X = vec.fit_transform(docs)

    # choose K by best silhouette over small candidate set (fast)
    best = None
    best_k = 2
    for k in _auto_k(len(files)):
        try:
            km = KMeans(n_clusters=k, n_init="auto", random_state=42).fit(X)
            s = silhouette_score(X, km.labels_, sample_size=min(1000, len(files)))
            if (best is None) or (s > best[0]):
                best = (s, km)
                best_k = k
        except Exception:
            continue
    if best is None:
        km = KMeans(n_clusters=best_k, n_init="auto", random_state=42).fit(X)
        s = 0.0
    else:
        s, km = best

    feats = vec.get_feature_names_out()
    centroids = km.cluster_centers_
    labels = km.labels_

    clusters: Dict[int, List[int]] = {}
    for i, lab in enumerate(labels):
        clusters.setdefault(lab, []).append(i)

    results: List[ClusterResult] = []
    for lab, idxs in clusters.items():
        centroid = centroids[lab]
        order = centroid.argsort()[::-1]
        terms = [feats[i] for i in order[:8]]
        # dominant extension hint
        ext_counts: Dict[str,int] = {}
        for i in idxs:
            ext = Path(files[i].path).suffix.lower().lstrip(".")
            ext_counts[ext] = ext_counts.get(ext, 0) + 1
        dom_ext = max(ext_counts, key=ext_counts.get) if ext_counts else ""
        prefix = f"{dom_ext} " if dom_ext else ""
        label = (prefix + ", ".join(terms[:4])).strip(", ")
        results.append(ClusterResult(
            label=label or f"cluster_{lab}",
            file_ids=[ids[i] for i in idxs],
            top_terms=terms,
            score=float(s)
        ))
    return results
