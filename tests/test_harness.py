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
    assert res["agents"] >= 9 and res["commands"] >= 14
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
