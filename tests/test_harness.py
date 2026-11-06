import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from agentes.installer import sync, uninstall
from agentes.scanner import index_code, scan
from agentes.store import Store


class FakeEF:
    """Embedding determinista (bolsa de palabras hasheada) para probar la ruta vectorial sin descargar modelos."""
    def __call__(self, input):
        out = []
        for t in input:
            v = [0.0] * 64
            for w in t.lower().split():
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1.0
            out.append(v)
        return out

    def name(self):
        return "fake"

    @staticmethod
    def build_from_config(config):
        return FakeEF()

    def get_config(self):
        return {}

    def is_legacy(self):
        return False

    def embed_query(self, input):
        return self(input)


@pytest.fixture
def proj(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "vitest"}, "dependencies": {"next": "14"}}))
    (tmp_path / "src" / "pay.ts").write_text("export function charge(cents: number) { return cents }\n")
    return tmp_path


def test_memory_tasks_profile(proj):
    s = Store(proj, use_vectors=False)
    mid = s.add("Usamos PostgreSQL con Prisma", "decision")
    assert s.add("Usamos PostgreSQL con Prisma", "decision") == mid  # dedupe
    assert s.search("prisma postgres")[0]["id"] == mid
    s.profile_set("colores", "#000 primario", "diseno")
    assert s.profile_get()["diseno"]["colores"] == "#000 primario"
    t = s.task_create("Login", assignee="backend-dev")
    assert s.task_update(t, status="doing", notes="ok")["status"] == "doing"
    with pytest.raises(ValueError):
        s.task_update(t, status="xx")
    assert "Login" in s.context_summary()


def test_vectors_hybrid(proj):
    pytest.importorskip("chromadb")
    s = Store(proj, embedding_function=FakeEF())
    s.add("los precios se guardan en centavos", "convention")
    s.add("el login usa magic links", "decision")
    assert s.collection is not None and s.collection.count() == 2, s.vector_status()
    assert "centavos" in s.search("precios centavos", k=1)[0]["text"]
    assert s.rebuild_vectors() == 2


def test_scan_index(proj):
    r = scan(proj)
    assert "Next.js" in r["frameworks"] and r["scripts"]
    s = Store(proj, use_vectors=False)
    st = index_code(s, proj)
    assert st["indexed"] >= 2
    assert index_code(s, proj)["unchanged"] == st["indexed"]  # incremental
    assert s.search("charge cents", "code")


def test_install_sync_uninstall(proj):
    (proj / ".claude" / "commands").mkdir(parents=True)
    (proj / ".claude" / "commands" / "mio.md").write_text("propio")
    (proj / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo hi"}]}]}}))
    res = sync(proj)
    assert res["agents"] >= 10 and res["commands"] >= 14
    sync(proj)  # idempotente
    st = json.loads((proj / ".claude" / "settings.json").read_text())
    assert len(st["hooks"]["SessionStart"]) == 1 and "Stop" in st["hooks"]
    assert "{{questions_new}}" not in (proj / ".claude/commands/kickoff.md").read_text()
    uninstall(proj)
    assert (proj / ".claude/commands/mio.md").exists()
    assert not (proj / ".claude/agents/tech-lead.md").exists()
    assert "Stop" in json.loads((proj / ".claude" / "settings.json").read_text())["hooks"]


def test_mcp_roundtrip(proj):
    Store(proj, use_vectors=False)
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "memory_add", "arguments": {"text": "hola mundo", "kind": "note"}}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "memory_search", "arguments": {"query": "hola"}}}]
    p = subprocess.run([sys.executable, "-m", "agentes", "mcp"], input="\n".join(map(json.dumps, msgs)) + "\n",
                       capture_output=True, text=True, cwd=proj, env={"AGENTES_NO_VECTORS": "1", "PATH": ""})
    out = [json.loads(l) for l in p.stdout.splitlines()]
    assert out[0]["result"]["serverInfo"]["name"] == "agentes"
    assert "hola mundo" in out[2]["result"]["content"][0]["text"]


def test_requisitos_check(tmp_path):
    script = Path(__file__).parent.parent / "agentes" / "requisitos.sh"
    (tmp_path / ".agentes").mkdir()
    (tmp_path / ".agentes" / "requisitos.conf").write_text(
        "noexiste|requerido|-|noexiste-xyz --version|cmd:true|cmd:true|siempre|Prueba\n"
        "gitviejo|opcional|999.0|git --version|cmd:true|cmd:true|siempre|Prueba version\n")
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(tmp_path), "NO_COLOR": "1"}
    p = subprocess.run(["bash", str(script), "--check", "--proyecto", str(tmp_path)],
                       capture_output=True, text=True, env=env)
    assert p.returncode == 1, p.stdout + p.stderr  # falta un requerido
    assert "noexiste" in p.stdout and "actualizar" in p.stdout
    lista = subprocess.run(["bash", str(script), "--lista"], capture_output=True, text=True, env=env)
    assert "claude" in lista.stdout and "docker" in lista.stdout


def test_kiro_generation(proj):
    from agentes.installer import set_ides
    set_ides(proj, ["kiro"])
    res = sync(proj)
    assert res["ides"] == ["kiro"] and res["workflows"] == 5
    agent = (proj / ".kiro/agents/tech-lead.md").read_text()
    assert agent.startswith("---\nname: tech-lead") and "'@agentes'" in agent and "mcp__agentes__" not in agent
    steer = (proj / ".kiro/steering/feature.md").read_text()
    assert steer.startswith("---\ninclusion: manual\n---") and "$ARGUMENTS" not in steer
    assert (proj / ".kiro/steering/agentes-equipo.md").read_text().startswith("---\ninclusion: always\n---")
    hooks = json.loads((proj / ".kiro/hooks/agentes.json").read_text())
    assert hooks["version"] == "v1" and {h["trigger"] for h in hooks["hooks"]} == {"SessionStart", "UserPromptSubmit", "PostTaskExec"}
    wf = json.loads((proj / ".kiro/workflows/agentes-feature.workflow.json").read_text())
    assert wf["name"] == "agentes-feature" and wf["inputs"]["task"] == "prompt"
    assert "agentes" in json.loads((proj / ".kiro/settings/mcp.json").read_text())["mcpServers"]
    assert not (proj / ".claude/agents").exists() and not (proj / ".mcp.json").exists()


def test_migrate_apply_restore(proj):
    sync(proj)
    (proj / "CLAUDE.md").write_text((proj / "CLAUDE.md").read_text() + "\n# Reglas\nNunca uses var en JavaScript.\n")
    (proj / "AGENTS.md").write_text("# Seguridad\nNo subas secretos al repositorio.\n")
    (proj / ".claude/agents/docs-writer.md").write_text("---\nname: docs-writer\ndescription: Docs\ntools: Read\n---\nEscribe docs.\n")
    (proj / ".kiro/steering").mkdir(parents=True)
    (proj / ".kiro/steering/release.md").write_text("---\ninclusion: manual\n---\nGenera el changelog.\n")
    original = {p: (proj / p).read_text() for p in ("AGENTS.md", ".claude/agents/docs-writer.md", ".kiro/steering/release.md")}
    from agentes.migrate import apply, detect, restore
    items = detect(proj)
    assert {i.path for i in items} >= {"CLAUDE.md", "AGENTS.md", ".claude/agents/docs-writer.md", ".kiro/steering/release.md"}
    assert not any(i.path.startswith("src/") or i.path == "package.json" for i in items)
    st = apply(proj, items, log=lambda *_: None)
    assert st["agentes"] == 1 and st["comandos"] == 1 and not (proj / "AGENTS.md").exists()
    s = Store(proj, use_vectors=False)
    assert "Nunca uses var" in s.context_summary()  # regla siempre presente
    assert s.search("secretos repositorio", "security")
    assert "docs-writer" in (proj / ".agentes/team.local.yaml").read_text()
    assert (proj / ".claude/agents/docs-writer.md").read_text().count("Generado por") == 1
    assert (proj / "src/pay.ts").exists() and (proj / "package.json").exists()  # el proyecto no se toca
    restore(proj, log=lambda *_: None)
    for p, txt in original.items():
        assert (proj / p).read_text() == txt
    assert "Nunca uses var" not in Store(proj, use_vectors=False).context_summary()


def test_token_savings(proj):
    import os
    from agentes.installer import set_ides
    (proj / ".kiroignore").write_text("secretos/\n")
    (proj / ".agentes").mkdir(exist_ok=True)
    (proj / ".agentes/team.local.yaml").write_text("kiro:\n  economy_model: modelo-barato\n")
    set_ides(proj, ["kiro"])
    sync(proj)
    ki = (proj / ".kiroignore").read_text()
    assert ki.startswith("secretos/") and "node_modules/" in ki and "!.env.example" in ki  # respeta líneas del usuario
    sync(proj)
    assert (proj / ".kiroignore").read_text().count("agentes:start") == 1
    wf = json.loads((proj / ".kiro/workflows/agentes-feature.workflow.json").read_text())
    txt = json.dumps(wf)
    assert '"economy"' not in txt and '"modelId": "modelo-barato"' in txt and '"effortLevel": "high"' in txt
    lite = json.loads((proj / ".kiro/workflows/agentes-feature-lite.workflow.json").read_text())
    assert [n.get("agent") for n in lite["steps"]][0] == "tech-lead"
    assert "write" in (proj / ".kiro/agents/tech-lead.md").read_text()  # escribe las specs
    uninstall(proj)
    assert (proj / ".kiroignore").read_text().strip() == "secretos/"

    # auto-recall selectivo y sin repetir en la sesión
    s = Store(proj, use_vectors=False)
    s.add("Los montos del checkout se guardan en centavos", "convention")
    s.add("El login usa magic links", "decision")
    sync(proj)

    def hook(prompt, sid="s1"):
        p = subprocess.run([sys.executable, "-m", "agentes", "hook", "prompt"], cwd=proj, capture_output=True, text=True,
                           input=json.dumps({"prompt": prompt, "session_id": sid, "cwd": str(proj)}),
                           env={**os.environ, "AGENTES_NO_VECTORS": "1"})
        return p.stdout
    assert hook("sí, continúa con eso por favor") == ""
    first = hook("agrega descuentos al checkout con montos en centavos")
    assert "centavos" in first and "magic" not in first
    assert hook("valida los montos del checkout en centavos") == ""      # ya inyectada en s1
    assert "centavos" in hook("agrega descuentos al checkout con montos en centavos", sid="s2")


def test_memory_search_compact(proj):
    import agentes.mcp_server as m
    s = Store(proj, use_vectors=False)
    body = "\n".join(f"const total{i} = computeTotal(order);" for i in range(80))
    s.add_many([{"text": f"// src/f{i}.ts:1\n{body}", "kind": "code", "source": f"src/f{i}.ts:1"} for i in range(10)])
    m._store = s
    out = m._search("computeTotal order", "code")
    assert out.count("[code]") == 5 and len(out) < 3500 and "src/f" in out
    assert len(m._search("computeTotal order", "code", full=True)) > len(out)


class CountingEF(FakeEF):
    calls = 0

    def __call__(self, input):
        CountingEF.calls += 1
        return super().__call__(input)


def test_vectores_selectivos_y_relleno(proj):
    pytest.importorskip("chromadb")
    s = Store(proj, embedding_function=FakeEF())
    s.add("los precios van en centavos", "convention")
    s.add_many([{"text": "// a.ts:1\nconst x = 1", "kind": "code", "source": "a.ts:1"},
                {"text": "// .kiro/specs/x/requirements.md:1\nEl usuario puede pagar", "kind": "spec", "source": "s:1"}])
    assert s.collection.count() == 2                      # memoria + spec; el código no se vectoriza
    assert s.search("const", "code")                      # el código se encuentra por BM25
    s2 = Store(proj, embedding_function=CountingEF())     # otro modelo → otra colección, se rellena sola
    s2._ef.name = lambda: "otro"
    assert s2.collection is not None and s2.collection.count() >= 2
    CountingEF.calls = 0
    s3 = Store(proj, embedding_function=CountingEF())
    s3.search("const x", "code")
    assert CountingEF.calls == 0                          # buscar código no carga el modelo
    s3.search("precios centavos", vectors=False)
    assert CountingEF.calls == 0


def test_bench(proj, tmp_path):
    from agentes import bench
    memories, cases = bench.builtin_cases()
    assert len(cases) == 2 * len(bench.DATASET) + len(bench.ENGLISH)
    res = bench.run(["bm25"], memories, cases)
    assert res[0]["por_tipo"]["literal"] > res[0]["por_tipo"]["paráfrasis"]  # BM25 falla con paráfrasis
    assert "Solo se pudo medir BM25" in bench.recommend(res + [{"modo": "multilingue", "error": "x"}])
    if pytest.importorskip("chromadb"):
        r = bench.run_mode("fake", memories, cases, ef=FakeEF())
        assert "error" not in r and 0 <= r["mrr"] <= 1
    s = Store(proj, use_vectors=False)
    s.add("Los montos se guardan en centavos", "convention")
    q = tmp_path / "q.yaml"
    q.write_text("- {query: '¿cómo guardamos el dinero?', expect: 'en centavos', tipo: parafrasis}\n"
                 "- {query: 'no existe', expect: 'zzz'}\n")
    mem, cs = bench.project_cases(proj, q)
    assert len(cs) == 1 and mem[cs[0]["expect"]].startswith("Los montos")


def test_triage_pesos():
    from agentes.triage import classify
    casos = {
        "corrige el typo en el botón de guardar": ("ajuste", "XS"),
        "cambia el color del header a azul": ("ajuste", "XS"),
        "el login no funciona cuando el correo tiene mayúsculas": ("fix", "S"),
        "el cupón no se aplica bien al total": ("fix", "S"),
        "agrega un campo de teléfono al formulario de registro": ("feature", "S"),
        "agrega un filtro por fecha a la lista de pedidos en la API y en la pantalla": ("feature", "M"),
        "actualiza react a la versión 19": ("update", "M"),
        "¿dónde se calcula el total del carrito?": ("pregunta", "XS"),
        "los pagos fallan a veces en producción con datos corruptos": ("fix", "L"),
        "implementa un sistema de roles y permisos para el panel de administración con base de datos": ("feature", "XL"),
    }
    for texto, esperado in casos.items():
        r = classify(texto)
        assert (r["tipo"], r["peso"]) == esperado, (texto, r)
    assert "workflow" in classify("cambia el texto del botón")["ruta"].lower()  # XS: explícitamente sin workflows
    assert "CONFIRMACIÓN" in classify("refactoriza el módulo de pagos")["ruta"]


def test_triage_codigo_y_hook(proj):
    import os
    from agentes.scanner import index_code, save_scan, scan
    (proj / "src/lib").mkdir(parents=True)
    (proj / "src/lib/pricing.ts").write_text("export function calculateTotal(items, coupon) {\n  // descuento cupón\n}\n")
    (proj / "src/components").mkdir()
    (proj / "src/components/CheckoutButton.tsx").write_text("export const CheckoutButton = () => <button>Pagar</button>;\n")
    s = Store(proj, use_vectors=False)
    save_scan(s, scan(proj))
    index_code(s, proj)
    ctx = s.context_summary()
    assert "Dónde está el código" in ctx and "src/lib/" in ctx and "componentes UI" in ctx
    from agentes.triage import render, triage
    r = triage(proj, "el descuento del cupón calcula mal el total", store=s)
    assert r["archivos"][0]["archivo"] == "src/lib/pricing.ts"
    assert "usuario indicó" in render(triage(proj, "arregla src/lib/pricing.ts", store=s))
    sync(proj)
    out = subprocess.run([sys.executable, "-m", "agentes", "hook", "prompt"], cwd=proj, capture_output=True, text=True,
                         input=json.dumps({"prompt": "/fix el descuento del cupón calcula mal el total", "cwd": str(proj)}),
                         env={**os.environ, "AGENTES_NO_VECTORS": "1"}).stdout
    assert "tipo=fix" in out and "src/lib/pricing.ts" in out
    import agentes.mcp_server as m
    m._store = s
    assert "pricing.ts" in m._locate("calculateTotal coupon") and "peso=" in m._triage("cambia el color del botón")


def test_kiro_sin_workflows_para_tareas_chicas(proj):
    from agentes.installer import set_ides
    set_ides(proj, ["kiro"])
    sync(proj)
    equipo = (proj / ".kiro/steering/agentes-equipo.md").read_text()
    assert "NO delegues" in equipo and "confirmación explícita" in equipo
    fix = (proj / ".kiro/steering/fix.md").read_text()
    assert "sin delegar ni lanzar workflows" in fix and "XS / S" in fix
