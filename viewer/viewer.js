// viewer/viewer.js
// Offline, dependency-free SVG viewer for RAZE graph.json + summaries.json (+ plan.json)

const COLORS = {
  root: "var(--root)",
  category: "#a78bfa",
  subcategory: "#38bdf8",
  duplicate_cluster: "var(--dup)",
  near_duplicate_text: "var(--neardup)",
  type_cluster: "var(--type)",
  age_bucket: "var(--age)",
  file: "var(--file)"
};

const ROWS = [
  "root",
  "category",
  "subcategory",
  "duplicate_cluster",
  "near_duplicate_text",
  "type_cluster",
  "age_bucket",
  "file"
];

const state = {
  graph: null,
  summaries: {},
  plan: null,
  filterKind: "all",
  minConf: 0,
  search: "",
  edgeMode: "none",   // "none" | "all" | "selected"
  selectedId: null
};

const $ = (sel) => document.querySelector(sel);
const svgNS = "http://www.w3.org/2000/svg";

// ---------- Boot + UI wiring ----------

document.addEventListener("DOMContentLoaded", async () => {
  // Try auto-load from ../
  try {
    const g = await fetchJSON("../graph.json");
    let s = {}; try { s = await fetchJSON("../summaries.json"); } catch {}
    let p = null; try { p = await fetchJSON("../plan.json"); } catch {}
    state.plan = p;
    loadData(g, s);
  } catch {
    // ignore; user can use buttons or drag&drop
  }

  // Buttons / pickers
  $("#load-local")?.addEventListener("click", async () => {
    try {
      const g = await fetchJSON("../graph.json");
      let s = {}; try { s = await fetchJSON("../summaries.json"); } catch {}
      let p = null; try { p = await fetchJSON("../plan.json"); } catch {}
      state.plan = p;
      loadData(g, s);
    } catch (e) {
      alert("Could not load ../graph.json (make sure the viewer folder sits next to it).");
    }
  });

  $("#file-graph")?.addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    state.graph = await file.text().then(JSON.parse);
    maybeRender();
  });

  $("#file-summaries")?.addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    state.summaries = await file.text().then(JSON.parse);
    maybeRender();
  });

  $("#filter-kind")?.addEventListener("change", (e) => {
    state.filterKind = e.target.value;
    render();
  });

  $("#min-conf")?.addEventListener("input", (e) => {
    state.minConf = parseFloat(e.target.value || "0");
    render();
  });

  $("#search")?.addEventListener("input", (e) => {
    state.search = (e.target.value || "").toLowerCase();
    render();
  });

  // Edge mode (safer init + listener)
  const edgeSelect = document.getElementById("edge-mode");
  state.edgeMode = (edgeSelect && edgeSelect.value) || "none";
  state.selectedId = null;
  edgeSelect && edgeSelect.addEventListener("change", (e) => {
    state.edgeMode = e.target.value || "none";
    render();
  });

  // Drag & drop
  document.body.addEventListener("dragover", (e) => e.preventDefault());
  document.body.addEventListener("drop", async (e) => {
    e.preventDefault();
    const files = [...(e.dataTransfer?.files || [])];
    for (const f of files) {
      const data = await f.text().then(JSON.parse).catch(() => null);
      if (!data) continue;
      if (f.name.toLowerCase().includes("graph")) state.graph = data;
      else if (f.name.toLowerCase().includes("summaries")) state.summaries = data;
      else if (f.name.toLowerCase().includes("plan")) state.plan = data;
    }
    maybeRender();
  });
});

// ---------- Data + rendering ----------

function loadData(graph, summaries) {
  state.graph = graph;
  state.summaries = summaries || {};
  state.selectedId = null;
  maybeRender();
}

function maybeRender() {
  if (!state.graph) return;
  render();
}

async function fetchJSON(rel) {
  const res = await fetch(rel, { cache: "no-store" });
  if (!res.ok) throw new Error("fetch failed");
  return res.json();
}

function render() {
  const svg = $("#canvas");
  while (svg.firstChild) svg.removeChild(svg.firstChild);

  if (!state.graph) return;
  const { nodes, edges } = state.graph;

  // Indexes
  const nodeById = new Map(nodes.map((n) => [n.id, n]));
  const outEdges = new Map();
  for (const e of edges) {
    if (!outEdges.has(e.source)) outEdges.set(e.source, []);
    outEdges.get(e.source).push(e);
  }

  // Filter nodes
  const filtered = nodes.filter((n) => {
    if (state.filterKind !== "all" && n.kind !== state.filterKind) return false;
    const conf =
      n?.reasoning && typeof n.reasoning.confidence === "number"
        ? n.reasoning.confidence
        : 1.0;
    if (conf < state.minConf) return false;
    if (state.search) {
      const label = (n.label || "").toLowerCase();
      const path = (n.meta && n.meta.path ? n.meta.path : "").toLowerCase();
      if (!label.includes(state.search) && !path.includes(state.search)) return false;
    }
    return true;
  });

  // Layout rows
  const rows = new Map(ROWS.map((k, i) => [k, i]));
  const margin = { left: 40, top: 40, xgap: 24, ygap: 160 };
  const size = { w: 260, h: 44 };

  // Positions
  const positions = new Map();
  const rowCounts = new Map();
  for (const n of filtered) {
    const ri = rows.get(n.kind) ?? rows.get("file");
    const idx = rowCounts.get(ri) || 0;
    rowCounts.set(ri, idx + 1);
    const x = margin.left + idx * (size.w + margin.xgap);
    const y = margin.top + ri * margin.ygap;
    positions.set(n.id, { x, y });
  }

  // Edges: only draw per mode
  const shouldDraw = (e) => {
    if (!positions.has(e.source) || !positions.has(e.target)) return false;
    if (state.edgeMode === "none") return false;
    if (state.edgeMode === "all") return true;
    if (state.edgeMode === "selected") {
      const id = state.selectedId;
      return !!id && (e.source === id || e.target === id);
    }
    return false;
  };

  for (const e of edges) {
    if (!shouldDraw(e)) continue;
    const a = positions.get(e.source);
    const b = positions.get(e.target);
    const line = document.createElementNS(svgNS, "line");
    line.setAttribute("x1", a.x + size.w / 2);
    line.setAttribute("y1", a.y + size.h / 2);
    line.setAttribute("x2", b.x + size.w / 2);
    line.setAttribute("y2", b.y + size.h / 2);
    line.setAttribute("class", "edge");
    svg.appendChild(line);
  }

  // Nodes
  for (const n of filtered) {
    const p = positions.get(n.id);
    const g = document.createElementNS(svgNS, "g");
    g.setAttribute("class", `node kind-${n.kind}`);
    g.setAttribute("tabindex", "0");
    g.addEventListener("click", () => selectNode(n, nodeById, outEdges));
    g.addEventListener("keypress", (ev) => {
      if (ev.key === "Enter") selectNode(n, nodeById, outEdges);
    });

    const rect = document.createElementNS(svgNS, "rect");
    rect.setAttribute("x", p.x);
    rect.setAttribute("y", p.y);
    rect.setAttribute("width", size.w);
    rect.setAttribute("height", size.h);
    rect.setAttribute("rx", 10);
    rect.setAttribute("ry", 10);
    rect.setAttribute("class", `node kind-${n.kind}`);
    rect.setAttribute("fill", "none");
    rect.setAttribute("stroke", "currentColor");
    g.appendChild(rect);

    const mark = document.createElementNS(svgNS, "circle");
    mark.setAttribute("cx", p.x + 10);
    mark.setAttribute("cy", p.y + 10);
    mark.setAttribute("r", 4);
    mark.setAttribute("fill", getKindColor(n.kind));
    g.appendChild(mark);

    const label = document.createElementNS(svgNS, "text");
    label.setAttribute("x", p.x + 14);
    label.setAttribute("y", p.y + 28);
    label.textContent = tidyLabel(n.label);
    g.appendChild(label);

    svg.appendChild(g);
  }

  // Row labels
  for (const [kind, ri] of rows.entries()) {
    const y = margin.top + ri * margin.ygap - 10;
    const t = document.createElementNS(svgNS, "text");
    t.setAttribute("x", 8);
    t.setAttribute("y", y);
    t.setAttribute("fill", "var(--muted)");
    t.textContent = kind;
    svg.appendChild(t);
  }
}

function tidyLabel(s) {
  if (!s) return "";
  return s.length > 40 ? s.slice(0, 37) + "…" : s;
}

function getKindColor(kind) {
  return getComputedStyle(document.documentElement).getPropertyValue(
    {
      root: "--root",
      duplicate_cluster: "--dup",
      near_duplicate_text: "--neardup",
      type_cluster: "--type",
      age_bucket: "--age",
      file: "--file"
    }[kind] || "--fg"
  );
}

function selectNode(n, nodeById, outEdges) {
  // remember selection so edge mode = "selected" works
  state.selectedId = n.id;
  render(); // re-draw edges per mode

  const panel = $("#inspector #details");
  const conf = n.reasoning?.confidence;
  const rationale = n.reasoning?.rationale || "";
  const meta = n.meta || {};
  const summary =
    meta.summary || (window.summaries && window.summaries[n.id]) || "";

  const files = (outEdges.get(n.id) || [])
    .filter((e) => nodeById.get(e.target)?.kind === "file")
    .slice(0, 40)
    .map((e) => nodeById.get(e.target)?.label);

  const lines = [];
  lines.push(`ID: ${n.id}`);
  lines.push(`Kind: ${n.kind}`);
  lines.push(`Label: ${n.label}`);
  if (typeof conf === "number") lines.push(`Confidence: ${conf}`);
  if (summary) lines.push(`Summary: ${summary}`);
  if (rationale) lines.push(`Reasoning: ${rationale}`);
  if (meta.hash) lines.push(`Hash: ${meta.hash}`);
  if (Array.isArray(meta.file_ids)) lines.push(`Files in cluster: ${meta.file_ids.length}`);

  // plan awareness (moves + deletes)
  if (state.plan && Array.isArray(meta.file_ids)) {
    const delSet = new Set((state.plan.deletes || []).map((i) => i.id));
    const moveSet = new Set((state.plan.moves || []).map((i) => i.id));
    const delHits = meta.file_ids.filter((id) => delSet.has(id)).length;
    const moveHits = meta.file_ids.filter((id) => moveSet.has(id)).length;
    lines.push(`Planned deletes in cluster: ${delHits}`);
    lines.push(`Planned moves in cluster: ${moveHits}`);
  }

  if (files.length) {
    lines.push("");
    lines.push("Sample files:");
    for (const f of files) lines.push("• " + f);
  }

  panel.innerHTML = `<pre>${escapeHtml(lines.join("\n"))}</pre>`;
}

function escapeHtml(s) {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}
