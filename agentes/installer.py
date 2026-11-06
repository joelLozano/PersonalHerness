"""Genera e instala el harness en un proyecto a partir de team.yaml (+ team.local.yaml)."""
from __future__ import annotations

import copy
import json
import shutil
import sys
import time
from pathlib import Path

import yaml

from . import __version__
from .store import HARNESS_DIR, Store

PKG_DIR = Path(__file__).parent
BASE_TEAM = PKG_DIR / "team.yaml"
LOCAL_TEAM = "team.local.yaml"
GEN_MARK = "<!-- Generado por `agentes sync`. No edites aquí: usa .agentes/team.local.yaml o `agentes agent ...` -->"
BLOCK_START, BLOCK_END = "<!-- agentes:start -->", "<!-- agentes:end -->"
GITIGNORE_LINES = [".agentes/agentes.db", ".agentes/vectors/", ".agentes/scan.json", ".agentes/*.log"]


def cli_cmd() -> str:
    """Comando para invocar el CLI desde hooks/MCP."""
    if shutil.which("agentes"):
        return "agentes"
    return f"{sys.executable} -m agentes"


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def local_team_path(root: Path) -> Path:
    return root / HARNESS_DIR / LOCAL_TEAM


def load_team(root: Path | None = None) -> dict:
    team = yaml.safe_load(BASE_TEAM.read_text(encoding="utf-8"))
    if root is not None and local_team_path(root).exists():
        local = yaml.safe_load(local_team_path(root).read_text(encoding="utf-8")) or {}
        team = deep_merge(team, local)
    return team


def render_questions(sections: list[dict]) -> str:
    out = []
    for s in sections:
        out.append(f"### {s.get('title', s['section'])}  (section: `{s['section']}`)")
        for q in s.get("items", []):
            opts = f"  — opciones: {', '.join(map(str, q['opts']))}" if q.get("opts") else ""
            out.append(f"- `{q['id']}`: {q['q']}{opts}")
        out.append("")
    return "\n".join(out).strip()


def _frontmatter(d: dict) -> str:
    lines = ["---"]
    for k, v in d.items():
        if v is None or v == "":
            continue
        if isinstance(v, list):
            v = ", ".join(v)
        v = str(v).replace("\n", " ").strip()
        if any(c in v for c in ":#'\"[]{}") or v != v.strip():
            v = json.dumps(v, ensure_ascii=False)
        lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines)


def render_agent(name: str, a: dict, team: dict) -> str:
    tools = a.get("tools")
    if isinstance(tools, str):
        tools = team.get("toolsets", {}).get(tools, None) if tools in team.get("toolsets", {}) else [t.strip() for t in tools.split(",")]
    fm = _frontmatter({"name": name, "description": a.get("description", ""), "tools": tools,
                       "model": a.get("model", "inherit"), "color": a.get("color")})
    body = [GEN_MARK, "", a.get("prompt", "").strip()]
    if a.get("extra_prompt"):
        body += ["", "## Instrucciones específicas de este proyecto", a["extra_prompt"].strip()]
    body += ["", team.get("shared_protocol", "").strip()]
    return fm + "\n\n" + "\n".join(body).strip() + "\n"


def render_command(name: str, c: dict, team: dict) -> str:
    fm = _frontmatter({"description": c.get("description", ""), "argument-hint": c.get("argument-hint"),
                       "allowed-tools": c.get("allowed-tools"), "model": c.get("model")})
    body = c.get("body", "")
    q = team.get("questions", {})
    body = body.replace("{{questions_new}}", render_questions(q.get("new", [])))
    body = body.replace("{{questions_existing}}", render_questions(q.get("existing", [])))
    return fm + "\n" + GEN_MARK + "\n\n" + body.strip() + "\n"


def _load_json(p: Path) -> dict:
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError:
            backup = p.with_suffix(p.suffix + f".bak{int(time.time())}")
            shutil.copy(p, backup)
            print(f"  ! {p.name} no era JSON válido; respaldo en {backup.name}")
    return {}


def _merge_hooks(settings: dict, cmd: str) -> dict:
    hooks = settings.setdefault("hooks", {})
    ours = {"SessionStart": f"{cmd} hook session-start", "UserPromptSubmit": f"{cmd} hook prompt"}
    for event, command in ours.items():
        groups = hooks.setdefault(event, [])
        # quita versiones previas nuestras
        for g in groups:
            g["hooks"] = [h for h in g.get("hooks", []) if "hook session-start" not in h.get("command", "")
                          and "hook prompt" not in h.get("command", "")]
        groups[:] = [g for g in groups if g.get("hooks")]
        groups.append({"hooks": [{"type": "command", "command": command, "timeout": 20}]})
    perms = settings.setdefault("permissions", {}).setdefault("allow", [])
    for p in ("mcp__agentes", "Bash(agentes:*)"):
        if p not in perms:
            perms.append(p)
    return settings


def _remove_hooks(settings: dict) -> dict:
    for event in list(settings.get("hooks", {})):
        groups = settings["hooks"][event]
        for g in groups:
            g["hooks"] = [h for h in g.get("hooks", []) if " hook session-start" not in h.get("command", "")
                          and " hook prompt" not in h.get("command", "")]
        settings["hooks"][event] = [g for g in groups if g.get("hooks")]
        if not settings["hooks"][event]:
            del settings["hooks"][event]
    if not settings.get("hooks"):
        settings.pop("hooks", None)
    perms = settings.get("permissions", {}).get("allow", [])
    for p in ("mcp__agentes", "Bash(agentes:*)"):
        if p in perms:
            perms.remove(p)
    return settings


def _update_block(path: Path, content: str | None) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if BLOCK_START in text and BLOCK_END in text:
        pre, rest = text.split(BLOCK_START, 1)
        _, post = rest.split(BLOCK_END, 1)
        text = pre.rstrip() + ("\n\n" if pre.strip() else "") + (
            f"{BLOCK_START}\n{content.strip()}\n{BLOCK_END}" if content else "") + post
    elif content:
        text = (text.rstrip() + "\n\n" if text.strip() else "") + f"{BLOCK_START}\n{content.strip()}\n{BLOCK_END}\n"
    if text.strip():
        path.write_text(text.strip() + "\n", encoding="utf-8")
    elif path.exists():
        path.write_text("", encoding="utf-8")


def sync(root: Path, quiet: bool = False) -> dict:
    """(Re)genera agentes, comandos, hooks, MCP y bloque de CLAUDE.md. Idempotente."""
    root = root.resolve()
    team = load_team(root)
    hd = root / HARNESS_DIR
    hd.mkdir(exist_ok=True)
    cfg_path = hd / "config.json"
    cfg = _load_json(cfg_path)
    old_manifest = set(cfg.get("generated", []))
    new_manifest: list[str] = []

    def write(rel: str, content: str):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists() and rel not in old_manifest and GEN_MARK not in p.read_text(encoding="utf-8", errors="ignore"):
            if not quiet:
                print(f"  ! {rel} ya existe y no es nuestro: lo omito (renómbralo o usa otro nombre en team.local.yaml)")
            return
        p.write_text(content, encoding="utf-8")
        new_manifest.append(rel)

    for name, a in team.get("agents", {}).items():
        if a and not a.get("disabled"):
            write(f".claude/agents/{name}.md", render_agent(name, a, team))
    for name, c in team.get("commands", {}).items():
        if c and not c.get("disabled"):
            write(f".claude/commands/{name}.md", render_command(name, c, team))

    for rel in old_manifest - set(new_manifest):  # elimina generados obsoletos
        p = root / rel
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass

    cmd = cli_cmd()
    settings_p = root / ".claude" / "settings.json"
    settings_p.parent.mkdir(exist_ok=True)
    settings_p.write_text(json.dumps(_merge_hooks(_load_json(settings_p), cmd), indent=2, ensure_ascii=False) + "\n")

    mcp_p = root / ".mcp.json"
    mcp = _load_json(mcp_p)
    parts = cmd.split()
    mcp.setdefault("mcpServers", {})["agentes"] = {"type": "stdio", "command": parts[0], "args": parts[1:] + ["mcp"]}
    mcp_p.write_text(json.dumps(mcp, indent=2, ensure_ascii=False) + "\n")

    _update_block(root / "CLAUDE.md", team.get("orchestrator", ""))

    gi = root / ".gitignore"
    lines = gi.read_text().splitlines() if gi.exists() else []
    missing = [l for l in GITIGNORE_LINES if l not in lines]
    if missing:
        gi.write_text("\n".join(lines + (["", "# agentes harness (memoria local)"] if lines else []) + missing) + "\n")

    if not local_team_path(root).exists():
        local_team_path(root).write_text(LOCAL_TEMPLATE, encoding="utf-8")

    cfg.update({"version": __version__, "synced_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "generated": sorted(new_manifest), "cli": cmd})
    cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
    Store(root)  # crea la BD
    return {"agents": sum(1 for r in new_manifest if "/agents/" in r),
            "commands": sum(1 for r in new_manifest if "/commands/" in r)}


def uninstall(root: Path, purge: bool = False) -> list[str]:
    root = root.resolve()
    cfg = _load_json(root / HARNESS_DIR / "config.json")
    removed = []
    for rel in cfg.get("generated", []):
        p = root / rel
        if p.exists():
            p.unlink()
            removed.append(rel)
    sp = root / ".claude" / "settings.json"
    if sp.exists():
        sp.write_text(json.dumps(_remove_hooks(_load_json(sp)), indent=2, ensure_ascii=False) + "\n")
    mp = root / ".mcp.json"
    if mp.exists():
        m = _load_json(mp)
        m.get("mcpServers", {}).pop("agentes", None)
        mp.write_text(json.dumps(m, indent=2) + "\n")
    _update_block(root / "CLAUDE.md", None)
    if purge:
        shutil.rmtree(root / HARNESS_DIR, ignore_errors=True)
        removed.append(HARNESS_DIR + "/")
    return removed


LOCAL_TEMPLATE = """# Personalización del equipo para ESTE proyecto (se fusiona sobre el team.yaml base).
# Tras editar, ejecuta:  agentes sync
#
# Ejemplos:
# agents:
#   frontend-dev:
#     model: opus
#     extra_prompt: |
#       Usa siempre Server Components salvo que haya interactividad.
#   devops-engineer:
#     disabled: true
#   data-engineer:                      # agente nuevo
#     description: Experto en pipelines de datos y SQL analítico.
#     model: sonnet
#     tools: full
#     prompt: |
#       Eres un ingeniero de datos...
# commands:
#   release:
#     description: Prepara un release
#     body: |
#       Genera changelog desde git log y propone versión semver. $ARGUMENTS
# settings:
#   auto_recall: false
"""
