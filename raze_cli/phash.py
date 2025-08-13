from __future__ import annotations
from pathlib import Path
from typing import Optional, List, Tuple
import math

try:
    from PIL import Image  # pip install pillow
except Exception:
    Image = None

IMG_EXT = {".jpg",".jpeg",".png",".gif",".webp",".bmp",".tif",".tiff",".heic",".heif"}

def _dct_1d(v):
    n = len(v); res = [0.0]*n
    factor = math.pi / (2*n)
    scale0 = math.sqrt(1/n)
    scale = math.sqrt(2/n)
    for k in range(n):
        s = 0.0
        for i, x in enumerate(v):
            s += x * math.cos((2*i+1)*k*factor)
        res[k] = s * (scale0 if k == 0 else scale)
    return res

def _dct_2d(m):
    # m: list of rows
    n = len(m)
    cols = list(zip(*m))
    t = [ _dct_1d(list(row)) for row in m ]
    tt = list(zip(*t))
    u = [ _dct_1d(list(col)) for col in tt ]
    return [ list(row) for row in zip(*u) ]

def phash64(path: str) -> Optional[int]:
    if Image is None: return None
    p = Path(path)
    if p.suffix.lower() not in IMG_EXT: return None
    try:
        img = Image.open(p).convert("L").resize((32,32), resample=Image.BILINEAR)
        pixels = list(img.getdata())
        m = [pixels[i*32:(i+1)*32] for i in range(32)]
        d = _dct_2d(m)
        # take 8x8 low-frequency (skip [0][0])
        bits = []
        sub = [row[:8] for row in d[:8]]
        mean = (sum(sum(row) for row in sub) - sub[0][0]) / (8*8 - 1)
        for r in range(8):
            for c in range(8):
                if r == 0 and c == 0: continue
                bits.append(1 if sub[r][c] > mean else 0)
        # pack to 64 bits (we have 63 bits; pad one 0)
        out = 0
        for b in bits[:63]: out = (out << 1) | b
        out <<= 1
        return out
    except Exception:
        return None

def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()

def cluster_phash(items: List[Tuple[str,int]], threshold: int = 12) -> List[List[str]]:
    visited = [False]*len(items)
    clusters = []
    for i,(fid,hi) in enumerate(items):
        if visited[i]: continue
        group = [fid]; visited[i] = True
        for j,(fid2,hj) in enumerate(items):
            if visited[j]: continue
            if hamming(hi,hj) <= threshold:
                group.append(fid2); visited[j] = True
        if len(group) > 1: clusters.append(group)
    return clusters
