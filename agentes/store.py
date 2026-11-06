"""Almacén de memoria del harness.

Una sola base por proyecto en `.agentes/`:
  - agentes.db  -> SQLite: memorias (+ índice FTS5/BM25), perfil, tareas, archivos indexados
  - vectors/    -> ChromaDB (base vectorial) si está instalada

La búsqueda es híbrida: semántica (vectores) + palabras clave (BM25), fusionadas con
Reciprocal Rank Fusion. Si ChromaDB no está disponible, funciona solo con BM25.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

HARNESS_DIR = ".agentes"

KINDS = {
    "rule": "Reglas obligatorias del proyecto (se inyectan siempre en el contexto)",
    "profile": "Respuestas del kickoff / contexto del proyecto",
    "decision": "Decisiones técnicas o de producto (ADR ligero)",
    "convention": "Convenciones de código, estilo, nombres, estructura",
    "design": "Sistema de diseño: colores, tipografía, componentes",
    "requirement": "Requisitos, historias de usuario, criterios de aceptación",
    "bug": "Bugs encontrados y su causa raíz",
    "security": "Hallazgos y políticas de seguridad",
    "learning": "Aprendizajes / gotchas del proyecto",
    "scan": "Resultados del análisis automático del proyecto",
    "code": "Fragmentos de código indexados",
    "spec": "Specs de Kiro indexadas (.kiro/specs: requirements/design/tasks)",
    "note": "Notas generales",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    tags TEXT DEFAULT '',
    source TEXT DEFAULT '',
    agent TEXT DEFAULT '',
    hash TEXT UNIQUE,
    created_at REAL NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    text, tags, source, content='memories', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, text, tags, source) VALUES (new.id, new.text, new.tags, new.source);
END;
CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, text, tags, source)
    VALUES ('delete', old.id, old.text, old.tags, old.source);
END;
CREATE TABLE IF NOT EXISTS profile (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    section TEXT DEFAULT '',
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'todo',
    assignee TEXT DEFAULT '',
    priority TEXT DEFAULT 'media',
    parent_id INTEGER,
    feature TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY,
    hash TEXT NOT NULL,
    chunk_ids TEXT NOT NULL,
    indexed_at REAL NOT NULL
);
"""

TASK_STATUSES = ("todo", "doing", "review", "testing", "blocked", "done")


def find_root(start: str | os.PathLike | None = None) -> Path:
    """Sube directorios hasta encontrar `.agentes/`; si no, usa la raíz git o cwd."""
    p = Path(start or os.getcwd()).resolve()
    for d in [p, *p.parents]:
        if (d / HARNESS_DIR).is_dir():
            return d
    for d in [p, *p.parents]:
        if (d / ".git").exists():
            return d
    return p


def _hash(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:32]


class Store:
    def __init__(self, root: str | os.PathLike | None = None, use_vectors: bool | None = None,
                 embedding_function=None, embedding_model: str | None = None):
        self.root = find_root(root) if root is None else Path(root).resolve()
        self.dir = self.root / HARNESS_DIR
        self.dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.dir / "agentes.db")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()
        if use_vectors is None:
            use_vectors = embedding_function is not None or os.environ.get("AGENTES_NO_VECTORS") != "1"
        self._want_vectors = use_vectors
        self._ef = embedding_function
        self._model_req = embedding_model
        self.model_label = ""
        self._col = None
        self._vector_error: str | None = None

    # ------------------------------------------------------------------ vectores
    FAIL_TTL = 3600  # tras un fallo de carga del modelo, usar solo BM25 durante 1 hora (sin reintentos lentos)

    def _fail_marker(self) -> Path:
        return self.dir / "vectors-error.json"

    def _recent_failure(self, model: str) -> str | None:
        try:
            d = json.loads(self._fail_marker().read_text())
            if d.get("model") == model and time.time() - d.get("ts", 0) < self.FAIL_TTL:
                return d.get("error", "fallo reciente")
        except Exception:
            pass
        return None

    def clear_vector_failure(self) -> None:
        try:
            self._fail_marker().unlink()
        except OSError:
            pass

    @property
    def collection(self):
        if self._col is None and self._want_vectors and self._vector_error is None:
            model_key = "personalizado" if self._ef is not None else (self._embedding_model_name() or "multilingue")
            recent = None if self._ef is not None else self._recent_failure(model_key)
            if recent:
                self._vector_error = f"{recent} (reintento automático en <1 h; fuerza con `agentes memory rebuild`)"
                return None
            try:
                import chromadb  # type: ignore
                from chromadb.config import Settings  # type: ignore

                client = self._client = chromadb.PersistentClient(
                    path=str(self.dir / "vectors"),
                    settings=Settings(anonymized_telemetry=False),
                )
                from .embeddings import collection_name, make_ef
                if self._ef is not None:
                    ef, label = self._ef, "personalizado"
                else:
                    ef, label = make_ef(self._embedding_model_name())
                self.model_label = label
                kw = {"embedding_function": ef} if ef is not None else {}
                col = client.get_or_create_collection(collection_name(label), metadata={"hnsw:space": "cosine"}, **kw)
                col._embedding_function(["ping"])  # verifica que el modelo de embeddings funcione
                self._col = col
                self._backfill()
                self.clear_vector_failure()
            except Exception as e:  # sin chromadb o sin modelo de embeddings
                self._disable_vectors(e)
                if self._ef is None and not isinstance(e, ImportError):
                    try:
                        self._fail_marker().write_text(json.dumps(
                            {"model": model_key, "ts": time.time(), "error": self._vector_error}))
                    except OSError:
                        pass
        return self._col

    def _embedding_model_name(self) -> str:
        if self._model_req:
            return self._model_req
        if os.environ.get("AGENTES_EMBEDDING_MODEL"):
            return os.environ["AGENTES_EMBEDDING_MODEL"]
        try:
            from .installer import load_team
            return load_team(self.root).get("settings", {}).get("embedding_model") or ""
        except Exception:
            return ""

    def _backfill(self) -> None:
        """Al estrenar un modelo (colección vacía) vectoriza las memorias existentes (no el código)."""
        col = self._col
        if col is None or col.count() > 0:
            return
        rows = [dict(r) for r in self.db.execute(
            "SELECT id,kind,text,tags,source FROM memories WHERE kind != 'code'")]
        for i in range(0, len(rows), 100):
            b = rows[i:i + 100]
            col.upsert(ids=[str(r["id"]) for r in b], documents=[r["text"] for r in b],
                       metadatas=[{"kind": r["kind"], "source": r["source"] or "", "tags": r["tags"] or ""} for r in b])

    def _disable_vectors(self, e: Exception) -> None:
        self._vector_error = f"{type(e).__name__}: {str(e)[:200]}"
        self._col = None
        try:
            (self.dir / "vectors.log").write_text(self._vector_error + "\n")
        except OSError:
            pass

    def vector_status(self) -> str:
        col = self.collection
        if col is not None:
            return f"chromadb OK · modelo {self.model_label} · {col.count()} vectores (el código usa solo BM25)"
        return f"desactivado ({self._vector_error or 'AGENTES_NO_VECTORS=1'}) -> solo BM25"

    # ------------------------------------------------------------------ memorias
    def add(self, text: str, kind: str = "note", tags: str | list[str] = "", source: str = "",
            agent: str = "", _vector: bool = True) -> int | None:
        text = (text or "").strip()
        if not text:
            return None
        if isinstance(tags, list):
            tags = ",".join(tags)
        h = _hash(kind, text, source)
        cur = self.db.execute(
            "INSERT OR IGNORE INTO memories(kind,text,tags,source,agent,hash,created_at) VALUES (?,?,?,?,?,?,?)",
            (kind, text, tags, source, agent, h, time.time()),
        )
        self.db.commit()
        if cur.rowcount == 0:
            row = self.db.execute("SELECT id FROM memories WHERE hash=?", (h,)).fetchone()
            return row["id"] if row else None
        mid = cur.lastrowid
        if _vector and kind != "code" and self.collection is not None:
            try:
                self.collection.upsert(
                    ids=[str(mid)], documents=[text],
                    metadatas=[{"kind": kind, "source": source or "", "tags": tags or ""}],
                )
            except Exception as e:
                self._disable_vectors(e)
        return mid

    def add_many(self, items: list[dict]) -> list[int]:
        """Inserción masiva (usada por el indexador de código)."""
        ids, vids, docs, metas = [], [], [], []
        now = time.time()
        for it in items:
            text = it["text"].strip()
            if not text:
                continue
            kind, source, tags = it.get("kind", "note"), it.get("source", ""), it.get("tags", "")
            h = _hash(kind, text, source)
            cur = self.db.execute(
                "INSERT OR IGNORE INTO memories(kind,text,tags,source,agent,hash,created_at) VALUES (?,?,?,?,?,?,?)",
                (kind, text, tags, source, it.get("agent", ""), h, now),
            )
            mid = cur.lastrowid if cur.rowcount else self.db.execute(
                "SELECT id FROM memories WHERE hash=?", (h,)).fetchone()["id"]
            ids.append(mid)
            if kind != "code":  # el código se busca con BM25 (exacto); los vectores son para lenguaje natural
                vids.append(mid)
                docs.append(text)
                metas.append({"kind": kind, "source": source, "tags": tags})
        self.db.commit()
        if vids and self.collection is not None:
            try:
                for i in range(0, len(vids), 200):
                    self.collection.upsert(ids=[str(x) for x in vids[i:i + 200]],
                                           documents=docs[i:i + 200], metadatas=metas[i:i + 200])
            except Exception as e:
                self._disable_vectors(e)
        return ids

    def delete(self, ids: list[int]) -> int:
        if not ids:
            return 0
        q = ",".join("?" * len(ids))
        n = self.db.execute(f"DELETE FROM memories WHERE id IN ({q})", ids).rowcount
        self.db.commit()
        if self.collection is not None:
            try:
                self.collection.delete(ids=[str(i) for i in ids])
            except Exception:
                pass
        return n

    def _fts(self, query: str, kinds: list[str] | None, k: int) -> list[int]:
        terms = [t for t in "".join(c if c.isalnum() or c in "_-." else " " for c in query).split() if len(t) > 1]
        if not terms:
            return []
        match = " OR ".join(f'"{t}"' for t in terms)
        sql = ("SELECT m.id FROM memories_fts f JOIN memories m ON m.id=f.rowid "
               "WHERE memories_fts MATCH ?")
        args: list[Any] = [match]
        if kinds:
            sql += f" AND m.kind IN ({','.join('?' * len(kinds))})"
            args += kinds
        sql += " ORDER BY bm25(memories_fts) LIMIT ?"
        args.append(k)
        try:
            return [r[0] for r in self.db.execute(sql, args)]
        except sqlite3.OperationalError:
            return []

    def _vec(self, query: str, kinds: list[str] | None, k: int) -> list[int]:
        if kinds and all(x == "code" for x in kinds):
            return []  # el código no se vectoriza: no cargar el modelo
        col = self.collection
        if col is None or col.count() == 0:
            return []
        where = None
        if kinds:
            where = {"kind": kinds[0]} if len(kinds) == 1 else {"kind": {"$in": kinds}}
        try:
            res = col.query(query_texts=[query], n_results=min(k, col.count()), where=where)
            return [int(x) for x in res["ids"][0]]
        except Exception as e:
            self._disable_vectors(e)
            return []

    def search(self, query: str, kinds: list[str] | str | None = None, k: int = 8,
               vectors: bool = True) -> list[dict]:
        if isinstance(kinds, str):
            kinds = [x.strip() for x in kinds.split(",") if x.strip()]
        pool = max(k * 3, 20)
        scores: dict[int, float] = {}
        vec = self._vec(query, kinds, pool) if vectors else []
        fts = self._fts(query, kinds, pool)
        for ranking in (vec, fts):
            for rank, mid in enumerate(ranking):
                scores[mid] = scores.get(mid, 0.0) + 1.0 / (60 + rank)
        vec_top = set(vec[: max(3, k)])
        best = sorted(scores, key=scores.get, reverse=True)[:k]
        if not best:
            return []
        rows = {r["id"]: dict(r) for r in self.db.execute(
            f"SELECT id,kind,text,tags,source,agent,created_at FROM memories WHERE id IN ({','.join('?' * len(best))})",
            best)}
        out = []
        for mid in best:
            if mid in rows:
                r = rows[mid]
                r["score"] = round(scores[mid] * 1000, 2)
                r["match"] = "both" if (mid in vec and mid in fts) else ("vec" if mid in vec else "fts")
                r["vec_top"] = mid in vec_top
                out.append(r)
        return out

    def list(self, kind: str | None = None, limit: int = 50) -> list[dict]:
        if kind:
            cur = self.db.execute("SELECT * FROM memories WHERE kind=? ORDER BY id DESC LIMIT ?", (kind, limit))
        else:
            cur = self.db.execute("SELECT * FROM memories WHERE kind NOT IN ('code','spec') ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in cur]

    def stats(self) -> dict:
        kinds = {r[0]: r[1] for r in self.db.execute("SELECT kind, COUNT(*) FROM memories GROUP BY kind")}
        tasks = {r[0]: r[1] for r in self.db.execute("SELECT status, COUNT(*) FROM tasks GROUP BY status")}
        return {
            "root": str(self.root),
            "memories": kinds,
            "profile_keys": self.db.execute("SELECT COUNT(*) FROM profile").fetchone()[0],
            "tasks": tasks,
            "indexed_files": self.db.execute("SELECT COUNT(*) FROM files").fetchone()[0],
            "vectors": self.vector_status(),
        }

    # ------------------------------------------------------------------ perfil
    def profile_set(self, key: str, value: str, section: str = "") -> None:
        self.db.execute(
            "INSERT INTO profile(key,value,section,updated_at) VALUES (?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, section=COALESCE(NULLIF(excluded.section,''),profile.section), updated_at=excluded.updated_at",
            (key, str(value), section, time.time()),
        )
        self.db.commit()
        # también se guarda como memoria buscable
        self.add(f"{key}: {value}", kind="profile", tags=section, source="profile")

    def profile_get(self, key: str | None = None) -> dict:
        if key:
            r = self.db.execute("SELECT * FROM profile WHERE key=?", (key,)).fetchone()
            return dict(r) if r else {}
        out: dict[str, dict] = {}
        for r in self.db.execute("SELECT key,value,section FROM profile ORDER BY section,key"):
            out.setdefault(r["section"] or "general", {})[r["key"]] = r["value"]
        return out

    # ------------------------------------------------------------------ tareas
    def task_create(self, title: str, description: str = "", assignee: str = "", priority: str = "media",
                    parent_id: int | None = None, feature: str = "") -> int:
        now = time.time()
        cur = self.db.execute(
            "INSERT INTO tasks(title,description,assignee,priority,parent_id,feature,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (title, description, assignee, priority, parent_id, feature, now, now),
        )
        self.db.commit()
        return cur.lastrowid

    def task_update(self, task_id: int, **fields) -> dict:
        allowed = {"title", "description", "status", "assignee", "priority", "feature", "notes"}
        fields = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if "status" in fields and fields["status"] not in TASK_STATUSES:
            raise ValueError(f"status inválido; usa uno de {TASK_STATUSES}")
        if "notes" in fields:
            old = self.db.execute("SELECT notes FROM tasks WHERE id=?", (task_id,)).fetchone()
            prev = old["notes"] if old else ""
            fields["notes"] = (prev + "\n" if prev else "") + f"[{time.strftime('%Y-%m-%d %H:%M')}] {fields['notes']}"
        if fields:
            sets = ",".join(f"{k}=?" for k in fields)
            self.db.execute(f"UPDATE tasks SET {sets}, updated_at=? WHERE id=?",
                            [*fields.values(), time.time(), task_id])
            self.db.commit()
        r = self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return dict(r) if r else {}

    def task_list(self, status: str | None = None, feature: str | None = None, include_done: bool = False) -> list[dict]:
        sql, args = "SELECT * FROM tasks WHERE 1=1", []
        if status:
            sql += " AND status=?"
            args.append(status)
        elif not include_done:
            sql += " AND status!='done'"
        if feature:
            sql += " AND feature=?"
            args.append(feature)
        sql += " ORDER BY CASE priority WHEN 'alta' THEN 0 WHEN 'media' THEN 1 ELSE 2 END, id"
        return [dict(r) for r in self.db.execute(sql, args)]

    # ------------------------------------------------------------------ contexto
    def context_summary(self, max_chars: int = 6000) -> str:
        """Resumen compacto que se inyecta al iniciar cada sesión."""
        parts = []
        rules = list(reversed(self.list("rule", 60)))
        if rules:
            budget, lines = 2500, []
            for r in rules:
                t = r["text"].strip().replace("\n", " ")[:400]
                if budget - len(t) < 0:
                    lines.append("- (más reglas: usa memory_search con kinds='rule')")
                    break
                budget -= len(t)
                lines.append(f"- {t}")
            parts.append("## Reglas obligatorias\n" + "\n".join(lines))
        cmap = self.db.execute("SELECT text FROM memories WHERE kind='scan' AND tags='mapa' ORDER BY id DESC LIMIT 1").fetchone()
        prof = self.profile_get()
        if prof:
            lines = []
            for section, kv in prof.items():
                lines.append(f"[{section}] " + "; ".join(f"{k}={v}" for k, v in kv.items()))
            parts.append("## Perfil del proyecto\n" + "\n".join(lines))
        else:
            parts.append("## Perfil del proyecto\n(vacío) -> ejecuta /kickoff (proyecto nuevo) o /onboard (existente)")
        if cmap:
            parts.append("## Dónde está el código\n" + cmap[0].split("\n", 1)[-1][:1000]
                         + "\n(Si no te indican archivos: usa la herramienta code_locate antes de explorar.)")
        for kind, title, n in (("scan", "Stack y comandos detectados", 10), ("decision", "Decisiones recientes", 6), ("convention", "Convenciones", 8),
                               ("design", "Diseño", 5), ("learning", "Aprendizajes", 5)):
            rows = [r for r in self.list(kind, n + 1) if r.get("tags") != "mapa"][:n]
            if rows:
                parts.append(f"## {title}\n" + "\n".join(f"- {r['text'][:220]}" for r in rows))
        tasks = self.task_list()
        if tasks:
            parts.append("## Tareas abiertas\n" + "\n".join(
                f"- #{t['id']} [{t['status']}] {t['title']} ({t['assignee'] or 'sin asignar'})" for t in tasks[:12]))
        text = "\n\n".join(parts)
        return text[:max_chars]

    # ------------------------------------------------------------------ export / import
    def export(self) -> dict:
        return {
            "memories": [dict(r) for r in self.db.execute(
                "SELECT kind,text,tags,source,agent,created_at FROM memories WHERE kind NOT IN ('code','spec')")],
            "profile": [dict(r) for r in self.db.execute("SELECT key,value,section FROM profile")],
            "tasks": [dict(r) for r in self.db.execute("SELECT * FROM tasks")],
        }

    def import_(self, data: dict) -> dict:
        n = 0
        for p in data.get("profile", []):
            self.profile_set(p["key"], p["value"], p.get("section", ""))
        for m in data.get("memories", []):
            if m["kind"] != "profile" and self.add(m["text"], m["kind"], m.get("tags", ""), m.get("source", ""), m.get("agent", "")):
                n += 1
        existing = {r[0] for r in self.db.execute("SELECT title FROM tasks")}
        t = 0
        for task in data.get("tasks", []):
            if task["title"] not in existing:
                tid = self.task_create(task["title"], task.get("description", ""), task.get("assignee", ""),
                                       task.get("priority", "media"), None, task.get("feature", ""))
                self.task_update(tid, status=task.get("status", "todo"))
                t += 1
        return {"memories": n, "tasks": t}

    def rebuild_vectors(self) -> int:
        self.clear_vector_failure()
        self._vector_error = None
        """Re-genera la base vectorial desde SQLite (tras cambiar modelo o corrupción)."""
        if self.collection is None:
            return 0
        self._client.delete_collection(self._col.name)
        self._col = None
        col = self.collection  # se recrea vacía y _backfill la llena
        return col.count() if col is not None else 0


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)
