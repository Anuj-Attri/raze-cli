from __future__ import annotations
import subprocess, shutil, zipfile, re
from pathlib import Path
from typing import Optional

# Lightweight, offline text extraction for small text-like files.
TEXT_EXT = {
    ".txt", ".md", ".csv", ".log", ".json", ".yaml", ".yml", ".xml", ".html", ".htm"
}

def _read_small_text(path: Path, max_bytes: int = 3_000_000) -> Optional[str]:
    try:
        if path.stat().st_size > max_bytes:
            return None
        raw = path.read_bytes()
        for enc in ("utf-8", "utf-16", "latin-1"):
            try:
                return raw.decode(enc, errors="ignore")
            except Exception:
                continue
        return None
    except Exception:
        return None

def _pdftotext(path: Path, max_pages: int = 5) -> Optional[str]:
    exe = shutil.which("pdftotext")
    if not exe:
        return None
    try:
        tmp = path.with_suffix(".phase2_excerpt.txt")
        subprocess.run([exe, "-l", str(max_pages), "-q", str(path), str(tmp)], check=True)
        text = tmp.read_text(encoding="utf-8", errors="ignore")
        tmp.unlink(missing_ok=True)
        return text
    except Exception:
        return None

_TAG = re.compile(r"<[^>]+>")

def _docx_text(path: Path, max_chars: int = 20000) -> Optional[str]:
    # No external deps: unzip and read word/document.xml, strip tags.
    try:
        with zipfile.ZipFile(path) as zf:
            with zf.open("word/document.xml") as f:
                xml = f.read().decode("utf-8", errors="ignore")
                text = _TAG.sub(" ", xml)
                return " ".join(text.split())[:max_chars]
    except Exception:
        return None

def extract_text_snippet(path: str, mime_guess: str) -> Optional[str]:
    p = Path(path)
    ext = p.suffix.lower()

    if ext in TEXT_EXT or (mime_guess or "").startswith("text/"):
        return _read_small_text(p, max_bytes=3_000_000)

    if ext == ".pdf" or mime_guess == "application/pdf":
        return _pdftotext(p, max_pages=5)

    if ext in (".docx",):
        return _docx_text(p)

    return None
