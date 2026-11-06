"""Log rotativo del harness en .agentes/agentes.log (hooks, servidor MCP, rechazos de seguridad).

Los hooks y el servidor MCP nunca deben interrumpir al IDE; sus errores se registran aquí para poder
diagnosticarlos con `agentes doctor` o `tail .agentes/agentes.log`.
"""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_loggers: dict[str, logging.Logger] = {}


def _root() -> Path:
    from .store import HARNESS_DIR, find_root
    return find_root() / HARNESS_DIR


def get_logger(root: Path | None = None) -> logging.Logger:
    d = (Path(root) / ".agentes") if root else _root()
    key = str(d)
    if key in _loggers:
        return _loggers[key]
    lg = logging.getLogger(f"agentes.{len(_loggers)}")
    lg.setLevel(logging.INFO)
    lg.propagate = False
    try:
        d.mkdir(parents=True, exist_ok=True)
        h = RotatingFileHandler(d / "agentes.log", maxBytes=512_000, backupCount=2, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(process)d %(message)s"))
        lg.addHandler(h)
    except OSError:
        lg.addHandler(logging.NullHandler())
    _loggers[key] = lg
    return lg


def log(component: str, msg: str, root: Path | None = None, level: int = logging.INFO) -> None:
    if os.environ.get("AGENTES_NO_LOG") == "1":
        return
    try:
        get_logger(root).log(level, f"[{component}] {msg}")
    except Exception:
        pass


def tail(root: Path, n: int = 20) -> list[str]:
    p = Path(root) / ".agentes" / "agentes.log"
    try:
        return p.read_text(encoding="utf-8", errors="ignore").splitlines()[-n:]
    except OSError:
        return []
