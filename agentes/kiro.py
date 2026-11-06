"""Generación del equipo para Kiro (IDE / CLI / Web) a partir de team.yaml.

Mapeo:
  agentes      -> .kiro/agents/<nombre>.md            (custom agents / sub-agentes / pasos de workflow)
  comandos     -> .kiro/steering/<nombre>.md          (inclusion: manual -> aparecen como /comando)
  orquestador  -> .kiro/steering/agentes-equipo.md    (inclusion: always)
  hooks        -> .kiro/hooks/agentes.json            (formato v1: SessionStart, UserPromptSubmit, PostTaskExec)
  MCP          -> .kiro/settings/mcp.json             (servidor "agentes", fusionado con el existente)
  workflows    -> .kiro/workflows/<nombre>.workflow.json
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

import yaml

CLAUDE_TO_KIRO = {
    "Read": "read", "Grep": "read", "Glob": "read", "LS": "read",
    "Write": "write", "Edit": "write", "MultiEdit": "write", "NotebookEdit": "write",
    "Bash": "shell", "WebFetch": "web", "WebSearch": "web", "Task": "subagent", "Agent": "subagent",
}
KIRO_TO_CLAUDE = {
    "read": ["Read", "Grep", "Glob"], "fs_read": ["Read", "Grep", "Glob"],
    "write": ["Write", "Edit"], "fs_write": ["Write", "Edit"],
    "shell": ["Bash"], "execute_bash": ["Bash"],
    "web": ["WebFetch", "WebSearch"], "web_fetch": ["WebFetch"], "web_search": ["WebSearch"],
    "subagent": ["Task"],
}


def claude_tools_to_kiro(tools: list[str]) -> list[str]:
    out: list[str] = []
    for t in tools:
        if t.startswith("mcp__"):
            parts = t.split("__")
            k = f"@{parts[1]}" if len(parts) < 3 or parts[1] == "agentes" else f"@{parts[1]}/{parts[2]}"
        else:
            k = CLAUDE_TO_KIRO.get(t)
        if k and k not in out:
            out.append(k)
    if "@agentes" not in out:
        out.append("@agentes")
    return out


def kiro_tools_to_claude(tools) -> list[str] | None:
    """Convierte herramientas de un agente de Kiro al formato de Claude Code (None = todas)."""
    if tools in (None, "*") or (isinstance(tools, list) and ("*" in tools or "@builtin" in tools)):
        return None
    out: list[str] = []
    for t in tools:
        if t.startswith("@"):
            srv, _, tool = t[1:].partition("/")
            names = [f"mcp__{srv}__{tool}" if tool else f"mcp__{srv}"]
        else:
            names = KIRO_TO_CLAUDE.get(t, [])
        out += [n for n in names if n not in out]
    return out or None


def kiro_text(s: str) -> str:
    """Adapta textos escritos para Claude Code al vocabulario de Kiro."""
    s = s.replace("mcp__agentes__", "")
    s = re.sub(r"usando la herramienta AskUserQuestion", "preguntando en el chat", s)
    s = re.sub(r"(con|usando) AskUserQuestion", "en el chat", s)
    s = s.replace("AskUserQuestion", "preguntas en el chat")
    s = s.replace("$ARGUMENTS", "(lo que el usuario escribió junto al comando)")
    return s


def _front(d: dict) -> str:
    d = {k: v for k, v in d.items() if v not in (None, "", [])}
    return "---\n" + yaml.safe_dump(d, allow_unicode=True, sort_keys=False, width=1000,
                                    default_flow_style=False).strip() + "\n---\n"


def agent_tools(a: dict, team: dict) -> list[str]:
    k = team.get("kiro", {})
    if a.get("kiro_tools"):
        tools = list(a["kiro_tools"])
        if "*" not in tools and "@agentes" not in tools:
            tools.append("@agentes")
        return tools
    tools = a.get("tools")
    if isinstance(tools, str) and tools in k.get("toolsets", {}):
        return list(k["toolsets"][tools])
    if isinstance(tools, str) and tools in team.get("toolsets", {}):
        tools = team["toolsets"][tools]
    if isinstance(tools, str):
        tools = [t.strip() for t in tools.split(",")]
    if not tools:
        return ["*"]
    return claude_tools_to_kiro(tools)


def render_agent(name: str, a: dict, team: dict, gen_mark: str) -> str:
    fm = _front({"name": name, "description": a.get("description", "").strip(),
                 "tools": agent_tools(a, team), "includeMcpJson": True, "model": a.get("kiro_model")})
    body = [gen_mark, "", a.get("prompt", "").strip()]
    if a.get("extra_prompt"):
        body += ["", "## Instrucciones específicas de este proyecto", a["extra_prompt"].strip()]
    body += ["", team.get("shared_protocol", "").strip()]
    return fm + "\n" + kiro_text("\n".join(body).strip()) + "\n"


def render_command(name: str, c: dict, body: str, team: dict, gen_mark: str) -> str:
    note = team.get("kiro", {}).get("command_notes", {}).get(name, "")
    text = f"# /{name} — {c.get('description', '')}\n\n" + (note.strip() + "\n\n" if note else "") + body.strip()
    return _front({"inclusion": "manual"}) + gen_mark + "\n\n" + kiro_text(text) + "\n"


def render_orchestrator(team: dict, gen_mark: str) -> str:
    return _front({"inclusion": "always"}) + gen_mark + "\n\n" + team.get("kiro", {}).get("orchestrator", "").strip() + "\n"


def hooks_json(cmd: str) -> str:
    return json.dumps({"version": "v1", "hooks": [
        {"name": "agentes-contexto", "description": "Inyecta el contexto del proyecto desde la memoria de agentes",
         "trigger": "SessionStart", "action": {"type": "command", "command": f"{cmd} hook session-start"},
         "timeout": 20, "enabled": True},
        {"name": "agentes-recall", "description": "Agrega memorias relevantes del proyecto a cada mensaje",
         "trigger": "UserPromptSubmit", "action": {"type": "command", "command": f"{cmd} hook prompt"},
         "timeout": 20, "enabled": True},
        {"name": "agentes-ds-check", "description": "Al terminar el turno revisa que la UI use el design system",
         "trigger": "Stop", "action": {"type": "command", "command": f"{cmd} hook stop --kiro"},
         "timeout": 60, "enabled": True},
        {"name": "agentes-indexar", "description": "Re-indexa specs y código en la memoria tras ejecutar una tarea de spec",
         "trigger": "PostTaskExec", "action": {"type": "command", "command": f"{cmd} index --quiet"},
         "timeout": 120, "enabled": True},
    ]}, indent=2, ensure_ascii=False) + "\n"


def _walk_agents(node) -> list[str]:
    found = []
    if isinstance(node, dict):
        if node.get("type") == "step" and node.get("agent"):
            found.append(node["agent"])
        for key in ("steps", "branches"):
            for child in node.get(key, []) or []:
                found += _walk_agents(child)
    elif isinstance(node, list):
        for n in node:
            found += _walk_agents(n)
    return found


def _apply_economy(node, model: str):
    """Quita la marca `economy` y, si hay modelo económico configurado, lo asigna a esos pasos."""
    if isinstance(node, list):
        return [_apply_economy(n, model) for n in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for k, v in node.items():
        if k == "economy":
            continue
        out[k] = _apply_economy(v, model) if k in ("steps", "branches") else v
    if node.get("economy") and model and "modelId" not in node:
        out["modelId"] = model
    return out


def workflow_json(name: str, wf: dict, economy_model: str = "") -> str:
    body = {k: v for k, v in wf.items() if k != "disabled"}
    body["steps"] = _apply_economy(body.get("steps", []), economy_model)
    return json.dumps({"name": name, **body}, indent=2, ensure_ascii=False) + "\n"


IGNORE_START, IGNORE_END = "# agentes:start (generado; edita kiro.kiroignore en team.local.yaml)", "# agentes:end"


def update_kiroignore(root: Path, patterns: list[str] | None) -> None:
    """Escribe/actualiza el bloque gestionado de .kiroignore sin tocar las líneas del usuario."""
    p = root / ".kiroignore"
    text = p.read_text(encoding="utf-8") if p.exists() else ""
    if IGNORE_START in text and IGNORE_END in text:
        pre, rest = text.split(IGNORE_START, 1)
        post = rest.split(IGNORE_END, 1)[1]
        text = pre.rstrip("\n") + ("\n" if pre.strip() else "") + post.lstrip("\n")
    block = f"{IGNORE_START}\n" + "\n".join(patterns) + f"\n{IGNORE_END}\n" if patterns else ""
    text = (text.rstrip("\n") + "\n\n" if text.strip() else "") + block
    if text.strip():
        p.write_text(text, encoding="utf-8")
    elif p.exists():
        p.unlink()


def merge_mcp(root: Path, parts: list[str], remove: bool = False) -> None:
    p = root / ".kiro" / "settings" / "mcp.json"
    data = {}
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError:
            p.rename(p.with_suffix(".json.bak"))
    if remove:
        if not p.exists():
            return
        data.get("mcpServers", {}).pop("agentes", None)
    else:
        p.parent.mkdir(parents=True, exist_ok=True)
        data.setdefault("mcpServers", {})["agentes"] = {"command": parts[0], "args": parts[1:] + ["mcp"], "disabled": False}
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def generate(root: Path, team: dict, write: Callable[[str, str], None], cmd: str,
             gen_mark: str, render_body: Callable[[dict], str], warn: Callable[[str], None]) -> None:
    agents = {n: a for n, a in team.get("agents", {}).items() if a and not a.get("disabled")}
    for name, a in agents.items():
        write(f".kiro/agents/{name}.md", render_agent(name, a, team, gen_mark))
    for name, c in team.get("commands", {}).items():
        if c and not c.get("disabled"):
            write(f".kiro/steering/{name}.md", render_command(name, c, render_body(c), team, gen_mark))
    write(".kiro/steering/agentes-equipo.md", render_orchestrator(team, gen_mark))
    write(".kiro/hooks/agentes.json", hooks_json(cmd))
    k = team.get("kiro", {})
    if k.get("generate_workflows", True):
        for name, wf in (k.get("workflows") or {}).items():
            if not wf or wf.get("disabled"):
                continue
            missing = sorted({x for x in _walk_agents(wf.get("steps", [])) if x not in agents
                              and not x.startswith(("wf-", "semantic_"))})
            if missing:
                warn(f"workflow {name} omitido: usa agentes no disponibles {missing}")
                continue
            write(f".kiro/workflows/{name}.workflow.json", workflow_json(name, wf, k.get("economy_model") or ""))
    merge_mcp(root, cmd.split())
    update_kiroignore(root, list(k.get("kiroignore") or []))
