"""Servidor MCP mínimo (JSON-RPC 2.0 sobre stdio, sin dependencias externas).

Expone a los agentes de Claude Code la memoria vectorial, el perfil del proyecto
y el tablero de tareas. Se registra en `.mcp.json` como servidor "agentes", por lo
que las herramientas aparecen como `mcp__agentes__<nombre>`.
"""
from __future__ import annotations

import json
import sys
import traceback
from typing import Any, Callable

from . import __version__
from .store import KINDS, TASK_STATUSES, Store, dumps

_store: Store | None = None


def store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store


def _s(desc: str, **props) -> dict:
    required = [k for k, v in props.items() if v.pop("required", False)]
    return {"description": desc, "inputSchema": {"type": "object", "properties": props, "required": required}}


KIND_DESC = "Tipo de memoria"

TOOLS: dict[str, tuple[dict, Callable[..., Any]]] = {}


def tool(name: str, spec: dict):
    def deco(fn):
        TOOLS[name] = (spec, fn)
        return fn
    return deco


@tool("project_context", _s("Resumen del proyecto (reglas, perfil, decisiones, diseño, tareas). Llamar al empezar."))
def _ctx():
    return store().context_summary(8000)


@tool("memory_search", _s(
    "Busca en memoria y código indexado. Devuelve fragmentos cortos con archivo:línea; lee solo esas líneas si necesitas más.",
    query={"type": "string", "required": True},
    kinds={"type": "string", "description": "Tipos separados por coma; 'code' o 'spec' para código/specs"},
    k={"type": "integer", "description": "Resultados (default 5)"},
    full={"type": "boolean", "description": "Texto completo (más tokens)"},
))
def _search(query: str, kinds: str | None = None, k: int = 5, full: bool = False):
    res = store().search(query, kinds, min(int(k or 5), 15))
    if not res:
        return "Sin resultados."
    limit = 2000 if full else 500
    out = []
    for r in res:
        text = r["text"].strip()
        if r["kind"] in ("code", "spec") and text.startswith("// "):
            text = text.split("\n", 1)[1] if "\n" in text else ""  # la ruta ya va en el encabezado
        cut = text[:limit] + (" …" if len(text) > limit else "")
        out.append(f"#{r['id']} [{r['kind']}]{' ' + r['source'] if r['source'] else ''}\n{cut}")
    return "\n\n".join(out)


@tool("code_locate", _s(
    "Archivos y líneas más probables para una descripción (índice del código, sin modelo). Úsalo cuando no te indiquen archivos.",
    query={"type": "string", "required": True},
    k={"type": "integer", "description": "Archivos (default 6)"},
))
def _locate(query: str, k: int = 6):
    from .triage import locate
    files = locate(store(), query, min(int(k or 6), 15))
    return "\n".join(f"{f['archivo']}:{','.join(f['lineas'])}" for f in files) or "Sin coincidencias (¿falta `agentes index`?)."


@tool("ds_lookup", _s(
    "Design system del proyecto: firma completa, documentación, ubicación y ejemplo de uso de componentes; o tokens "
    "(colores, tipografía, espaciado). Úsalo antes de escribir UI.",
    query={"type": "string", "required": True, "description": "Nombre (DSButton) o descripción ('botón primario', 'colores')"},
    platform={"type": "string", "enum": ["ios", "android"]},
))
def _ds_lookup(query: str, platform: str | None = None):
    from .ds import lookup
    return lookup(store().root, query, platform)


@tool("ds_check", _s("Revisa los cambios actuales: usos de componentes nativos o valores literales que deberían usar el design system."))
def _ds_check():
    from .ds import check, render_check
    return render_check(check(store().root))


@tool("triage", _s(
    "Clasifica una tarea: tipo (fix, feature, update, refactor, ajuste...), peso XS-XL, ruta más barata y archivos probables.",
    task={"type": "string", "required": True},
))
def _triage(task: str):
    from .triage import render, triage
    return render(triage(store().root, task, store=store()))


@tool("memory_add", _s(
    "Guarda conocimiento durable (1-3 frases autocontenidas). Nada trivial ni temporal.",
    text={"type": "string", "required": True},
    kind={"type": "string", "enum": [k for k in KINDS if k not in ("code", "spec", "scan")], "required": True},
    tags={"type": "string"},
    source={"type": "string", "description": "Archivo o feature"},
    agent={"type": "string"},
))
def _add(text: str, kind: str = "note", tags: str = "", source: str = "", agent: str = ""):
    if kind not in KINDS:
        raise ValueError(f"kind inválido. Opciones: {list(KINDS)}")
    mid = store().add(text, kind, tags, source, agent)
    return f"Guardado #{mid} [{kind}]"


@tool("memory_list", _s("Lista memorias recientes.", kind={"type": "string"}, limit={"type": "integer"}))
def _list(kind: str | None = None, limit: int = 30):
    rows = store().list(kind, int(limit or 30))
    return "\n".join(f"#{r['id']} [{r['kind']}] {r['text'][:300]}" for r in rows) or "Vacío."


@tool("memory_delete", _s("Elimina memorias obsoletas por id.",
                          ids={"type": "array", "items": {"type": "integer"}, "required": True}))
def _delete(ids: list[int]):
    return f"Eliminadas {store().delete([int(i) for i in ids])} memorias."


@tool("profile_get", _s("Perfil del proyecto (kickoff/onboarding).", key={"type": "string"}))
def _pget(key: str | None = None):
    prof = store().profile_get(key)
    return dumps(prof) if prof else "Perfil vacío. Ejecuta /kickoff o /onboard."


@tool("profile_set", _s(
    "Guarda respuestas del perfil.",
    entries={"type": "array", "required": True,
             "items": {"type": "object", "properties": {
                 "key": {"type": "string"}, "value": {"type": "string"}, "section": {"type": "string"}},
                 "required": ["key", "value"]}},
))
def _pset(entries: list[dict]):
    for e in entries:
        store().profile_set(e["key"], e["value"], e.get("section", ""))
    return f"Perfil actualizado ({len(entries)} claves)."


@tool("task_create", _s(
    "Crea una tarea en el tablero.",
    title={"type": "string", "required": True},
    description={"type": "string"},
    assignee={"type": "string", "description": "Agente responsable"},
    priority={"type": "string", "enum": ["alta", "media", "baja"]},
    feature={"type": "string"},
    parent_id={"type": "integer"},
))
def _tcreate(title: str, description: str = "", assignee: str = "", priority: str = "media",
             feature: str = "", parent_id: int | None = None):
    return f"Tarea #{store().task_create(title, description, assignee, priority, parent_id, feature)} creada."


@tool("task_list", _s("Lista tareas (por defecto, abiertas).",
                      status={"type": "string", "enum": list(TASK_STATUSES)},
                      feature={"type": "string"},
                      include_done={"type": "boolean"}))
def _tlist(status: str | None = None, feature: str | None = None, include_done: bool = False):
    rows = store().task_list(status, feature, include_done)
    return "\n".join(
        f"#{t['id']} [{t['status']}|{t['priority']}] {t['title']} -> {t['assignee'] or '-'}"
        f"{' (' + t['feature'] + ')' if t['feature'] else ''}" for t in rows) or "Sin tareas."


@tool("task_update", _s(
    "Actualiza una tarea.",
    id={"type": "integer", "required": True},
    status={"type": "string", "enum": list(TASK_STATUSES)},
    assignee={"type": "string"},
    priority={"type": "string"},
    notes={"type": "string", "description": "Nota de avance"},
    title={"type": "string"},
    description={"type": "string"},
))
def _tupdate(id: int, **kw):
    t = store().task_update(int(id), **kw)
    return f"#{t['id']} [{t['status']}] {t['title']}" if t else "Tarea no encontrada."


# ---------------------------------------------------------------------------- protocolo
def _reply(id_, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": id_}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle(msg: dict) -> None:
    method, id_ = msg.get("method"), msg.get("id")
    if id_ is None:  # notificación
        return
    params = msg.get("params") or {}
    if method == "initialize":
        _reply(id_, {
            "protocolVersion": params.get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "agentes", "version": __version__},
            "instructions": "Memoria persistente, perfil y tareas del proyecto. Empieza con project_context.",
        })
    elif method == "ping":
        _reply(id_, {})
    elif method == "tools/list":
        _reply(id_, {"tools": [{"name": n, **spec} for n, (spec, _) in TOOLS.items()]})
    elif method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        if name not in TOOLS:
            _reply(id_, error={"code": -32602, "message": f"Herramienta desconocida: {name}"})
            return
        try:
            text = TOOLS[name][1](**args)
            _reply(id_, {"content": [{"type": "text", "text": str(text)}], "isError": False})
        except Exception as e:
            _reply(id_, {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True})
    elif method in ("resources/list", "prompts/list"):
        _reply(id_, {method.split("/")[0]: []})
    else:
        _reply(id_, error={"code": -32601, "message": f"Método no soportado: {method}"})


def serve() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            handle(json.loads(line))
        except Exception:
            traceback.print_exc(file=sys.stderr)
