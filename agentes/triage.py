"""Triaje de tareas: tipo, peso, ruta recomendada y dónde buscar el código.

Es determinista (heurísticas + índice BM25 del código), no usa modelo ni gasta tokens de LLM. El hook
UserPromptSubmit lo añade a cada mensaje para que el orquestador elija la ruta más barata.

Pesos:
  XS  ajuste trivial (texto, estilo, una línea)          → directo en la sesión
  S   cambio acotado (1-3 archivos)                       → directo en la sesión + pruebas relacionadas
  M   varios archivos o una capa completa                 → plan breve en el chat; 1 sub-agente para verificar
  L   varias capas / decisiones de diseño / riesgo        → Spec + receta de workflow, con confirmación
  XL  sistema o módulo nuevo, migración grande            → dividir en entregas; Spec + workflows con confirmación
"""
from __future__ import annotations

import re
from collections import OrderedDict
from pathlib import Path

from .store import Store

WEIGHTS = ["XS", "S", "M", "L", "XL"]

# tipo -> (patrón, peso base). El orden importa: el primero que coincide gana (salvo pregunta).
TYPES: "OrderedDict[str, tuple[str, str]]" = OrderedDict([
    ("seguridad", (r"vulnerab|seguridad|security|owasp|audit|secreto|secret|inyecci|injection|xss|csrf|permisos? de acceso", "M")),
    ("fix", (r"\bbug|error|falla|fallo|\bfix|arregl|corrig|no funciona|not working|crash|excepci|exception|roto|broken|\b500\b|"
             r"undefined|null pointer|se cae|no carga|no guarda|no aparece|regresi|\bmal\b|incorrect|"
             r"no se (aplica|muestra|calcula|actualiza|env[ií]a|guarda|carga|ve)|deber[ií]a (dar|mostrar|ser)|sale (mal|vac[ií])|no responde|no hace nada|no reacciona|se queda (cargando|colgad)", "S")),
    ("issue", (r"\bissue|ticket|#\d+|reporte de|incidencia|jira", "S")),
    ("update", (r"actualiz|upgrade|\bbump|dependenc|versi[oó]n|migrar a |migra a |deprecad|deprecat|\bupdate\b|configur|\.env|ci/cd|pipeline", "S")),
    ("refactor", (r"refactor|reorganiz|limpi|extrae|extract|simplific|deuda t|renombra.*(m[oó]dulo|carpeta)|desacopl", "M")),
    ("test", (r"\bprueba|\btest|cobertura|coverage|e2e|unitari", "S")),
    ("docs", (r"document|readme|comentari|jsdoc|docstring|changelog", "XS")),
    ("ajuste", (r"typo|ortograf|texto|label|etiqueta|copy|mensaje|placeholder|color|margen|margin|padding|alinea|"
                r"tamaño de (letra|fuente)|icono|renombra|rename|tooltip|estilo", "XS")),
    ("feature", (r"agreg|añad|crea|implement|nuev[oa]|permit|soporte para|integra|\badd\b|\bbuild\b|\bnew\b|"
                 r"habilita|desarroll|construi|hacer que", "M")),
])
QUESTION = r"^(¿|qu[eé]\b|c[oó]mo\b|d[oó]nde\b|por qu[eé]\b|cu[aá]l|cu[aá]ndo|explica|expl[ií]came|what\b|how\b|where\b|why\b|which\b)"
UP = [  # señales que suben el peso
    r"\btod[oa]s? (el|la|los|las)\b|en todo el|global|completo|end.to.end|de punta a punta|todo el proyecto",
    r"m[oó]dulo|sistema|panel|dashboard|integraci[oó]n|pasarela|pagos|autenticaci[oó]n|\bauth|roles|permisos|multi.?tenant",
    r"base de datos|migraci[oó]n|esquema|schema|modelo de datos",
    r"producci[oó]n|intermitente|a veces|race|concurren|datos corrupt|p[eé]rdida de datos|rendimiento|performance",
    r"arquitectura|redise[nñ]|reescrib|rewrite|desde cero",
    r"a la versi[oó]n \d+|versi[oó]n mayor|major (version|upgrade)",
]
DOWN = r"peque[nñ]|solo|sólo|simple|r[aá]pid|un (bot[oó]n|campo|texto|color)|una (l[ií]nea|columna)|nada m[aá]s|typo|menor"
LAYERS = {"frontend": r"front|ui\b|pantalla|vista|componente|p[aá]gina|bot[oó]n|formulario|css|estilo",
          "backend": r"\bback|\bapi\b|endpoint|servidor|servicio|controlador|\brutas?\b",
          "datos": r"base de datos|\btablas?\b|migraci|esquema|\bmodelos?\b|\bquery\b|\bsql\b|prisma|\borm\b"}
FILE_RX = r"(?:#\S+|[\w./-]+\.(?:py|ts|tsx|js|jsx|vue|svelte|go|rs|java|kt|rb|php|cs|css|scss|html|sql|yaml|yml|json|md))\b"
STOP = {"para", "como", "cómo", "que", "qué", "con", "por", "una", "los", "las", "del", "este", "esta", "esto", "agrega",
        "agregar", "añade", "corrige", "arregla", "quiero", "necesito", "puedes", "favor", "hacer", "cuando", "donde",
        "dónde", "the", "and", "for", "with", "this", "that", "from", "error", "falla", "pantalla", "nuevo", "nueva"}

ROUTES = {
    "XS": "Resuélvelo TÚ directamente en esta sesión. Sin sub-agentes, sin Specs y sin workflows.",
    "S": "Directo en esta sesión: localiza, haz el cambio y ejecuta las pruebas relacionadas. Sin workflows; no delegues.",
    "M": "Plan breve en el chat → implementa tú (o 1 sub-agente) → 1 verificación con qa-engineer. "
         "Workflow `agentes-feature-lite` solo si el usuario lo pide.",
    "L": "Propón Quick Spec/Spec y la receta adecuada (agentes-feature / agentes-bugfix). PIDE CONFIRMACIÓN antes "
         "de lanzar cualquier workflow e indica el costo (~5-14 sesiones de agente).",
    "XL": "Divide en entregas M/L; propón Spec por entrega. Ningún workflow sin confirmación explícita del usuario.",
}
CMD_TYPE = {"fix": "fix", "feature": "feature", "implement": None, "plan": None, "design": "feature",
            "security": "seguridad", "test": "test"}


def _bump(w: str, n: int) -> str:
    return WEIGHTS[max(0, min(len(WEIGHTS) - 1, WEIGHTS.index(w) + n))]


def classify(text: str, hint: str | None = None) -> dict:
    low = text.lower().strip()
    reasons = []
    is_question = bool(re.search(QUESTION, low)) and not re.search(r"\b(agrega|corrige|arregla|implementa|crea|cambia)\b", low)
    tipo, base = None, "S"
    if hint:
        tipo, base = hint, TYPES.get(hint, ("", "S"))[1]
    elif re.search(r"typo|ortograf|errata", low):
        tipo, base = "ajuste", "XS"
    else:
        for t, (pat, w) in TYPES.items():
            if re.search(pat, low):
                tipo, base = t, w
                break
    if is_question and tipo in (None, "feature", "ajuste", "docs"):
        tipo, base = "pregunta", "XS"
    tipo = tipo or "tarea"
    weight = base
    ups = sum(1 for p in UP if re.search(p, low))
    layers = [k for k, p in LAYERS.items() if re.search(p, low)]
    if len(layers) >= 3 or (len(layers) == 2 and base in ("XS", "S")):
        ups += 1
        reasons.append("toca " + " + ".join(layers))
    if len(low) > 450:
        ups += 1
        reasons.append("descripción extensa")
    if ups:
        reasons.append(f"{ups} señal(es) de alcance")
    down = 1 if re.search(DOWN, low) else 0
    if down:
        reasons.append("pedido acotado")
    if tipo != "pregunta":
        weight = _bump(base, min(ups, 2) - down)
    if tipo in ("ajuste", "docs") and weight in ("L", "XL"):
        weight = "M"
    return {"tipo": tipo, "peso": weight, "razones": reasons, "ruta": ROUTES[weight] if tipo != "pregunta" else
            "Responde en esta sesión; usa code_locate si necesitas ver código. Sin sub-agentes."}


def locate(store: Store, text: str, k: int = 5) -> list[dict]:
    """Archivos más probables según el índice BM25 del código (y specs). No carga modelos."""
    words = [w for w in re.findall(r"[a-záéíóúñ_][\wáéíóúñ]{2,}", text.lower()) if w not in STOP]
    if not words:
        return []
    ids = store._fts(" ".join(words), ["code", "spec"], 40)
    if not ids:
        return []
    rows = {r[0]: r[1] for r in store.db.execute(
        f"SELECT id, source FROM memories WHERE id IN ({','.join('?' * len(ids))})", ids)}
    files: "OrderedDict[str, dict]" = OrderedDict()
    for rank, mid in enumerate(ids):
        src = rows.get(mid, "")
        path, _, line = src.rpartition(":")
        if not path:
            path, line = src, "1"
        f = files.setdefault(path, {"archivo": path, "lineas": [], "score": 0.0})
        f["score"] += 1.0 / (1 + rank)
        if line and len(f["lineas"]) < 3:
            f["lineas"].append(line)
    ranked = sorted(files.values(), key=lambda f: -f["score"])
    top = ranked[0]["score"] if ranked else 0
    return [f for f in ranked if f["score"] >= top * 0.4][:k]  # descarta coincidencias débiles


def triage(root: Path | str | None, text: str, hint: str | None = None, store: Store | None = None) -> dict:
    res = classify(text, hint)
    explicit = re.findall(FILE_RX, text)
    if explicit:
        res["archivos"] = []
        res["archivos_usuario"] = explicit[:6]
    else:
        st = store or Store(root, use_vectors=False)
        res["archivos"] = locate(st, text)
        n = len(res["archivos"])
        # muchos archivos relevantes dispersos en módulos distintos → probablemente más alcance
        dirs = {str(Path(f["archivo"]).parent) for f in res["archivos"]}
        if res["tipo"] not in ("pregunta", "ajuste", "docs") and n >= 5 and len(dirs) >= 4 and res["peso"] in ("XS", "S"):
            res["peso"] = _bump(res["peso"], 1)
            res["ruta"] = ROUTES[res["peso"]]
            res["razones"].append("código relevante disperso en varios módulos")
    return res


def render(res: dict) -> str:
    lines = [f"Triaje agentes: tipo={res['tipo']} · peso={res['peso']}"
             + (f" ({'; '.join(res['razones'])})" if res.get("razones") else ""),
             f"Ruta: {res['ruta']}"]
    if res.get("archivos_usuario"):
        lines.append("Código: el usuario indicó " + ", ".join(res["archivos_usuario"]) + " — empieza por ahí.")
    elif res.get("archivos"):
        lines.append("Código probable (lee solo estos rangos primero): " + ", ".join(
            f"{f['archivo']}:{','.join(f['lineas'])}" for f in res["archivos"]))
    lines.append("Si el usuario indica otro alcance, su criterio manda.")
    return "\n".join(lines)
