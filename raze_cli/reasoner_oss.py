# raze_cli/reasoner_oss.py
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Any, Tuple
from urllib.parse import urljoin
import json, time, math, re, requests

@dataclass
class LLMCategory:
    bucket: str          # one of: Images, Documents, Audio, Video, Other
    label: str           # discovered subcategory name (from data, not hard-coded)
    file_ids: List[str]
    rationale: str
    confidence: float

# Prompt: discover subcategories *from content* inside a single base bucket.
DISCOVER_PROMPT = """You are an offline data-restructuring copilot.
You will receive a BASE BUCKET (Images, Documents, Audio, Video, or Other) and a list of files with lightweight metadata:
{id, name, path, ext, mime, size, snippet}.
Your tasks, LIMITED TO THE GIVEN BUCKET ONLY:

1) Discover 3–12 meaningful SUBCATEGORIES that are grounded in the ACTUAL CONTENT (from snippet/metadata) of these files.
   - Do NOT invent generic names that do not reflect this set.
   - Do NOT base categories only on extension or file name patterns unless content corroborates it.
   - Prefer mutually exclusive subcategories. If ambiguous, choose 'Uncategorized'.

2) Assign each file id to at most one subcategory. If uncertain, put it in 'Uncategorized'.

3) Return STRICT JSON ONLY (no commentary) in this schema:
{
  "categories": [
    {"label": "<subcategory name>", "file_ids": ["f1","f2",...],
     "rationale": "<why these files form a coherent content-based cluster>",
     "confidence": 0.0-1.0}
  ],
  "uncategorized": ["..."]
}

Notes:
- Keep labels concise but descriptive (learned from this batch).
- Use conservative assignments: it's OK to leave files in 'Uncategorized' if unsure.
"""

def _normalize_endpoint(endpoint: str) -> str:
    """
    Accepts:
      http://localhost:11434
      http://localhost:11434/
      http://localhost:11434/v1
      http://localhost:11434/v1/
    Returns the full /v1/chat/completions base URL.
    """
    e = endpoint.rstrip("/")
    if e.endswith("/v1"):
        return e + "/chat/completions"
    if e.endswith("/v1/chat/completions"):
        return e
    # allow bare host:port
    return e + "/v1/chat/completions"

def _openai_chat(endpoint: str, model: str, messages: List[Dict[str, Any]],
                 api_key: str | None, max_tokens: int, temperature: float,
                 timeout: int = 180) -> Dict[str, Any]:
    url = _normalize_endpoint(endpoint)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()

from typing import Optional

def _find_json_object(text: str) -> Optional[str]:
    """
    Return the largest balanced JSON object substring from `text`, or None.
    Handles braces inside quoted strings and escaped quotes.
    """
    if not text:
        return None

    best_start = best_end = -1
    in_str = False
    esc = False
    depth = 0
    start_idx = -1

    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
            continue

        # not in string
        if ch == '"':
            in_str = True
            continue

        if ch == '{':
            if depth == 0:
                start_idx = i
            depth += 1
        elif ch == '}':
            if depth > 0:
                depth -= 1
                if depth == 0 and start_idx != -1:
                    # candidate object
                    if (i - start_idx) > (best_end - best_start):
                        best_start, best_end = start_idx, i

    if best_start >= 0 and best_end >= 0:
        return text[best_start:best_end+1]
    return None

def _extract_json(text: str) -> Dict[str, Any]:
    """
    Best-effort JSON recovery:
      1) direct json.loads
      2) largest balanced object via _find_json_object
      3) fallback to empty schema
    """
    try:
        return json.loads(text)
    except Exception:
        pass

    candidate = _find_json_object(text or "")
    if candidate:
        try:
            return json.loads(candidate)
        except Exception:
            pass

    return {"categories": [], "uncategorized": []}

def _retry(fn, attempts: int = 3, base_delay: float = 1.0):
    last = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            last = e
            if i < attempts - 1:
                time.sleep(base_delay * (2 ** i))
    raise last

def _compact_inventory(inventory: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {k: v for k, v in item.items() if k in ("id","name","path","ext","mime","size","snippet")}
        for item in inventory
    ]

def _assign_unique(categories: List[LLMCategory],
                   all_ids: set[str]) -> List[LLMCategory]:
    """
    Ensure each file id is in at most one category.
    If a file appears in multiple, keep it in the category with the highest (cluster) confidence.
    """
    # build candidate list: (fid -> [(conf, idx_of_cat)])
    candidates: Dict[str, List[Tuple[float, int]]] = {}
    for idx, c in enumerate(categories):
        for fid in c.file_ids:
            if fid in all_ids:
                candidates.setdefault(fid, []).append((c.confidence, idx))

    # winner per fid
    winners: Dict[str, int] = {}
    for fid, lst in candidates.items():
        # highest confidence wins
        lst.sort(key=lambda x: x[0], reverse=True)
        winners[fid] = lst[0][1]

    # filter each category's file_ids to winners only
    pruned: List[LLMCategory] = []
    for idx, c in enumerate(categories):
        keep_ids = [fid for fid in c.file_ids if winners.get(fid) == idx]
        if keep_ids:
            pruned.append(LLMCategory(
                bucket=c.bucket,
                label=c.label,
                file_ids=keep_ids,
                rationale=c.rationale,
                confidence=c.confidence
            ))
    return pruned

def _merge_batches(bucket: str, batches: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Merge multiple JSON responses of the schema into one.
    Labels with same (casefolded) name are merged.
    """
    merged: Dict[str, Any] = {"categories": [], "uncategorized": []}
    # label -> (idx, max_confidence)
    index: Dict[str, Tuple[int, float]] = {}
    for data in batches:
        for c in data.get("categories", []):
            lab = str(c.get("label","Cluster")).strip()
            key = lab.casefold()
            file_ids = list(c.get("file_ids", []))
            rat = str(c.get("rationale","")).strip()
            conf = float(c.get("confidence", 0.5))
            if key in index:
                i, best = index[key]
                merged["categories"][i]["file_ids"].extend(file_ids)
                # keep the higher confidence rationale
                if conf > best:
                    merged["categories"][i]["rationale"] = rat
                    index[key] = (i, conf)
            else:
                index[key] = (len(merged["categories"]), conf)
                merged["categories"].append({
                    "label": lab,
                    "file_ids": file_ids,
                    "rationale": rat,
                    "confidence": conf
                })
        merged["uncategorized"].extend([str(x) for x in data.get("uncategorized", [])])
    # dedupe
    for c in merged["categories"]:
        seen = set()
        c["file_ids"] = [fid for fid in c["file_ids"] if not (fid in seen or seen.add(fid))]
    merged["uncategorized"] = list(dict.fromkeys(merged["uncategorized"]))
    return merged

def llm_discover_categories(endpoint: str,
                            model: str,
                            bucket: str,
                            inventory: List[Dict[str, Any]],
                            api_key: str | None,
                            *,
                            max_tokens: int = 1800,
                            temperature: float = 0.2,
                            batch_size: int = 400) -> List[LLMCategory]:
    """
    Discover subcategories inside one base bucket using a local OpenAI-compatible server (Ollama/vLLM/LM Studio).
    - Splits large inventories into batches and merges results.
    - Enforces unique assignment (each file id in at most one category).
    """
    if not inventory:
        return []

    compact = _compact_inventory(inventory)
    # Chunk if big
    batches = [compact[i:i+batch_size] for i in range(0, len(compact), batch_size)]

    json_blobs: List[Dict[str, Any]] = []
    for chunk in batches:
        messages = [
            {"role": "system", "content": DISCOVER_PROMPT},
            {"role": "user", "content": json.dumps({"bucket": bucket, "files": chunk}, ensure_ascii=False)}
        ]

        def _call():
            return _openai_chat(endpoint, model, messages, api_key, max_tokens=max_tokens, temperature=temperature)

        resp = _retry(_call, attempts=3, base_delay=1.0)
        # Some servers stream or wrap; we read choices[0].message.content
        content = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
        data = _extract_json(content)
        json_blobs.append(data)

    # Merge batches
    merged = _merge_batches(bucket, json_blobs)

    # Convert to dataclass list
    cats: List[LLMCategory] = []
    for c in merged.get("categories", []):
        cats.append(LLMCategory(
            bucket=bucket,
            label=str(c.get("label","Cluster")).strip(),
            file_ids=[str(x) for x in c.get("file_ids", [])],
            rationale=str(c.get("rationale","")).strip(),
            confidence=float(c.get("confidence", 0.5))
        ))

    # Ensure IDs are valid & unique-assigned
    all_ids = {str(item.get("id")) for item in compact}
    # Drop any ids not in inventory
    for c in cats:
        c.file_ids = [fid for fid in c.file_ids if fid in all_ids]

    cats = _assign_unique(cats, all_ids)

    # Optionally add Uncategorized node (remaining)
    assigned = {fid for c in cats for fid in c.file_ids}
    rest = sorted(all_ids - assigned)
    if rest:
        cats.append(LLMCategory(
            bucket=bucket,
            label="Uncategorized",
            file_ids=rest,
            rationale="Files not confidently assigned to any discovered content-based subcategory.",
            confidence=0.5
        ))

    return cats
