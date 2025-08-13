from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import List, Dict, Any
from .ingest import FileMeta
from .reasoner_stub import suggest_node_reasoning

@dataclass
class Node:
    id: str
    kind: str
    label: str
    meta: Dict[str, Any]
    reasoning: Dict[str, Any]

@dataclass
class Edge:
    id: str
    source: str
    target: str
    kind: str

def build_graph(files: List[FileMeta],
                dup_clusters: Dict[str, List[str]],
                type_clusters: Dict[str, List[str]],
                age_clusters: Dict[str, List[str]],
                near_dup_clusters: List[List[str]] | None = None,
                summaries: dict | None = None) -> Dict[str, Any]:
    nodes: List[Node] = []
    edges: List[Edge] = []

    # Root
    root_id = "root"
    nodes.append(Node(id=root_id, kind="root", label="Scan Root",
                      meta={}, reasoning={"rationale": "Root of scan.", "confidence": 1.0}))

    # Exact duplicate clusters
    for h, ids in dup_clusters.items():
        nid = f"dup:{h[:8]}"
        meta = {"hash": h, "file_ids": ids}
        if summaries:
            meta["summary"] = summaries.get(nid, "")
        reasoning = suggest_node_reasoning("duplicate_cluster", {"file_ids": ids})
        nodes.append(Node(id=nid, kind="duplicate_cluster", label=f"Duplicates {h[:8]}",
                          meta=meta, reasoning=reasoning))
        edges.append(Edge(id=f"e-{root_id}-{nid}", source=root_id, target=nid, kind="contains"))
        for fid in ids:
            edges.append(Edge(id=f"e-{nid}-{fid}", source=nid, target=fid, kind="contains"))

    # Type clusters
    for t, ids in type_clusters.items():
        nid = f"type:{t}"
        meta = {"file_ids": ids}
        if summaries:
            meta["summary"] = summaries.get(nid, "")
        reasoning = suggest_node_reasoning("type_cluster", {"type": t, "file_ids": ids})
        nodes.append(Node(id=nid, kind="type_cluster", label=f"Type: {t}",
                          meta=meta, reasoning=reasoning))
        edges.append(Edge(id=f"e-{root_id}-{nid}", source=root_id, target=nid, kind="contains"))
        for fid in ids[:50]:  # sample edges to avoid explosion
            edges.append(Edge(id=f"e-{nid}-{fid}", source=nid, target=fid, kind="contains_sample"))

    # Age buckets
    for label, ids in age_clusters.items():
        nid = f"age:{label}"
        meta = {"file_ids": ids}
        if summaries:
            meta["summary"] = summaries.get(nid, "")
        reasoning = suggest_node_reasoning("age_bucket", {"label": label, "file_ids": ids})
        nodes.append(Node(id=nid, kind="age_bucket", label=f"Age: {label}",
                          meta=meta, reasoning=reasoning))
        edges.append(Edge(id=f"e-{root_id}-{nid}", source=root_id, target=nid, kind="contains"))
        for fid in ids[:50]:
            edges.append(Edge(id=f"e-{nid}-{fid}", source=nid, target=fid, kind="contains_sample"))

    # Near-duplicate text clusters
    if near_dup_clusters:
        for idx, ids in enumerate(near_dup_clusters):
            nid = f"neardup:{idx}"
            meta = {"file_ids": ids}
            if summaries:
                meta["summary"] = summaries.get(nid, "")
            reasoning = suggest_node_reasoning("duplicate_cluster", {"file_ids": ids})
            nodes.append(Node(id=nid, kind="near_duplicate_text", label=f"Near-duplicates #{idx}",
                              meta=meta, reasoning=reasoning))
            edges.append(Edge(id=f"e-{root_id}-{nid}", source=root_id, target=nid, kind="contains"))
            for fid in ids[:50]:
                edges.append(Edge(id=f"e-{nid}-{fid}", source=nid, target=fid, kind="contains_sample"))

    # File leaf nodes (sample only for graph size)
    for f in files[:200]:
        nodes.append(Node(
            id=f.id, kind="file", label=f.path,
            meta={"size": f.size, "mtime": f.mtime, "type": f.type, "hash": f.hash},
            reasoning={"rationale": "Raw file node", "confidence": 1.0}
        ))

    return {"nodes": [asdict(n) for n in nodes],
            "edges": [asdict(e) for e in edges]}
