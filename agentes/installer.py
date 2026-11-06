"""Genera e instala el harness en un proyecto a partir de team.yaml (+ team.local.yaml)."""
from __future__ import annotations

import copy
import json
import os
import re
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
GITIGNORE_LINES = [".agentes/agentes.db*", ".agentes/vectors/", ".agentes/scan.json", ".agentes/*.log",
                   ".agentes/recall-state.json", ".agentes/backup/", ".agentes/vectors-error.json",
                   ".agentes/design/compare/", ".agentes/design/shots/", ".agentes/design/figma/", ".agentes/index.stamp",
                   ".agentes/agentes.log*", ".agentes/vectors.lock", ".agentes/ds/"]


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


PROFILES_DIR = PKG_DIR / "profiles"


def available_profiles() -> list[str]:
    return sorted(p.stem for p in PROFILES_DIR.glob("*.yaml")) if PROFILES_DIR.exists() else []


def get_profiles(root: Path | None) -> list[str]:
    if root is None:
        return []
    cfg = _load_json(Path(root) / HARNESS_DIR / "config.json")
    return [p for p in cfg.get("profiles", []) if p in available_profiles()]


def set_profiles(root: Path, profiles: list[str]) -> None:
    p = root / HARNESS_DIR / "config.json"
    p.parent.mkdir(exist_ok=True)
    cfg = _load_json(p)
    cfg["profiles"] = [x for x in profiles if x in available_profiles()]
    p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")


def detect_profiles(root: Path) -> list[str]:
    """Sugiere perfiles según el proyecto (p. ej. mobile si hay Xcode/SPM/Gradle de Android y no hay web)."""
    root = Path(root)
    mobile = any(root.glob("*.xcodeproj")) or any(root.glob("*.xcworkspace")) or any(root.glob("*/*.xcodeproj")) \
        or (root / "Podfile").exists() or any((root / n).exists() for n in ("settings.gradle", "settings.gradle.kts")) \
        or any(root.glob("*/src/main/AndroidManifest.xml")) if root.exists() else False
    if (root / "Package.swift").exists() and "iOS" in (root / "Package.swift").read_text(errors="ignore"):
        mobile = True
    web = (root / "package.json").exists() and re.search(r'"(next|react-dom|vue|nuxt|svelte|@angular/core)"',
                                                          (root / "package.json").read_text(errors="ignore"))
    return ["mobile"] if mobile and not web else []


def _append_extras(team: dict) -> dict:
    """Las claves `<clave>_extra` de los perfiles se agregan al final del texto base (no lo reemplazan)."""
    for key in ("orchestrator", "shared_protocol"):
        if team.get(f"{key}_extra"):
            team[key] = (team.get(key, "").rstrip() + "\n" + team.pop(f"{key}_extra").rstrip() + "\n")
    k = team.get("kiro", {})
    if k.get("orchestrator_extra"):
        k["orchestrator"] = k.get("orchestrator", "").rstrip() + "\n" + k.pop("orchestrator_extra").rstrip() + "\n"
    return team


def load_team(root: Path | None = None, profiles: list[str] | None = None, use_local: bool | None = None) -> dict:
    team = yaml.safe_load(BASE_TEAM.read_text(encoding="utf-8"))
    extras: dict[str, list[str]] = {}
    for prof in (profiles if profiles is not None else get_profiles(root)):
        pdata = yaml.safe_load((PROFILES_DIR / f"{prof}.yaml").read_text(encoding="utf-8")) or {}
        for key in ("orchestrator_extra", "shared_protocol_extra"):
            if pdata.get(key):
                extras.setdefault(key, []).append(pdata.pop(key))
        if pdata.get("kiro", {}).get("orchestrator_extra"):
            extras.setdefault("kiro_orchestrator_extra", []).append(pdata["kiro"].pop("orchestrator_extra"))
        team = deep_merge(team, pdata)
    if use_local is None:  # personalizaciones del repo: solo si el usuario las aprobó (o las escribió el harness)
        from .security import is_trusted
        use_local = root is not None and (os.environ.get("AGENTES_TRUST_ALL") == "1" or is_trusted(Path(root)))
    if use_local and root is not None and local_team_path(root).exists():
        local = yaml.safe_load(local_team_path(root).read_text(encoding="utf-8")) or {}
        team = deep_merge(team, local)
    for key in ("orchestrator_extra", "shared_protocol_extra"):
        if extras.get(key):
            team[key] = "\n".join(extras[key]) + ("\n" + team[key] if team.get(key) else "")
    if extras.get("kiro_orchestrator_extra"):
        team.setdefault("kiro", {})["orchestrator_extra"] = "\n".join(extras["kiro_orchestrator_extra"])
    return _append_extras(team)


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


def render_body(c: dict, team: dict) -> str:
    body = c.get("body", "")
    q = team.get("questions", {})
    body = body.replace("{{questions_new}}", render_questions(q.get("new", [])))
    return body.replace("{{questions_existing}}", render_questions(q.get("existing", [])))


def render_command(name: str, c: dict, team: dict) -> str:
    fm = _frontmatter({"description": c.get("description", ""), "argument-hint": c.get("argument-hint"),
                       "allowed-tools": c.get("allowed-tools"), "model": c.get("model")})
    return fm + "\n" + GEN_MARK + "\n\n" + render_body(c, team).strip() + "\n"


def _load_json(p: Path) -> dict:
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError:
            backup = p.with_suffix(p.suffix + f".bak{int(time.time())}")
            shutil.copy(p, backup)
            print(f"  ! {p.name} no era JSON válido; respaldo en {backup.name}")
    return {}


# Subcomandos que los agentes pueden ejecutar sin pedir permiso (solo lectura o efectos acotados al proyecto).
# Quedan FUERA a propósito: install, sync, uninstall, migrate, memory delete/import/rebuild, design figma --save-token,
# agent/command/team/perfil/ide (cambian el equipo), trust y upgrade.
SAFE_ALLOW = ["mcp__agentes"] + [f"Bash(agentes {c}:*)" for c in (
    "context", "scan", "index", "triage", "doctor", "audit", "bench", "questions",
    "ds show", "ds lookup", "ds check", "ds map", "ds index",
    "design list", "design ref", "design compare", "design shot",
    "requisitos --check", "memory search", "memory list", "memory stats", "task list", "task show",
)]
# Archivos con secretos que Claude Code no debe leer (en Kiro lo cubre .kiroignore).
DENY_READ = [f"Read({p})" for p in (
    "./.env", "./.env.local", "./.env.development", "./.env.production", "./.env.staging", "./.env.test",
    "./**/*.pem", "./**/*.key", "./**/*.p8", "./**/*.p12", "./**/*.pfx", "./**/*.jks", "./**/*.keystore",
    "./**/*.mobileprovision", "./**/local.properties", "./**/keystore.properties", "./**/*.tfvars",
    "./**/credentials.json", "./**/service-account*.json", "~/.ssh/**", "~/.aws/**",
    "~/.config/agentes/**",
)]


def _is_ours(command: str) -> bool:
    return bool(re.search(r"(agentes|-m agentes) hook (session-start|prompt|stop)\b", command))


def _merge_hooks(settings: dict, cmd: str) -> dict:
    hooks = settings.setdefault("hooks", {})
    ours = {"SessionStart": f"{cmd} hook session-start", "UserPromptSubmit": f"{cmd} hook prompt",
            "Stop": f"{cmd} hook stop"}
    for event, command in ours.items():
        groups = hooks.setdefault(event, [])
        # quita versiones previas nuestras
        for g in groups:
            g["hooks"] = [h for h in g.get("hooks", []) if not _is_ours(h.get("command", ""))]
        groups[:] = [g for g in groups if g.get("hooks")]
        groups.append({"hooks": [{"type": "command", "command": command, "timeout": 20}]})
    perm = settings.setdefault("permissions", {})
    allow = perm.setdefault("allow", [])
    if "Bash(agentes:*)" in allow:  # versiones anteriores aprobaban TODOS los subcomandos (incl. destructivos)
        allow.remove("Bash(agentes:*)")
    for p in SAFE_ALLOW:
        if p not in allow:
            allow.append(p)
    deny = perm.setdefault("deny", [])
    for p in DENY_READ:
        if p not in deny:
            deny.append(p)
    return settings


def _remove_hooks(settings: dict) -> dict:
    for event in list(settings.get("hooks", {})):
        groups = settings["hooks"][event]
        for g in groups:
            g["hooks"] = [h for h in g.get("hooks", []) if not _is_ours(h.get("command", ""))]
        settings["hooks"][event] = [g for g in groups if g.get("hooks")]
        if not settings["hooks"][event]:
            del settings["hooks"][event]
    if not settings.get("hooks"):
        settings.pop("hooks", None)
    perm = settings.get("permissions", {})
    for key, ours in (("allow", SAFE_ALLOW + ["Bash(agentes:*)"]), ("deny", DENY_READ)):
        lst = perm.get(key, [])
        for p in ours:
            if p in lst:
                lst.remove(p)
        if key in perm and not lst:
            perm.pop(key)
    if "permissions" in settings and not settings["permissions"]:
        settings.pop("permissions")
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


IDES = ("claude", "kiro")


def detect_ides(root: Path) -> list[str]:
    """IDEs a generar si el proyecto no tiene preferencia guardada."""
    found = []
    if (root / ".claude").exists() or (root / "CLAUDE.md").exists() or shutil.which("claude"):
        found.append("claude")
    if (root / ".kiro").exists() or shutil.which("kiro") or shutil.which("kiro-cli"):
        found.append("kiro")
    return found or ["claude"]


def get_ides(root: Path) -> list[str]:
    cfg = _load_json(root / HARNESS_DIR / "config.json")
    return cfg.get("ides") or detect_ides(root)


def set_ides(root: Path, ides: list[str]) -> None:
    p = root / HARNESS_DIR / "config.json"
    p.parent.mkdir(exist_ok=True)
    cfg = _load_json(p)
    cfg["ides"] = [i for i in IDES if i in ides]
    p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")


def sync(root: Path, quiet: bool = False, ides: list[str] | None = None) -> dict:
    """(Re)genera agentes, comandos, hooks, MCP e instrucciones para cada IDE. Idempotente."""
    from . import kiro as kiro_gen
    from .security import ensure_trusted, mark_trusted

    root = root.resolve()
    if not local_team_path(root).exists():
        (root / HARNESS_DIR).mkdir(exist_ok=True)
        local_team_path(root).write_text(LOCAL_TEMPLATE, encoding="utf-8")
        mark_trusted(root)
    trusted = os.environ.get("AGENTES_TRUST_ALL") == "1" or ensure_trusted(root, interactive=None if not quiet else False)
    team = load_team(root, use_local=trusted)
    hd = root / HARNESS_DIR
    hd.mkdir(exist_ok=True)
    cfg_path = hd / "config.json"
    cfg = _load_json(cfg_path)
    ides = [i for i in IDES if i in (ides or cfg.get("ides") or detect_ides(root))]
    old_manifest = set(cfg.get("generated", []))
    new_manifest: list[str] = []

    def warn(msg: str):
        if not quiet:
            print(f"  ! {msg}")

    def write(rel: str, content: str):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists() and rel not in old_manifest and GEN_MARK not in p.read_text(encoding="utf-8", errors="ignore"):
            warn(f"{rel} ya existe y no es nuestro: lo omito (usa `agentes migrate` para sustituirlo)")
            return
        p.write_text(content, encoding="utf-8")
        new_manifest.append(rel)

    cmd = cli_cmd()
    if "claude" in ides:
        for name, a in team.get("agents", {}).items():
            if a and not a.get("disabled"):
                write(f".claude/agents/{name}.md", render_agent(name, a, team))
        for name, c in team.get("commands", {}).items():
            if c and not c.get("disabled"):
                write(f".claude/commands/{name}.md", render_command(name, c, team))
        settings_p = root / ".claude" / "settings.json"
        settings_p.parent.mkdir(exist_ok=True)
        settings_p.write_text(json.dumps(_merge_hooks(_load_json(settings_p), cmd), indent=2, ensure_ascii=False) + "\n")
        mcp_p = root / ".mcp.json"
        mcp = _load_json(mcp_p)
        parts = cmd.split()
        mcp.setdefault("mcpServers", {})["agentes"] = {"type": "stdio", "command": parts[0], "args": parts[1:] + ["mcp"]}
        mcp_p.write_text(json.dumps(mcp, indent=2, ensure_ascii=False) + "\n")
        _update_block(root / "CLAUDE.md", team.get("orchestrator", ""))
    elif "claude" in cfg.get("ides", []):  # se desactivó Claude: limpiar sus integraciones
        _unwire_claude(root)

    if "kiro" in ides:
        kiro_gen.generate(root, team, write, cmd, GEN_MARK, lambda c: render_body(c, team), warn)
    elif "kiro" in cfg.get("ides", []):
        kiro_gen.merge_mcp(root, [], remove=True)
        kiro_gen.update_kiroignore(root, None)

    for rel in old_manifest - set(new_manifest):  # elimina generados obsoletos
        p = root / rel
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass

    gi = root / ".gitignore"
    lines = gi.read_text().splitlines() if gi.exists() else []
    missing = [l for l in GITIGNORE_LINES if l not in lines]
    if missing:
        gi.write_text("\n".join(lines + (["", "# agentes harness (memoria local)"] if lines else []) + missing) + "\n")

    cfg.update({"version": __version__, "synced_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "generated": sorted(new_manifest), "cli": cmd, "ides": ides})
    cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
    Store(root)  # crea la BD
    register_project(root, ides, get_profiles(root))
    return {"ides": ides,
            "agents": len({Path(r).stem for r in new_manifest if "/agents/" in r}),
            "commands": len({Path(r).stem for r in new_manifest
                             if "/commands/" in r or (r.startswith(".kiro/steering/") and "agentes-equipo" not in r)}),
            "workflows": sum(1 for r in new_manifest if r.endswith(".workflow.json"))}


def _unwire_claude(root: Path) -> None:
    sp = root / ".claude" / "settings.json"
    if sp.exists():
        sp.write_text(json.dumps(_remove_hooks(_load_json(sp)), indent=2, ensure_ascii=False) + "\n")
    mp = root / ".mcp.json"
    if mp.exists():
        m = _load_json(mp)
        m.get("mcpServers", {}).pop("agentes", None)
        mp.write_text(json.dumps(m, indent=2) + "\n")
    if (root / "CLAUDE.md").exists():
        _update_block(root / "CLAUDE.md", None)


def _projects_file() -> Path:
    return Path.home() / ".config" / "agentes" / "projects.json"


def load_projects() -> dict:
    try:
        return json.loads(_projects_file().read_text())
    except Exception:
        return {}


def register_project(root: Path, ides: list[str], profiles: list[str], remove: bool = False) -> None:
    data = load_projects()
    key = str(Path(root).resolve())
    if remove:
        data.pop(key, None)
    else:
        data[key] = {"version": __version__, "ides": ides, "perfiles": profiles, "sync": time.strftime("%Y-%m-%d %H:%M")}
    try:
        _projects_file().parent.mkdir(parents=True, exist_ok=True)
        _projects_file().write_text(json.dumps(data, indent=2, ensure_ascii=False))
    except OSError:
        pass


def uninstall(root: Path, purge: bool = False) -> list[str]:
    root = root.resolve()
    cfg = _load_json(root / HARNESS_DIR / "config.json")
    removed = []
    for rel in cfg.get("generated", []):
        p = root / rel
        if p.exists():
            p.unlink()
            removed.append(rel)
    _unwire_claude(root)
    register_project(root, [], [], remove=True)
    from . import kiro as kiro_gen
    kiro_gen.merge_mcp(root, [], remove=True)
    kiro_gen.update_kiroignore(root, None)
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
