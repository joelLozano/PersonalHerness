"""`agentes bench`: compara la búsqueda por palabras clave (BM25) con la híbrida (BM25 + vectores) por modelo.

Mide sobre un conjunto en español (o tus propias preguntas) cuántas veces la memoria correcta aparece
primero (acierto@1) o entre las 3 primeras (acierto@3), el MRR, la latencia, el tiempo de carga del modelo
y los tokens que devolvería una búsqueda. Trabaja en carpetas temporales: no toca la memoria del proyecto.
"""
from __future__ import annotations

import re
import shutil
import tempfile
import time
from pathlib import Path

import yaml

from .store import Store

# (memoria, pregunta parafraseada sin las palabras clave de la memoria)
DATASET: list[tuple[str, str]] = [
    ("Los montos se guardan en centavos como enteros para evitar errores de redondeo.",
     "¿Cómo representamos el dinero para no perder precisión?"),
    ("Usamos Stripe Payment Intents para cobrar con tarjeta por la autenticación SCA.",
     "¿Con qué procesamos los pagos de los clientes?"),
    ("El login usa magic links que expiran en 15 minutos.",
     "¿Cómo entra la gente a su cuenta sin escribir clave?"),
    ("Las migraciones de base de datos se hacen con Prisma Migrate y deben ser reversibles.",
     "¿Qué herramienta modifica el esquema de las tablas?"),
    ("El color primario es #0F172A y el acento #22C55E; la tipografía es Inter.",
     "¿Qué paleta y fuente usa la interfaz?"),
    ("Las pruebas end-to-end se escriben con Playwright y corren en CI en cada pull request.",
     "¿Cómo verificamos los recorridos completos en el navegador?"),
    ("Los secretos se leen de variables de entorno; nunca se suben al repositorio.",
     "¿Dónde deben vivir las claves de API?"),
    ("Los commits siguen Conventional Commits (feat, fix, chore).",
     "¿Qué formato llevan los mensajes al registrar cambios en git?"),
    ("Las imágenes subidas se almacenan en S3 con URLs firmadas que caducan en una hora.",
     "¿Dónde guardamos los archivos que cargan los usuarios?"),
    ("La API devuelve los errores en formato RFC 7807 (problem+json).",
     "¿Qué estructura tienen las respuestas cuando algo falla?"),
    ("Las listas largas se paginan por cursor, nunca por offset.",
     "¿Cómo entregamos resultados extensos en partes?"),
    ("El despliegue es en Vercel para el frontend y Railway para el backend.",
     "¿En qué servicios publicamos la aplicación?"),
    ("Los correos transaccionales se envían con Resend y plantillas React Email.",
     "¿Cómo mandamos notificaciones por email?"),
    ("Las fechas se guardan en UTC y se convierten a la zona horaria del usuario en el cliente.",
     "¿Cómo manejamos los husos horarios?"),
    ("El estado global del frontend usa Zustand y los datos del servidor TanStack Query.",
     "¿Qué usamos para cachear información remota en la UI?"),
    ("Los logs son JSON estructurado con request_id para trazabilidad.",
     "¿Cómo seguimos el rastro de una petición en los registros?"),
    ("Las contraseñas se hashean con Argon2id.",
     "¿Qué algoritmo protege las claves de acceso almacenadas?"),
    ("El rate limiting de la API pública es de 100 peticiones por minuto por IP.",
     "¿Cuántas solicitudes puede hacer un cliente antes de ser bloqueado?"),
    ("Los textos de la UI se traducen con i18next en español e inglés.",
     "¿Cómo soportamos varios idiomas en las pantallas?"),
    ("Las tareas en segundo plano se procesan con BullMQ sobre Redis.",
     "¿Qué usamos para trabajos asíncronos y colas?"),
]
# preguntas en inglés sobre memorias en español: (índice de la memoria, pregunta)
ENGLISH: list[tuple[int, str]] = [
    (0, "How do we store money amounts?"), (1, "Which payment provider do we use?"),
    (6, "Where are API keys stored?"), (16, "How are passwords hashed?"),
    (13, "How do we handle time zones?"), (19, "What runs our background jobs?"),
]
DISTRACTORS = [
    "El README explica cómo levantar el entorno local con docker compose.",
    "Decidimos no soportar Internet Explorer.",
    "Los componentes de formulario validan con Zod en cliente y servidor.",
    "El equipo hace demo de avances cada viernes.",
    "Las variables de CSS siguen el prefijo --app-.",
    "El catálogo de productos se sincroniza cada noche desde el ERP.",
    "Los endpoints administrativos requieren rol admin.",
    "Usamos ESLint con la configuración recomendada y Prettier.",
    "Los feature flags se gestionan con un archivo JSON por entorno.",
    "El panel de métricas usa Grafana con datos de Prometheus.",
]
STOP = {"para", "como", "cómo", "con", "los", "las", "del", "que", "por", "una", "son", "sobre", "cada", "nunca", "deben"}
MODES_DEFAULT = ["bm25", "ingles", "multilingue"]


def literal_query(text: str) -> str:
    words = [w for w in re.findall(r"[\wáéíóúñ#-]+", text.lower()) if len(w) > 4 and w not in STOP]
    return " ".join(sorted(set(words), key=lambda w: (-len(w), w))[:3])


def builtin_cases() -> tuple[list[str], list[dict]]:
    memories = [m for m, _ in DATASET] + DISTRACTORS
    cases = []
    for i, (mem, para) in enumerate(DATASET):
        cases.append({"query": literal_query(mem), "expect": i, "tipo": "literal"})
        cases.append({"query": para, "expect": i, "tipo": "paráfrasis"})
    for i, q in ENGLISH:
        cases.append({"query": q, "expect": i, "tipo": "inglés"})
    return memories, cases


def project_cases(root: Path, queries_file: Path) -> tuple[list[str], list[dict]]:
    """Preguntas propias: YAML con [{query, expect: "fragmento literal de la memoria esperada", tipo?}]."""
    src = Store(root, use_vectors=False)
    memories = [r[0] for r in src.db.execute("SELECT text FROM memories WHERE kind NOT IN ('code','spec')")]
    raw = yaml.safe_load(queries_file.read_text(encoding="utf-8")) or []
    cases = []
    for c in raw:
        frag = str(c.get("expect", "")).lower()
        idx = next((i for i, m in enumerate(memories) if frag and frag in m.lower()), None)
        if idx is not None:
            cases.append({"query": c["query"], "expect": idx, "tipo": c.get("tipo", "proyecto")})
    return memories, cases


def run_mode(mode: str, memories: list[str], cases: list[dict], ef=None, k: int = 5) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="agentes-bench-"))
    try:
        vectors = mode != "bm25"
        st = Store(tmp, use_vectors=vectors, embedding_function=ef,
                   embedding_model=None if (ef is not None or not vectors) else mode)
        t0 = time.perf_counter()
        if vectors and st.collection is None:
            return {"modo": mode, "error": st._vector_error or "vectores no disponibles"}
        load = time.perf_counter() - t0
        t0 = time.perf_counter()
        ids = [st.add(m, "note") for m in memories]
        index_s = time.perf_counter() - t0
        hit1 = hit3 = rr = 0.0
        by_type: dict[str, list[int]] = {}
        lat, toks = [], []
        for c in cases:
            t0 = time.perf_counter()
            res = st.search(c["query"], None, k)
            lat.append((time.perf_counter() - t0) * 1000)
            got = [r["id"] for r in res]
            toks.append(sum(len(r["text"]) for r in res[:3]) / 4)
            target = ids[c["expect"]]
            rank = got.index(target) + 1 if target in got else 0
            hit1 += rank == 1
            hit3 += 0 < rank <= 3
            rr += 1 / rank if rank else 0
            by_type.setdefault(c["tipo"], []).append(int(0 < rank <= 3))
        n = len(cases) or 1
        return {"modo": mode, "modelo": st.model_label or ("-" if not vectors else "?"),
                "acierto@1": hit1 / n, "acierto@3": hit3 / n, "mrr": rr / n,
                "por_tipo": {t: sum(v) / len(v) for t, v in by_type.items()},
                "latencia_ms": sum(lat) / len(lat) if lat else 0, "carga_s": load, "indexado_s": index_s,
                "tokens_top3": sum(toks) / len(toks) if toks else 0}
    except Exception as e:  # modelo no descargable, dependencia faltante, etc.
        return {"modo": mode, "error": f"{type(e).__name__}: {e}"}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run(modes: list[str], memories: list[str], cases: list[dict], efs: dict | None = None) -> list[dict]:
    efs = efs or {}
    return [run_mode(m, memories, cases, efs.get(m)) for m in modes]


def recommend(results: list[dict]) -> str:
    ok = [r for r in results if "error" not in r]
    if not ok:
        return "Ningún modo pudo ejecutarse."
    best = max(ok, key=lambda r: r["mrr"])
    bm25 = next((r for r in ok if r["modo"] == "bm25"), None)
    if len(ok) == 1 and bm25:
        failed = ", ".join(r["modo"] for r in results if "error" in r)
        return (f"Solo se pudo medir BM25 ({failed} sin modelo: revisa tu conexión o instala con ./install.sh). "
                f"Sin vectores, las paráfrasis aciertan {bm25['por_tipo'].get('paráfrasis', 0):.0%} y las preguntas "
                f"en inglés {bm25['por_tipo'].get('inglés', 0):.0%}.")
    if bm25 and (best is bm25 or best["mrr"] - bm25["mrr"] < 0.05):
        return ("BM25 rinde prácticamente igual: usa `./install.sh --lite` (sin vectores), es más rápido y ligero.")
    para = best["por_tipo"].get("paráfrasis")
    para_b = bm25["por_tipo"].get("paráfrasis") if bm25 else None
    extra = f" Las paráfrasis pasan de {para_b:.0%} a {para:.0%} en acierto@3." if para is not None and para_b is not None else ""
    return (f"Usa `embedding_model: {best['modo']}` (MRR {best['mrr']:.2f} vs {bm25['mrr']:.2f} de BM25)." + extra
            if bm25 else f"Mejor modo: {best['modo']} (MRR {best['mrr']:.2f}).")


def table(results: list[dict]) -> str:
    tipos = sorted({t for r in results if "error" not in r for t in r["por_tipo"]})
    head = f"{'modo':20} {'acierto@1':>9} {'acierto@3':>9} {'MRR':>5} " + " ".join(f"{t[:10]:>10}" for t in tipos) \
        + f" {'latencia':>9} {'carga':>7} {'tokens':>7}"
    lines = [head, "-" * len(head)]
    for r in results:
        if "error" in r:
            lines.append(f"{r['modo']:20} no disponible: {r['error'][:90]}")
            continue
        lines.append(f"{r['modo']:20} {r['acierto@1']:>9.0%} {r['acierto@3']:>9.0%} {r['mrr']:>5.2f} "
                     + " ".join(f"{r['por_tipo'].get(t, 0):>10.0%}" for t in tipos)
                     + f" {r['latencia_ms']:>7.0f}ms {r['carga_s']:>6.1f}s {r['tokens_top3']:>7.0f}")
    lines.append("(columnas por tipo = acierto@3; tokens = lo que devuelven los 3 primeros resultados)")
    return "\n".join(lines)
