"""`agentes clean`: elimina restos que ya no se usan, uno por uno y con respaldo.

Busca: respaldos de migración antiguos, capturas/comparaciones viejas, hooks de Kiro 0.x (.kiro.hook) que
Kiro 1.x ya no ejecuta, carpetas vacías de otras herramientas de IA, archivos generados por el harness que
quedaron huérfanos y colecciones de vectores de modelos de embeddings que ya no usas.
Nunca toca código, documentación ni configuraciones activas del usuario.
"""
from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from .store import HARNESS_DIR

OTHER_TOOL_DIRS = [".cursor/rules", ".cursor", ".windsurf/rules", ".windsurf", ".clinerules", ".github/instructions",
                   "memory-bank", ".memory", ".ai", ".claude/commands", ".claude/agents", ".kiro/steering", ".kiro/agents"]


@dataclass
class Item:
    key: str
    desc: str
    paths: list[Path] = field(default_factory=list)
    size: int = 0
    backup: bool = True
    note: str = ""
    action: str = "delete"  # delete | collection
    extra: dict = field(default_factory=dict)


def _size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0


def _older(p: Path, days: int) -> bool:
    try:
        return time.time() - p.stat().st_mtime > days * 86400
    except OSError:
        return False


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def find(root: Path, days_backup: int = 30, days_shots: int = 14) -> list[Item]:
    root = Path(root).resolve()
    hd = root / HARNESS_DIR
    items: list[Item] = []
    old_bk = [p for p in (hd / "backup").glob("*") if p.is_dir() and _older(p, days_backup)] if (hd / "backup").exists() else []
    if old_bk:
        items.append(Item("respaldos", f"{len(old_bk)} respaldo(s) de migración/limpieza con más de {days_backup} días",
                          old_bk, sum(map(_size, old_bk)), backup=False,
                          note="Después ya no podrás restaurar esas migraciones."))
    shots = [f for d in ("compare", "shots") for f in (hd / "design" / d).glob("*") if f.is_file() and _older(f, days_shots)] \
        if (hd / "design").exists() else []
    if shots:
        items.append(Item("capturas", f"{len(shots)} captura(s)/comparación(es) de diseño con más de {days_shots} días",
                          shots, sum(map(_size, shots)), backup=False))
    legacy = sorted((root / ".kiro" / "hooks").glob("*.kiro.hook")) if (root / ".kiro" / "hooks").exists() else []
    if legacy:
        items.append(Item("kiro-legacy", f"{len(legacy)} hook(s) de Kiro 0.x (.kiro.hook) que Kiro 1.x ya no ejecuta",
                          legacy, sum(map(_size, legacy)),
                          note="Si aún los necesitas, primero migra cada uno desde el panel Agent Hooks de Kiro."))
    empty = []
    for rel in OTHER_TOOL_DIRS:
        d = root / rel
        if d.is_dir() and not any(f.is_file() for f in d.rglob("*")):
            if not any(str(d).startswith(str(e) + "/") for e in empty):
                empty.append(d)
    if empty:
        items.append(Item("carpetas-vacias", "Carpetas vacías de otras herramientas de IA: "
                          + ", ".join(p.relative_to(root).as_posix() for p in empty), empty, 0, backup=False))
    cfg_p = hd / "config.json"
    manifest = set(json.loads(cfg_p.read_text() or "{}").get("generated", [])) if cfg_p.exists() else set()
    from .installer import GEN_MARK
    orphans = []
    for base in (".claude/agents", ".claude/commands", ".kiro/agents", ".kiro/steering"):
        for f in (root / base).glob("*.md") if (root / base).exists() else []:
            rel = f.relative_to(root).as_posix()
            if rel not in manifest and GEN_MARK in f.read_text(encoding="utf-8", errors="ignore"):
                orphans.append(f)
    for base in (".kiro/workflows",):
        for f in (root / base).glob("agentes-*.workflow.json") if (root / base).exists() else []:
            if f.relative_to(root).as_posix() not in manifest:
                orphans.append(f)
    if orphans:
        items.append(Item("huerfanos", f"{len(orphans)} archivo(s) generados por agentes que ya no se usan",
                          orphans, sum(map(_size, orphans))))
    try:
        from .embeddings import collection_name, resolve
        from .store import Store
        st = Store(root)
        current = collection_name(resolve(st._embedding_model_name())[1])
        if (hd / "vectors").exists():
            import chromadb  # type: ignore
            from chromadb.config import Settings  # type: ignore
            client = chromadb.PersistentClient(path=str(hd / "vectors"), settings=Settings(anonymized_telemetry=False))
            stale = [c.name if hasattr(c, "name") else str(c) for c in client.list_collections()]
            stale = [n for n in stale if n != current]
            if stale:
                items.append(Item("vectores", f"Colecciones de vectores de modelos que ya no usas: {', '.join(stale)}",
                                  [], 0, backup=False, action="collection", extra={"names": stale}))
    except Exception:
        pass
    return items


def apply(root: Path, item: Item, backup_dir: Path | None) -> int:
    root = Path(root).resolve()
    if item.action == "collection":
        import chromadb  # type: ignore
        from chromadb.config import Settings  # type: ignore
        client = chromadb.PersistentClient(path=str(root / HARNESS_DIR / "vectors"),
                                           settings=Settings(anonymized_telemetry=False))
        for n in item.extra.get("names", []):
            client.delete_collection(n)
        return len(item.extra.get("names", []))
    n = 0
    for p in item.paths:
        if not p.exists():
            continue
        if item.backup and backup_dir is not None:
            dst = backup_dir / p.relative_to(root)
            dst.parent.mkdir(parents=True, exist_ok=True)
            if p.is_dir():
                shutil.copytree(p, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(p, dst)
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        n += 1
    return n
