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
                summaries: dict | None = None,
                categories: Dict[str, Dict[str, List[str]]] | None = None) -> Dict[str, Any]:
    nodes: List[Node] = []
    edges: List[Edge] = []

    # Root
    root_id = "root"
    nodes.append(Node(
        id=root_id,
        kind="root",
        label="Scan Root",
        meta={},
        reasoning={"rationale": "Root of scan.", "confidence": 1.0}
    ))

    # --- AI/auto categories (optional) ---
    if categories:
        for bucket, subs in categories.items():
            cat_id = f"cat:{bucket}"
            nodes.append(Node(
                id=cat_id,
                kind="category",
                label=bucket,
                meta={"subcount": len(subs)},
                reasoning={"rationale": "Category bucket", "confidence": 0.8}
            ))
            edges.append(Edge(id=f"e-{root_id}-{cat_id}", source=root_id, target=cat_id, kind="contains"))

            for sub, ids in subs.items():
                sub_id = f"sub:{bucket}:{sub}"
                meta = {"file_ids": ids, "bucket": bucket}
                if summaries:
                    meta["summary"] = summaries.get(sub_id, "")
                nodes.append(Node(
                    id=sub_id,
                    kind="subcategory",
                    label=f"{bucket} → {sub}",
                    meta=meta,
                    reasoning={"rationale": f"Files categorized as {bucket}/{sub}", "confidence": 0.75}
                ))
                edges.append(Edge(id=f"e-{cat_id}-{sub_id}", source=cat_id, target=sub_id, kind="contains"))
                for fid in ids[:50]:
                    edges.append(Edge(id=f"e-{sub_id}-{fid}", source=sub_id, target=fid, kind="contains_sample"))

    # Exact duplicate clusters
    for h, ids in dup_clusters.items():
        nid = f"dup:{h[:8]}"
        meta = {"hash": h, "file_ids": ids}
        if summaries:
            meta["summary"] = summaries.get(nid, "")
        reasoning = suggest_node_reasoning("duplicate_cluster", {"file_ids": ids})
        nodes.append(Node(
            id=nid,
            kind="duplicate_cluster",
            label=f"Duplicates {h[:8]}",
            meta=meta,
            reasoning=reasoning
        ))
        edges.append(Edge(id=f"e-{root_id}-{nid}", source=root_id, target=nid, kind="contains"))
        for fid in ids:
            edges.append(Edge(id=f"e-{nid}-{fid}", source=nid, target=fid, kind="contains"))

    # Type clusters (now base buckets)
    for t, ids in type_clusters.items():
        nid = f"type:{t}"
        meta = {"file_ids": ids, "bucket": t}
        if summaries:
            meta["summary"] = summaries.get(nid, "")
        reasoning = suggest_node_reasoning("type_cluster", {"type": t, "file_ids": ids})
        nodes.append(Node(
            id=nid,
            kind="type_cluster",
            label=f"Type: {t}",
            meta=meta,
            reasoning=reasoning
        ))
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
        nodes.append(Node(
            id=nid,
            kind="age_bucket",
            label=f"Age: {label}",
            meta=meta,
            reasoning=reasoning
        ))
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
            nodes.append(Node(
                id=nid,
                kind="near_duplicate_text",
                label=f"Near-duplicates #{idx}",
                meta=meta,
                reasoning=reasoning
            ))
            edges.append(Edge(id=f"e-{root_id}-{nid}", source=root_id, target=nid, kind="contains"))
            for fid in ids[:50]:
                edges.append(Edge(id=f"e-{nid}-{fid}", source=nid, target=fid, kind="contains_sample"))

    # (Image similarity clusters can be added here later if we choose to render them inside the graph.)

    # File leaf nodes (sample only for graph size)
    for f in files[:200]:
        nodes.append(Node(
            id=f.id,
            kind="file",
            label=f.path,
            meta={"size": f.size, "mtime": f.mtime, "type": f.type, "hash": f.hash},
            reasoning={"rationale": "Raw file node", "confidence": 1.0}
        ))

    return {
        "nodes": [asdict(n) for n in nodes],
        "edges": [asdict(e) for e in edges],
    }
