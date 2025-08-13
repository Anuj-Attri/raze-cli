from __future__ import annotations
from pathlib import Path
import shutil, json, time, os

def apply_plan(plan_path: str, root: str, dry_run: bool = False, quarantine_days: int = 30) -> str:
    rootp = Path(root)
    if not rootp.exists(): raise FileNotFoundError(root)
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))

    ts = time.strftime("%Y%m%d-%H%M%S")
    qroot = rootp / f".quarantine/{ts}"
    audit = rootp / f".raze-audit-{ts}.jsonl"
    if not dry_run:
        qroot.mkdir(parents=True, exist_ok=True)

    def _log(rec): 
        with audit.open("a", encoding="utf-8") as f: f.write(json.dumps(rec)+"\n")

    # Moves
    for mv in plan.get("moves", []):
        src = Path(mv.get("from") or "")
        if not src.exists(): 
            _log({"op":"move","status":"skip_not_found","src":str(src),"to":mv.get("to")}); 
            continue
        dst_dir = rootp / mv["to"].lstrip("/\\")
        dst_dir.mkdir(parents=True, exist_ok=True) if not dry_run else None
        dst = dst_dir / src.name
        _log({"op":"move","status":"dry_run" if dry_run else "moved","src":str(src),"dst":str(dst)})
        if not dry_run:
            shutil.move(str(src), str(dst))

    # Deletes -> quarantine
    for de in plan.get("deletes", []):
        src = Path(de.get("path") or "")
        if not src.exists():
            _log({"op":"delete","status":"skip_not_found","src":str(src),"reason":de.get("reason")})
            continue
        qdst = qroot / src.name
        _log({"op":"delete","status":"dry_run" if dry_run else "quarantined","src":str(src),"qdst":str(qdst),"reason":de.get("reason")})
        if not dry_run:
            shutil.move(str(src), str(qdst))

    # retention note
    _log({"op":"meta","quarantine":str(qroot),"retention_days":quarantine_days})
    return str(audit)
