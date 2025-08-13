
from __future__ import annotations
import os, hashlib, mimetypes, time
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Dict, Any

@dataclass
class FileMeta:
    id: str
    path: str
    size: int
    mtime: float
    type: str  # mime guess
    hash: str | None  # sha256 (only for small files), else None

def sha256_file(path: Path, max_bytes: int | None = 5_000_000) -> str | None:
    try:
        if max_bytes is not None and path.stat().st_size > max_bytes:
            return None
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None

def scan_directory(root: str) -> List[FileMeta]:
    files: List[FileMeta] = []
    rootp = Path(root)
    for p in rootp.rglob("*"):
        if not p.is_file():
            continue
        try:
            st = p.stat()
            mime, _ = mimetypes.guess_type(p.name)
            mime = mime or "application/octet-stream"
            digest = sha256_file(p)
            fid = hashlib.md5(str(p).encode("utf-8")).hexdigest()
            files.append(FileMeta(
                id=fid,
                path=str(p),
                size=st.st_size,
                mtime=st.st_mtime,
                type=mime,
                hash=digest
            ))
        except Exception:
            continue
    return files

def to_dicts(files: List[FileMeta]) -> List[Dict[str, Any]]:
    return [asdict(f) for f in files]
