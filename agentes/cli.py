"""CLI `agentes`: instala y gestiona el equipo de agentes en cualquier proyecto."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from . import __version__
from .installer import (BASE_TEAM, IDES, deep_merge, get_ides, load_team, local_team_path, render_agent,
                        render_questions, set_ides, sync, uninstall)
from .store import HARNESS_DIR, KINDS, TASK_STATUSES, Store, dumps, find_root

C = {"b": "\033[1m", "g": "\033[32m", "y": "\033[33m", "r": "\033[31m", "c": "\033[36m", "0": "\033[0m"}
if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
    C = {k: "" for k in C}


def ok(msg):
    print(f"{C['g']}✔{C['0']} {msg}")


def warn(msg):
    print(f"{C['y']}!{C['0']} {msg}")


def root_of(args) -> Path:
    return Path(args.path).resolve() if getattr(args, "path", None) else find_root()


# ----------------------------------------------------------------------------- instalación
def cmd_install(a):
    root = Path(a.path or ".").resolve()
    if not root.is_dir():
        sys.exit(f"No existe {root}")
    ides = None
    if a.ide:
        ides = list(IDES) if a.ide in ("ambos", "all") else [a.ide]
        set_ides(root, ides)
    res = sync(root, ides=ides)
    ok(f"Harness instalado en {root} para {' + '.join(res['ides'])}: {res['agents']} agentes, "
       f"{res['commands']} comandos" + (f", {res['workflows']} workflows de Kiro" if res['workflows'] else ""))
    _offer_migration(root, a)
    store = Store(root)
    existing = any((root / m).exists() for m in ("package.json", "pyproject.toml", "go.mod", "Cargo.toml",
                                                 "requirements.txt", "pom.xml", "Gemfile", "composer.json", "src"))
    if existing and not a.no_scan:
        from .scanner import index_code, save_scan, scan
        print("Proyecto existente detectado → escaneando…")
        r = scan(root)
        save_scan(store, r)
        ok(f"Escaneo guardado ({', '.join(r.get('frameworks', [])[:6]) or 'stack no detectado'})")
        if not a.no_index:
            st = index_code(store, root)
            ok(f"Código indexado: {st['indexed']} archivos")
    vs = store.vector_status()
    print(f"Memoria vectorial: {vs}")
    if vs.startswith("desactivado") and os.environ.get("AGENTES_NO_VECTORS") != "1":
        print("   Se usa búsqueda por palabras clave (BM25). Cuando tengas conexión: `agentes memory rebuild`;"
              " para comparar opciones: `agentes bench`.")
    print(f"""
{C['b']}Siguiente paso{C['0']} → abre {'Claude Code (`claude`)' if 'claude' in res['ides'] else 'Kiro'} en el proyecto y ejecuta:
  {C['c']}/{'onboard' if existing else 'kickoff'}{C['0']}  {'(proyecto existente: contexto + preguntas)' if existing else '(proyecto nuevo: cuestionario de contexto)'}
Personaliza el equipo en .agentes/team.local.yaml y aplica con `agentes sync`.""")


def _print_migration_report(root: Path, items) -> None:
    from .migrate import keep_notes
    print(f"\n{C['b']}Configuraciones de agentes / archivos .md detectados ({len(items)}){C['0']}")
    for it in items:
        print(f"  • {it.path:42} {C['c']}{it.tool:16}{C['0']} → {it.action}")
    notes = keep_notes(root)
    if notes:
        print(f"{C['b']}Se conservan sin cambios{C['0']}")
        for n in notes:
            print(f"  · {n}")


def _ask(question: str) -> bool:
    if not sys.stdin.isatty():
        return False
    while True:
        ans = input(f"{question} [s/n] ").strip().lower()
        if ans in ("s", "si", "sí", "y", "yes"):
            return True
        if ans in ("n", "no"):
            return False


def _offer_migration(root: Path, a) -> None:
    from .migrate import apply, detect
    items = detect(root)
    if not items:
        return
    _print_migration_report(root, items)
    if getattr(a, "migrate", False) or _ask("\n¿Migrar a la base de datos y sustituir estas configuraciones por el equipo agentes? (se respaldan)"):
        st = apply(root, items)
        ok(f"Migración aplicada: {st}")
        print(f"   Deshacer: agentes migrate --restore {Path(st['backup']).name}")
    else:
        print(f"   Puedes hacerlo después con: {C['c']}agentes migrate --apply{C['0']} (simulacro: agentes migrate)")


def cmd_migrate(a):
    from .migrate import apply, backups, detect, git_dirty, restore
    root = root_of(a)
    if not (root / HARNESS_DIR).exists():
        sys.exit("Primero instala el harness: agentes install")
    if a.backups:
        print("\n".join(backups(root)) or "Sin respaldos.")
        return
    if a.restore is not None:
        ok(f"Restaurado: {restore(root, a.restore or None)}")
        return
    items = detect(root, a.include)
    if not items:
        ok("No se encontraron configuraciones de agentes ni .md por migrar.")
        return
    _print_migration_report(root, items)
    if not a.apply:
        print(f"\n{C['y']}Simulacro: no se cambió nada.{C['0']} Aplica con: agentes migrate --apply"
              f"{' --keep (importa sin eliminar originales)' if not a.keep else ''}")
        return
    dirty = git_dirty(root, [it.path for it in items])
    if dirty:
        warn("Estos archivos tienen cambios sin commit (igual se respaldan): " + ", ".join(dirty))
    if not a.yes and not _ask("\n¿Aplicar la migración?"):
        print("Cancelado." if sys.stdin.isatty() else "Sin terminal interactiva: usa --yes para confirmar.")
        return
    st = apply(root, items, keep=a.keep)
    ok(f"Migración aplicada: {st}")
    print(f"   Deshacer: agentes migrate --restore {Path(st['backup']).name}")


def cmd_ide(a):
    root = root_of(a)
    current = get_ides(root)
    if a.action == "list":
        print(f"IDEs configurados: {', '.join(current)}   (disponibles: {', '.join(IDES)})")
        return
    if not a.name or a.name not in IDES:
        sys.exit(f"Indica el IDE: {', '.join(IDES)}")
    new = sorted(set(current) | {a.name}) if a.action == "add" else [i for i in current if i != a.name]
    if not new:
        sys.exit("Debe quedar al menos un IDE.")
    res = sync(root, ides=new)
    set_ides(root, res["ides"])
    ok(f"IDEs: {', '.join(res['ides'])} (sincronizado)")


def cmd_sync(a):
    root = root_of(a)
    if not (root / HARNESS_DIR).exists():
        sys.exit("Este proyecto no tiene el harness. Ejecuta `agentes install`.")
    res = sync(root)
    ok(f"Sincronizado: {res['agents']} agentes, {res['commands']} comandos")


def cmd_uninstall(a):
    root = root_of(a)
    removed = uninstall(root, purge=a.purge)
    ok(f"Desinstalado ({len(removed)} archivos). " + ("Memoria eliminada." if a.purge else
                                                         "La memoria (.agentes/) se conserva; usa --purge para borrarla."))


def cmd_doctor(a):
    root = root_of(a)
    print(f"agentes {__version__}  ·  python {sys.version.split()[0]}  ·  proyecto: {root}")
    checks = [
        ("CLI en PATH", bool(shutil.which("agentes"))),
        ("claude (Claude Code) en PATH", bool(shutil.which("claude"))),
        ("git", bool(shutil.which("git"))),
        (".agentes/ instalado", (root / HARNESS_DIR).exists()),
        (".mcp.json con servidor agentes", '"agentes"' in (root / ".mcp.json").read_text() if (root / ".mcp.json").exists() else False),
        ("hooks en .claude/settings.json", "hook session-start" in (root / ".claude/settings.json").read_text() if (root / ".claude/settings.json").exists() else False),
    ]
    ides = get_ides(root)
    print(f"  IDEs: {', '.join(ides)}")
    if "kiro" in ides:
        checks += [
            ("Kiro: .kiro/agents generados", any((root / ".kiro/agents").glob("*.md")) if (root / ".kiro/agents").exists() else False),
            ("Kiro: hooks .kiro/hooks/agentes.json", (root / ".kiro/hooks/agentes.json").exists()),
            ("Kiro: MCP en .kiro/settings/mcp.json", '"agentes"' in (root / ".kiro/settings/mcp.json").read_text() if (root / ".kiro/settings/mcp.json").exists() else False),
            ("Kiro: recetas en .kiro/workflows", any((root / ".kiro/workflows").glob("*.workflow.json")) if (root / ".kiro/workflows").exists() else False),
        ]
        if "claude" not in ides:
            checks = [c for c in checks if not c[0].startswith((".mcp.json", "hooks en .claude", "claude (Claude"))]
    try:
        import chromadb  # noqa
        checks.append(("chromadb instalado (vectores)", True))
    except Exception:
        checks.append(("chromadb instalado (vectores) – opcional, usa BM25 si falta", False))
    for name, good in checks:
        print(f"  {'✔' if good else '✘'} {name}")
    if (root / HARNESS_DIR).exists():
        s = Store(root)
        print(dumps(s.stats()))
    # prueba MCP
    try:
        p = subprocess.run([sys.executable, "-m", "agentes", "mcp"], input=json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n", capture_output=True, text=True,
            timeout=30, cwd=root)
        n = len(json.loads(p.stdout.splitlines()[0])["result"]["tools"])
        print(f"  ✔ servidor MCP responde ({n} herramientas)")
    except Exception as e:
        print(f"  ✘ servidor MCP: {e}")


# ----------------------------------------------------------------------------- contexto
def cmd_scan(a):
    from .scanner import report_to_text, save_scan, scan
    root = root_of(a)
    r = scan(root)
    if not a.no_save:
        save_scan(Store(root), r)
    print(json.dumps(r, ensure_ascii=False, indent=2) if a.json else report_to_text(r))


def cmd_index(a):
    from .scanner import index_code
    root = root_of(a)
    s = Store(root)
    if a.rebuild:
        s.db.execute("DELETE FROM files")
        s.delete([r[0] for r in s.db.execute("SELECT id FROM memories WHERE kind='code'")])
    st = index_code(s, root, progress=None if a.quiet else (lambda n, t: print(f"  {n}/{t}…", end="\r")))
    if not a.quiet:
        ok(f"Indexado: {st}  ·  vectores: {s.vector_status()}")


def cmd_context(a):
    print(Store(root_of(a)).context_summary(a.max))


def cmd_questions(a):
    team = load_team(root_of(a))
    print(render_questions(team["questions"][a.kind]))


def cmd_kickoff(a):
    """Cuestionario interactivo en terminal (alternativa a /kickoff dentro de Claude)."""
    root = root_of(a)
    s = Store(root)
    team = load_team(root)
    current = {k: v for sec in s.profile_get().values() for k, v in sec.items()}
    print(f"{C['b']}Cuestionario ({a.kind}). Enter = mantener/omitir.{C['0']}")
    for sec in team["questions"][a.kind]:
        print(f"\n{C['c']}== {sec.get('title', sec['section'])} =={C['0']}")
        for q in sec["items"]:
            opts = q.get("opts") or []
            hint = "".join(f"\n    {i + 1}) {o}" for i, o in enumerate(opts))
            cur = current.get(q["id"])
            ans = input(f"• {q['q']}{hint}\n  {('[' + cur + '] ') if cur else ''}> ").strip()
            if ans.isdigit() and opts and 1 <= int(ans) <= len(opts):
                ans = str(opts[int(ans) - 1])
            if ans:
                s.profile_set(q["id"], ans, sec["section"])
    ok("Perfil guardado. En Claude Code ejecuta /kickoff para que el equipo genere requisitos, diseño y backlog.")


# ----------------------------------------------------------------------------- memoria
def cmd_memory(a):
    s = Store(root_of(a))
    if a.action == "search":
        for r in s.search(" ".join(a.args), a.kind, a.k):
            print(f"{C['c']}#{r['id']} [{r['kind']}]{C['0']} {r['source']} (score {r['score']})\n{r['text'][:600]}\n")
    elif a.action == "add":
        print(f"Guardado #{s.add(' '.join(a.args), a.kind or 'note', a.tags or '', agent='usuario')}")
    elif a.action == "list":
        for r in s.list(a.kind, a.k):
            print(f"#{r['id']} [{r['kind']}] {r['text'][:200]}")
    elif a.action == "delete":
        print(f"Eliminadas: {s.delete([int(x) for x in a.args])}")
    elif a.action == "stats":
        print(dumps(s.stats()))
    elif a.action == "export":
        out = Path(a.args[0]) if a.args else s.dir / "memory.json"
        out.write_text(dumps(s.export()))
        ok(f"Exportado a {out} (versionable en git para compartir con el equipo)")
    elif a.action == "import":
        src = Path(a.args[0]) if a.args else s.dir / "memory.json"
        print(s.import_(json.loads(src.read_text())))
    elif a.action == "rebuild":
        ok(f"Vectores regenerados: {s.rebuild_vectors()}")
    elif a.action == "profile":
        if len(a.args) >= 2:
            s.profile_set(a.args[0], " ".join(a.args[1:]), a.tags or "")
        print(dumps(s.profile_get()))
    elif a.action == "kinds":
        for k, v in KINDS.items():
            print(f"  {k:12} {v}")


# ----------------------------------------------------------------------------- tareas
def cmd_task(a):
    s = Store(root_of(a))
    if a.action == "add":
        print(f"Tarea #{s.task_create(' '.join(a.args), assignee=a.assignee or '', priority=a.priority, feature=a.feature or '')}")
    elif a.action in ("list", "ls"):
        rows = s.task_list(a.status, a.feature, a.all)
        for t in rows:
            print(f"#{t['id']:<4} {t['status']:<8} {t['priority']:<5} {t['title'][:70]:<70} {t['assignee']}")
        if not rows:
            print("Sin tareas.")
    elif a.action == "set":
        tid, status = int(a.args[0]), a.args[1]
        print(s.task_update(tid, status=status, notes=" ".join(a.args[2:]) or None))
    elif a.action == "done":
        for tid in a.args:
            s.task_update(int(tid), status="done")
        ok("Hecho.")
    elif a.action == "show":
        print(dumps(s.task_update(int(a.args[0]))))


# ----------------------------------------------------------------------------- equipo
def _load_local(root: Path) -> dict:
    p = local_team_path(root)
    return (yaml.safe_load(p.read_text()) or {}) if p.exists() else {}


def _save_local(root: Path, data: dict):
    p = local_team_path(root)
    p.parent.mkdir(exist_ok=True)
    header = "# Personalización del equipo para este proyecto. Aplica con: agentes sync\n"
    p.write_text(header + yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=110))


def _editor(path: Path):
    ed = os.environ.get("VISUAL") or os.environ.get("EDITOR") or ("code -w" if shutil.which("code") else "nano")
    subprocess.call(f'{ed} "{path}"', shell=True)


def cmd_agent(a):
    root = root_of(a)
    team = load_team(root)
    agents = team.get("agents", {})
    local = _load_local(root)
    la = local.setdefault("agents", {})
    if a.action == "list":
        for n, d in agents.items():
            flag = " (desactivado)" if d.get("disabled") else (" (personalizado)" if n in la else "")
            print(f"  {C['b']}{n:18}{C['0']} {d.get('model', 'inherit'):7} {d.get('description', '')[:85]}{flag}")
        return
    name = a.name
    if a.action == "show":
        print(render_agent(name, agents[name], team))
        return
    if a.action == "add":
        la[name] = {"description": a.description or f"Agente {name}", "model": a.model or "sonnet",
                    "tools": a.tools or "full", "prompt": a.prompt or f"Eres {name}. Describe aquí su rol."}
    elif a.action == "extend":
        la.setdefault(name, {})["extra_prompt"] = ((la.get(name, {}).get("extra_prompt") or "") + "\n" + a.text).strip()
    elif a.action == "model":
        la.setdefault(name, {})["model"] = a.text
    elif a.action == "disable":
        la.setdefault(name, {})["disabled"] = True
    elif a.action == "enable":
        la.setdefault(name, {}).pop("disabled", None)
    elif a.action == "override":
        la[name] = deep_merge(agents.get(name, {}), la.get(name, {}))
    elif a.action == "reset":
        la.pop(name, None)
    elif a.action == "remove":
        if name in yaml.safe_load(BASE_TEAM.read_text())["agents"]:
            la.setdefault(name, {})["disabled"] = True
        else:
            la.pop(name, None)
    _save_local(root, local)
    if a.action in ("add", "override"):
        _editor(local_team_path(root)) if a.edit else None
    if (root / HARNESS_DIR).exists():
        sync(root, quiet=True)
    ok(f"Agente '{name}': {a.action} aplicado y sincronizado")


def cmd_command(a):
    root = root_of(a)
    team = load_team(root)
    local = _load_local(root)
    lc = local.setdefault("commands", {})
    if a.action == "list":
        for n, c in team.get("commands", {}).items():
            print(f"  /{n:12} {c.get('description', '')[:95]}{' (desactivado)' if c.get('disabled') else ''}")
        return
    if a.action == "add":
        lc[a.name] = {"description": a.description or a.name, "body": a.body or "$ARGUMENTS"}
    elif a.action == "disable":
        lc.setdefault(a.name, {})["disabled"] = True
    elif a.action == "reset":
        lc.pop(a.name, None)
    _save_local(root, local)
    sync(root, quiet=True)
    ok(f"Comando /{a.name}: {a.action}")


def cmd_team(a):
    root = root_of(a)
    if a.action == "path":
        print(f"base : {BASE_TEAM}\nlocal: {local_team_path(root)}")
    elif a.action == "edit":
        _editor(local_team_path(root) if not a.base else BASE_TEAM)
        if (root / HARNESS_DIR).exists():
            sync(root, quiet=True)
            ok("Sincronizado")
    elif a.action == "export":
        print(yaml.safe_dump(load_team(root), allow_unicode=True, sort_keys=False, width=110))
    elif a.action == "validate":
        team = load_team(root)
        errs = []
        for n, d in team.get("agents", {}).items():
            for k in ("description", "prompt"):
                if not d.get("disabled") and not d.get(k):
                    errs.append(f"agente {n}: falta '{k}'")
        for n, c in team.get("commands", {}).items():
            if not c.get("disabled") and not c.get("body"):
                errs.append(f"comando {n}: falta 'body'")
        print("\n".join(errs) if errs else "team válido ✔")


# ----------------------------------------------------------------------------- hooks
def cmd_hook(a):
    """Hooks de Claude Code. Nunca deben romper la sesión: siempre exit 0."""
    try:
        raw = sys.stdin.read() if not sys.stdin.isatty() else ""
        data = json.loads(raw) if raw.strip() else {}
        root = find_root(data.get("cwd"))
        if not (root / HARNESS_DIR).exists():
            return
        if a.event == "session-start":
            s = Store(root, use_vectors=False)
            print("# Contexto del proyecto (memoria del equipo `agentes`)\n" + s.context_summary())
        elif a.event == "prompt":
            _recall(root, data)
    except Exception as e:  # pragma: no cover
        print(f"(agentes hook: {e})", file=sys.stderr)


def cmd_requisitos(a):
    """Ejecuta requisitos.sh (bash) para revisar/instalar el software necesario."""
    script = Path(__file__).parent / "requisitos.sh"
    root = root_of(a)
    extra = [x for x in a.extra if x != "--"]
    if "--proyecto" not in extra and "-p" not in extra:
        extra = ["--proyecto", str(root)] + extra
    sys.exit(subprocess.call(["bash", str(script), *extra]))


ACKS = {"si", "sí", "no", "ok", "okay", "dale", "va", "vale", "continua", "continúa", "sigue", "gracias", "listo",
        "perfecto", "adelante", "hazlo", "procede", "yes", "go", "next", "thanks", "claro", "correcto", "bien"}
STOP = {"para", "como", "cómo", "que", "qué", "con", "por", "una", "uno", "los", "las", "del", "el", "la", "de", "en",
        "y", "a", "un", "es", "se", "lo", "al", "más", "mas", "este", "esta", "esto", "ese", "esa", "hay", "puedes",
        "quiero", "necesito", "the", "and", "for", "with", "this", "that", "from", "what", "how", "can", "you"}


def _recall(root: Path, data: dict) -> None:
    """Auto-recall selectivo: solo memorias realmente relevantes y nunca repetidas en la misma sesión."""
    import re as _re
    settings = load_team(root).get("settings", {})
    prompt = (data.get("prompt") or data.get("user_prompt") or os.environ.get("USER_PROMPT") or "").strip()
    if not settings.get("auto_recall", True) or prompt.startswith("/"):
        return
    words = _re.findall(r"\w+", prompt.lower())
    if len(prompt) < settings.get("auto_recall_min_chars", 20) or all(w in ACKS or w in STOP for w in words):
        return
    terms = {w for w in words if len(w) > 3 and w not in STOP}
    k = int(settings.get("auto_recall_k", 3))
    need = int(settings.get("auto_recall_min_overlap", 2))
    s = Store(root)
    kinds = ["decision", "convention", "design", "requirement", "bug", "security", "learning", "profile", "note"]

    def relevant(h) -> bool:
        overlap = len(terms & set(_re.findall(r"\w+", h["text"].lower())))
        return h["match"] == "both" or overlap >= need or (h["match"] == "vec" and h["vec_top"] and overlap >= 1)

    state_p = s.dir / "recall-state.json"
    try:
        state = json.loads(state_p.read_text()) if state_p.exists() else {}
    except Exception:
        state = {}
    sid = str(data.get("session_id") or "")
    seen = set(state.get(sid, [])) if sid else set()
    # fase 1: palabras clave (instantáneo, no carga el modelo); fase 2: semántica solo si la 1 no encontró nada
    picked = [h for h in s.search(prompt, kinds, k * 3, vectors=False) if relevant(h) and h["id"] not in seen][:k]
    if not picked and settings.get("auto_recall_vectors", True):
        picked = [h for h in s.search(prompt, kinds, k * 3) if relevant(h) and h["id"] not in seen][:k]
    if not picked:
        return
    print("Memorias relevantes (auto-recall):\n" + "\n".join(f"- [{h['kind']}#{h['id']}] {h['text'][:300]}" for h in picked))
    if sid:
        state[sid] = sorted(seen | {h["id"] for h in picked})
        order = [x for x in state.get("_order", []) if x != sid] + [sid]
        for old in order[:-20]:
            state.pop(old, None)
        state["_order"] = order[-20:]
        try:
            state_p.write_text(json.dumps(state))
        except OSError:
            pass


def cmd_bench(a):
    from . import bench
    root = root_of(a)
    modes = [m.strip() for m in a.modelos.split(",") if m.strip()]
    if a.queries:
        memories, cases = bench.project_cases(root, Path(a.queries))
        origen = f"tus preguntas ({a.queries}) sobre {len(memories)} memorias del proyecto"
        if not cases:
            sys.exit("Ninguna pregunta coincidió con una memoria (revisa el campo expect).")
    else:
        memories, cases = bench.builtin_cases()
        origen = f"conjunto de prueba en español ({len(memories)} memorias, {len(cases)} preguntas)"
    print(f"Benchmark de búsqueda · {origen}\nModos: {', '.join(modes)} (la primera vez se descargan los modelos)\n")
    results = bench.run(modes, memories, cases)
    if a.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return
    print(bench.table(results))
    print(f"\n{C['b']}Recomendación:{C['0']} {bench.recommend(results)}")


def cmd_mcp(a):
    from .mcp_server import serve
    serve()


# ----------------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agentes", description="Harness de equipo de desarrollo para Claude Code y Kiro")
    p.add_argument("--version", action="version", version=f"agentes {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def sp(name, fn, help_):
        x = sub.add_parser(name, help=help_)
        x.set_defaults(fn=fn)
        x.add_argument("--path", "-C", help="Ruta del proyecto (default: actual)")
        return x

    x = sp("install", cmd_install, "Instala el harness en un proyecto (nuevo o existente)")
    x.add_argument("target", nargs="?", help="Ruta (default: .)")
    x.add_argument("--no-scan", action="store_true")
    x.add_argument("--no-index", action="store_true")
    x.add_argument("--ide", choices=[*IDES, "ambos", "all"], help="IDE(s) a generar (default: autodetección)")
    x.add_argument("--migrate", action="store_true", help="Migrar configuraciones previas sin preguntar")
    x = sp("migrate", cmd_migrate, "Migra .md y configuraciones de agentes existentes a la BD y al equipo")
    x.add_argument("--apply", action="store_true", help="Aplicar (por defecto es un simulacro)")
    x.add_argument("--keep", action="store_true", help="Importar sin eliminar los originales")
    x.add_argument("--include", "-i", action="append", default=[], metavar="GLOB",
                   help="Archivos .md extra a migrar (ej. 'docs/decisiones/*.md'); repetible")
    x.add_argument("--yes", "-y", action="store_true", help="No pedir confirmación")
    x.add_argument("--restore", nargs="?", const="", metavar="FECHA", help="Deshacer una migración (default: la última)")
    x.add_argument("--backups", action="store_true", help="Listar respaldos de migración")
    x = sp("bench", cmd_bench, "Compara BM25 vs búsqueda híbrida por modelo de embeddings (calidad, latencia, tokens)")
    x.add_argument("--modelos", default="bm25,ingles,multilingue",
                   help="Modos separados por coma: bm25, ingles, multilingue, multilingue-grande u otro modelo de fastembed")
    x.add_argument("--queries", "-q", help="YAML con tus preguntas: [{query, expect: 'fragmento de la memoria'}]")
    x.add_argument("--json", action="store_true")
    x = sp("ide", cmd_ide, "IDEs del proyecto: list | add <claude|kiro> | remove <claude|kiro>")
    x.add_argument("action", choices=["list", "add", "remove"])
    x.add_argument("name", nargs="?")
    sp("sync", cmd_sync, "Regenera agentes/comandos/hooks desde team.yaml + team.local.yaml")
    x = sp("uninstall", cmd_uninstall, "Quita el harness del proyecto")
    x.add_argument("--purge", action="store_true", help="Borra también la memoria (.agentes/)")
    sp("doctor", cmd_doctor, "Diagnóstico de la instalación")
    x = sp("requisitos", cmd_requisitos, "Revisa el software necesario (harness + proyecto) e instala lo que falte (s/n)")
    x.add_argument("extra", nargs=argparse.REMAINDER, help="--check | --yes | --solo-requeridos | --lista")

    x = sp("scan", cmd_scan, "Analiza el proyecto (stack, scripts, git, deuda) y lo guarda en memoria")
    x.add_argument("--json", action="store_true")
    x.add_argument("--no-save", action="store_true")
    x = sp("index", cmd_index, "Indexa el código y las specs de Kiro en la memoria vectorial (incremental)")
    x.add_argument("--rebuild", action="store_true")
    x.add_argument("--quiet", "-q", action="store_true")
    x = sp("context", cmd_context, "Muestra el resumen de contexto que reciben los agentes")
    x.add_argument("--max", type=int, default=6000)
    x = sp("questions", cmd_questions, "Muestra el cuestionario")
    x.add_argument("kind", nargs="?", default="new", choices=["new", "existing"])
    x = sp("kickoff", cmd_kickoff, "Cuestionario de contexto en la terminal")
    x.add_argument("kind", nargs="?", default="new", choices=["new", "existing"])

    x = sp("memory", cmd_memory, "Memoria: search|add|list|delete|stats|export|import|rebuild|profile|kinds")
    x.add_argument("action", choices=["search", "add", "list", "delete", "stats", "export", "import", "rebuild", "profile", "kinds"])
    x.add_argument("args", nargs="*")
    x.add_argument("--kind", "-k")
    x.add_argument("--tags")
    x.add_argument("-n", dest="k", type=int, default=10)

    x = sp("task", cmd_task, "Tareas: add|list|set|done|show")
    x.add_argument("action", choices=["add", "list", "ls", "set", "done", "show"])
    x.add_argument("args", nargs="*")
    x.add_argument("--assignee", "-a")
    x.add_argument("--priority", "-p", default="media", choices=["alta", "media", "baja"])
    x.add_argument("--feature", "-f")
    x.add_argument("--status", "-s", choices=TASK_STATUSES)
    x.add_argument("--all", action="store_true")

    x = sp("agent", cmd_agent, "Equipo: list|show|add|extend|model|override|disable|enable|reset|remove")
    x.add_argument("action", choices=["list", "show", "add", "extend", "model", "override", "disable", "enable", "reset", "remove"])
    x.add_argument("name", nargs="?")
    x.add_argument("text", nargs="?", help="Texto para extend / modelo para model")
    x.add_argument("--description", "-d")
    x.add_argument("--prompt")
    x.add_argument("--model", "-m")
    x.add_argument("--tools", "-t", help="'full', 'readonly' o lista separada por comas")
    x.add_argument("--edit", "-e", action="store_true", help="Abrir el editor tras crear/override")

    x = sp("command", cmd_command, "Comandos slash: list|add|disable|reset")
    x.add_argument("action", choices=["list", "add", "disable", "reset"])
    x.add_argument("name", nargs="?")
    x.add_argument("--description", "-d")
    x.add_argument("--body", "-b")

    x = sp("team", cmd_team, "Definición del equipo: path|edit|export|validate")
    x.add_argument("action", choices=["path", "edit", "export", "validate"])
    x.add_argument("--base", action="store_true", help="Editar el team.yaml base (afecta a todos los proyectos)")

    x = sub.add_parser("hook", help="(interno) hooks de Claude Code")
    x.add_argument("event", choices=["session-start", "prompt"])
    x.set_defaults(fn=cmd_hook)
    x = sub.add_parser("mcp", help="(interno) servidor MCP stdio")
    x.set_defaults(fn=cmd_mcp)
    return p


def main(argv=None):
    parser = build_parser()
    a, unknown = parser.parse_known_args(argv)
    if a.cmd == "requisitos":
        a.extra = list(a.extra) + unknown
    elif unknown:
        parser.error(f"argumentos no reconocidos: {' '.join(unknown)}")
    if a.cmd == "install" and a.target:
        a.path = a.target
    if a.cmd in ("agent",) and a.action not in ("list",) and not a.name:
        sys.exit("Falta el nombre del agente")
    a.fn(a)


if __name__ == "__main__":
    main()
