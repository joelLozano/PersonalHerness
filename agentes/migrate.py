"""Migración de archivos .md y configuraciones de agentes existentes a la memoria de `agentes`.

Detecta configuraciones de Claude Code, Kiro, Cursor, Windsurf, Cline, GitHub Copilot, Gemini,
AGENTS.md y bancos de memoria en .md. Por defecto es un simulacro (no cambia nada). Con --apply:
  1. respalda cada archivo en .agentes/backup/<fecha>/ (se puede restaurar),
  2. importa instrucciones y notas a la base de datos (troceadas por secciones y clasificadas),
  3. convierte agentes y comandos de otras herramientas en entradas de .agentes/team.local.yaml,
  4. sustituye los originales (los elimina; CLAUDE.md conserva solo el bloque gestionado),
  5. regenera el equipo para los IDEs del proyecto.
Nunca toca código fuente, README, docs del proyecto, specs de Kiro ni hooks/MCP del usuario.
"""
from __future__ import annotations

import fnmatch
import json
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from .installer import BLOCK_END, BLOCK_START, GEN_MARK, load_team, local_team_path, sync
from .kiro import kiro_tools_to_claude
from .store import HARNESS_DIR, Store

# patrón (relativo a la raíz) -> (herramienta, categoría)
#   instructions: se cargaban siempre (-> reglas/memoria)  memory: notas (-> memoria)
#   agent / command: -> team.local.yaml                       steering: depende de su `inclusion`
SOURCES: list[tuple[str, str, str]] = [
    ("CLAUDE.md", "Claude Code", "instructions"),
    ("CLAUDE.local.md", "Claude Code", "instructions"),
    (".claude/CLAUDE.md", "Claude Code", "instructions"),
    (".claude/agents/**/*.md", "Claude Code", "agent"),
    (".claude/commands/**/*.md", "Claude Code", "command"),
    ("AGENTS.md", "AGENTS.md", "instructions"),
    ("GEMINI.md", "Gemini CLI", "instructions"),
    (".cursorrules", "Cursor", "instructions"),
    (".cursor/rules/**/*.mdc", "Cursor", "instructions"),
    (".cursor/rules/**/*.md", "Cursor", "instructions"),
    (".windsurfrules", "Windsurf", "instructions"),
    (".windsurf/rules/**/*.md", "Windsurf", "instructions"),
    (".clinerules", "Cline", "instructions"),
    (".clinerules/**/*.md", "Cline", "instructions"),
    (".github/copilot-instructions.md", "GitHub Copilot", "instructions"),
    (".github/instructions/**/*.md", "GitHub Copilot", "instructions"),
    (".kiro/steering/**/*.md", "Kiro", "steering"),
    (".kiro/agents/**/*.md", "Kiro", "agent"),
    (".kiro/agents/**/*.json", "Kiro", "agent"),
    ("memory-bank/**/*.md", "Cline Memory Bank", "memory"),
    (".memory/**/*.md", "Notas de memoria", "memory"),
    (".ai/**/*.md", "Notas de IA", "memory"),
]
KEEP_NOTES = [
    (".kiro/specs", "Specs de Kiro: se conservan y se indexan en la memoria (`agentes index`)"),
    (".kiro/hooks", "Hooks de Kiro del usuario: se conservan"),
    (".claude/settings.json", "Hooks/permisos de Claude Code del usuario: se conservan (solo se agregan los de agentes)"),
    (".mcp.json", "Servidores MCP del usuario: se conservan"),
    (".kiro/settings/mcp.json", "Servidores MCP de Kiro del usuario: se conservan"),
]

KIND_RULES = [
    ("security", r"segur|security|secret|credencial|credential|owasp|vulnerab|\bauth|token|cifrad|encrypt|permis"),
    ("design", r"color|colou?r|tipograf|typograph|font|diseñ|design system|\bui\b|\bux\b|theme|tema visual|figma|tailwind|css|espaciad|spacing"),
    ("decision", r"decisi|decid|\badr\b|elegimos|we chose|we decided|rationale|trade-?off|arquitectura|architecture"),
    ("requirement", r"requisit|requirement|user stor|historia de usuario|acceptance|criterio de aceptaci|feature|funcionalidad"),
    ("convention", r"convenci|convention|estilo|style|naming|nombr|lint|format|estructura|structure|commit|test|prueba|siempre|nunca|always|never|must|debe|should"),
]


@dataclass
class Item:
    path: str
    tool: str
    category: str
    action: str = ""
    sections: int = 0
    size: int = 0
    meta: dict = field(default_factory=dict)


# ------------------------------------------------------------------------------ parsing
def split_front(text: str) -> tuple[dict, str]:
    if text.startswith("---"):
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
        if m:
            try:
                meta = yaml.safe_load(m.group(1)) or {}
                if isinstance(meta, dict):
                    return meta, m.group(2)
            except yaml.YAMLError:
                pass
    return {}, text


def strip_managed(text: str) -> str:
    """Quita nuestro bloque gestionado y marcas de generación."""
    if BLOCK_START in text and BLOCK_END in text:
        pre, rest = text.split(BLOCK_START, 1)
        _, post = rest.split(BLOCK_END, 1)
        text = pre + post
    return text.replace(GEN_MARK, "").strip()


def sections(body: str, title: str, max_len: int = 1400) -> list[str]:
    out: list[str] = []
    heads: list[str] = []
    buf: list[str] = []

    def flush():
        content = "\n".join(buf).strip()
        buf.clear()
        if len(content) < 15:
            return
        head = " > ".join(h for h in heads if h) or title
        if len(content) <= max_len:
            out.append(f"{head}: {content}")
            return
        chunk = ""
        for para in re.split(r"\n\s*\n", content):
            if chunk and len(chunk) + len(para) > max_len:
                out.append(f"{head}: {chunk.strip()}")
                chunk = ""
            chunk += para + "\n\n"
        if chunk.strip():
            out.append(f"{head}: {chunk.strip()}")

    in_code = False
    for line in body.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
        m = None if in_code else re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            flush()
            level = len(m.group(1))
            heads[:] = heads[: level - 1] + [""] * max(0, level - 1 - len(heads))
            heads[level - 1: level] = [m.group(2).strip()]
            del heads[level:]
        else:
            buf.append(line)
    flush()
    return out


def classify(text: str, default: str = "note") -> str:
    low = text.lower()
    for kind, pat in KIND_RULES:
        if re.search(pat, low):
            return kind
    return default


# ------------------------------------------------------------------------------ detección
def _glob(root: Path, pattern: str) -> list[Path]:
    if "*" not in pattern:
        p = root / pattern
        return [p] if p.is_file() else []
    base = pattern.split("*")[0].rstrip("/")
    start = root / base
    if not start.exists():
        return []
    return sorted(p for p in start.rglob("*") if p.is_file()
                  and fnmatch.fnmatch(p.relative_to(root).as_posix(), pattern.replace("**/", "*")))


def detect(root: Path, include: list[str] | None = None) -> list[Item]:
    root = root.resolve()
    team = load_team(root)
    ours_agents, ours_cmds = set(team.get("agents", {})), set(team.get("commands", {}))
    seen: set[str] = set()
    items: list[Item] = []
    sources = list(SOURCES) + [(g, "Incluido por ti", "memory") for g in (include or [])]
    for pattern, tool, cat in sources:
        for p in _glob(root, pattern):
            rel = p.relative_to(root).as_posix()
            if rel in seen or rel.startswith(HARNESS_DIR + "/"):
                continue
            seen.add(rel)
            try:
                raw = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if GEN_MARK in raw:  # generado por nosotros
                continue
            text = strip_managed(raw)
            if not text:
                continue
            it = Item(rel, tool, cat, size=len(text))
            if cat == "steering":
                meta, body = split_front(text)
                inc = str(meta.get("inclusion", "always"))
                it.meta["inclusion"] = inc
                if inc == "manual":
                    it.category = "command"
                elif inc in ("fileMatch", "auto"):
                    it.category = "memory"
                    it.meta["pattern"] = meta.get("fileMatchPattern") or meta.get("description", "")
                else:
                    it.category = "instructions"
            if it.category == "agent":
                name = p.stem
                it.action = (f"fusionar con el agente '{name}' del equipo (extra_prompt)" if name in ours_agents
                             else f"agregar como agente '{name}' del equipo")
            elif it.category == "command":
                name = _cmd_name(rel)
                it.action = (f"agregar como comando /{name}-migrado (ya existe /{name})" if name in ours_cmds
                             else f"agregar como comando /{name}")
            else:
                _, body = split_front(text)
                it.sections = len(sections(body, Path(rel).stem))
                kind = "reglas" if it.category == "instructions" else "memorias"
                it.action = f"importar {it.sections} secciones como {kind}"
            items.append(it)
    return items


def _cmd_name(rel: str) -> str:
    rel = re.sub(r"^\.(claude/commands|kiro/steering)/", "", rel)
    return re.sub(r"\.(md|mdc)$", "", rel).replace("/", "-")


def keep_notes(root: Path) -> list[str]:
    out = []
    for rel, note in KEEP_NOTES:
        p = root / rel
        if p.exists():
            if rel.endswith(".json"):
                try:
                    data = json.loads(p.read_text() or "{}")
                    servers = [s for s in data.get("mcpServers", {}) if s != "agentes"]
                    hooks = [h for groups in (data.get("hooks") or {}).values() for g in groups
                             for h in g.get("hooks", []) if " hook session-start" not in h.get("command", "")
                             and " hook prompt" not in h.get("command", "")]
                except Exception:
                    servers, hooks = [], None
                if not servers and not hooks:
                    continue
            out.append(f"{rel}: {note}")
    return out


# ------------------------------------------------------------------------------ aplicación
def _load_local(root: Path) -> dict:
    p = local_team_path(root)
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


def _save_local(root: Path, data: dict) -> None:
    p = local_team_path(root)
    p.parent.mkdir(exist_ok=True)
    p.write_text("# Personalización del equipo para este proyecto. Aplica con: agentes sync\n"
                 + yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=110), encoding="utf-8")


def _agent_entry(p: Path, root: Path, text: str) -> tuple[str, dict]:
    if p.suffix == ".json":
        meta = json.loads(text)
        prompt = meta.get("prompt", "")
        if isinstance(prompt, str) and prompt.startswith("file://"):
            ref = prompt[len("file://"):]
            for base in (p.parent, root):
                if (base / ref).exists():
                    prompt = (base / ref).read_text(encoding="utf-8", errors="ignore")
                    break
        body = prompt
    else:
        meta, body = split_front(text)
    name = str(meta.get("name") or p.stem)
    entry: dict = {"description": str(meta.get("description") or f"Agente migrado de {p.name}").strip(),
                   "prompt": body.strip(), "migrated_from": p.relative_to(root).as_posix()}
    tools = meta.get("tools")
    if p.relative_to(root).as_posix().startswith(".kiro/"):
        if tools:
            entry["kiro_tools"] = tools if isinstance(tools, list) else [tools]
        conv = kiro_tools_to_claude(tools if isinstance(tools, list) else ([tools] if tools else None))
        entry["tools"] = conv if conv else "full"
        if meta.get("model"):
            entry["kiro_model"] = meta["model"]
    else:
        if isinstance(tools, str):
            tools = [t.strip() for t in tools.split(",") if t.strip()]
        entry["tools"] = tools or "full"
        if str(meta.get("model", "")) in ("opus", "sonnet", "haiku", "inherit"):
            entry["model"] = meta["model"]
        else:
            entry["model"] = "sonnet"
    return name, entry


def apply(root: Path, items: list[Item], keep: bool = False, log=print) -> dict:
    root = root.resolve()
    ts = time.strftime("%Y%m%d-%H%M%S")
    bdir = root / HARNESS_DIR / "backup" / ts
    (bdir / "files").mkdir(parents=True, exist_ok=True)
    tag = f"migrado:{ts}"
    lp = local_team_path(root)
    if lp.exists():
        shutil.copy2(lp, bdir / "team.local.yaml.orig")

    store = Store(root)
    team = load_team(root)
    local = _load_local(root)
    stats = {"reglas": 0, "memorias": 0, "agentes": 0, "comandos": 0, "sustituidos": 0}
    manifest = {"ts": ts, "tag": tag, "items": [], "keep": keep}

    for it in items:
        src = root / it.path
        dst = bdir / "files" / it.path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        raw = src.read_text(encoding="utf-8", errors="ignore")
        text = strip_managed(raw)

        if it.category == "agent":
            name, entry = _agent_entry(src, root, text)
            agents = local.setdefault("agents", {})
            if name in team.get("agents", {}) and not team["agents"][name].get("migrated_from"):
                cur = agents.setdefault(name, {})
                cur["extra_prompt"] = ((cur.get("extra_prompt") or "") + f"\n\n# Migrado de {it.path}\n"
                                       + entry["prompt"]).strip()
            else:
                agents[name] = entry
            stats["agentes"] += 1
        elif it.category == "command":
            meta, body = split_front(text)
            name = _cmd_name(it.path)
            if name in team.get("commands", {}) and not team["commands"][name].get("migrated_from"):
                name = f"{name}-migrado"
            local.setdefault("commands", {})[name] = {
                "description": str(meta.get("description") or f"Comando migrado de {it.path}"),
                "argument-hint": meta.get("argument-hint"), "body": body.strip(), "migrated_from": it.path}
            if not local["commands"][name]["argument-hint"]:
                local["commands"][name].pop("argument-hint")
            stats["comandos"] += 1
        else:
            meta, body = split_front(text)
            extra_tag = f",patron:{it.meta['pattern']}" if it.meta.get("pattern") else ""
            for sec in sections(body, Path(it.path).stem):
                kind = classify(sec)
                if it.category == "instructions" and kind in ("convention", "note"):
                    kind = "rule"
                store.add(sec, kind=kind, tags=f"{tag},{it.tool}{extra_tag}", source=it.path, agent="migracion")
                stats["reglas" if kind == "rule" else "memorias"] += 1

        removed = False
        if not keep:
            if it.path in ("CLAUDE.md",) and BLOCK_START in raw:
                pre, rest = raw.split(BLOCK_START, 1)
                _, post = rest.split(BLOCK_END, 1)
                src.write_text(raw[len(pre):len(raw) - len(post)].strip() + "\n", encoding="utf-8")
            else:
                src.unlink()
                _prune_empty(src.parent, root)
            removed = True
            stats["sustituidos"] += 1
        manifest["items"].append({**asdict(it), "removed": removed})
        log(f"  ✔ {it.path} → {it.action}{'' if keep else ' (original sustituido)'}")

    _save_local(root, local)
    (bdir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    res = sync(root, quiet=True)
    stats.update({"backup": str(bdir.relative_to(root)), "ides": res["ides"]})
    return stats


def _prune_empty(d: Path, root: Path) -> None:
    keep = {root, root / ".claude", root / ".kiro", root / ".github"}
    while d not in keep and d.is_dir() and root in d.parents and not any(d.iterdir()):
        d.rmdir()
        d = d.parent


def backups(root: Path) -> list[str]:
    b = root / HARNESS_DIR / "backup"
    return sorted((p.name for p in b.iterdir() if (p / "manifest.json").exists()), reverse=True) if b.exists() else []


def restore(root: Path, ts: str | None = None, log=print) -> dict:
    root = root.resolve()
    avail = backups(root)
    if not avail:
        raise SystemExit("No hay respaldos de migración.")
    ts = ts or avail[0]
    bdir = root / HARNESS_DIR / "backup" / ts
    manifest = json.loads((bdir / "manifest.json").read_text())
    # los archivos restaurados vuelven a ser del usuario: sácalos del registro de generados
    cfg_p = root / HARNESS_DIR / "config.json"
    if cfg_p.exists():
        cfg = json.loads(cfg_p.read_text() or "{}")
        paths = {it["path"] for it in manifest["items"]}
        cfg["generated"] = [g for g in cfg.get("generated", []) if g not in paths]
        cfg_p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
    for it in manifest["items"]:
        src = bdir / "files" / it["path"]
        dst = root / it["path"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)  # CLAUDE.md: sync vuelve a insertar el bloque gestionado
        log(f"  ↺ {it['path']}")
    orig = bdir / "team.local.yaml.orig"
    lp = local_team_path(root)
    if orig.exists():
        shutil.copy2(orig, lp)
    elif lp.exists():
        lp.unlink()
    store = Store(root)
    ids = [r[0] for r in store.db.execute("SELECT id FROM memories WHERE tags LIKE ?", (f"%{manifest['tag']}%",))]
    store.delete(ids)
    sync(root, quiet=True)
    return {"restaurados": len(manifest["items"]), "memorias_eliminadas": len(ids), "respaldo": ts}


def git_dirty(root: Path, paths: list[str]) -> list[str]:
    try:
        out = subprocess.run(["git", "status", "--porcelain", "--", *paths], cwd=root,
                             capture_output=True, text=True, timeout=10).stdout
        return [l[3:] for l in out.splitlines() if l.strip()]
    except Exception:
        return []
