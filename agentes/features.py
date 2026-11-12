"""Índice de símbolos y catálogo de features por capas (determinista, sin modelo).

- `extract(rel, text)`: tipos y funciones públicas de Swift, Kotlin, Java, TS/JS y Python con su línea.
- Cada símbolo recibe una capa (UI, presentación, dominio, datos, DI) por la ruta o el sufijo del nombre y una
  feature (carpeta `Features/<X>`, módulo Gradle `feature/<x>` o, si no hay, el prefijo del tipo: CheckoutViewModel →
  Checkout).
- `catalog(store)`: una línea por feature con las capas presentes, ejemplos de tipos y las capas que faltan. Se
  guarda como memoria `scan` (tags=features) y entra en el contexto de cada sesión y en el triaje.
"""
from __future__ import annotations

import re
from collections import Counter, OrderedDict, defaultdict

SYMBOLS_VERSION = "1"

_MODS = r"(?:(?:public|open|internal|private|fileprivate|final|abstract|sealed|data|enum|inner|value|annotation|" \
        r"export|default|static|override|indirect|@MainActor|@Observable|@objc(?:\(\w+\))?)\s+)*"
PATTERNS: dict[str, list[tuple[str, re.Pattern]]] = {
    "swift": [("tipo", re.compile(rf"^\s*{_MODS}(class|struct|enum|protocol|actor)\s+([A-Z]\w*)", re.M))],
    "kotlin": [("tipo", re.compile(rf"^\s*{_MODS}(class|interface|object|fun interface)\s+([A-Z]\w*)", re.M)),
               ("composable", re.compile(r"@Composable\s+(?:(?:public|internal|private)\s+)?fun\s+()([A-Z]\w*)"))],
    "java": [("tipo", re.compile(rf"^\s*{_MODS}(class|interface|enum|record)\s+([A-Z]\w*)", re.M))],
    "ts": [("tipo", re.compile(r"^\s*export\s+(?:default\s+)?(?:abstract\s+)?(class|interface|type|enum)\s+([A-Z]\w*)", re.M)),
           ("función", re.compile(r"^\s*export\s+(?:default\s+)?(?:async\s+)?(function|const)\s+([A-Za-z]\w*)", re.M))],
    "python": [("tipo", re.compile(r"^(class)\s+([A-Z]\w*)", re.M))],
}
EXT_LANG = {".swift": "swift", ".kt": "kotlin", ".kts": None, ".java": "java", ".ts": "ts", ".tsx": "ts",
            ".js": "ts", ".jsx": "ts", ".vue": "ts", ".svelte": "ts", ".py": "python"}
PLATFORM = {"swift": "ios", "kotlin": "android", "java": "android"}

LAYERS = ["UI", "presentación", "dominio", "datos", "DI"]
# (capa, regex de carpeta, regex de sufijo del nombre). La carpeta manda sobre el sufijo.
LAYER_RULES = [
    ("DI", r"/(di|injection|dependencies|assembly|assemblies)/", r"(Module|Component|Container|Assembly|Injector|DependencyContainer)$"),
    ("dominio", r"/(domain|usecases?|use-cases?|interactors?|entities)/", r"(UseCase|UseCases|Interactor)$"),
    ("datos", r"/(data|repositor(y|ies)|datasources?|network(ing)?|remote|local|persistence|storage|api|dto|mappers?|db|database|dao)/",
     r"(Repository|RepositoryImpl|DataSource|Dao|Api|ApiService|Service|Client|Mapper|Dto|DTO|Request|Response|Entity|Store(?<!ViewStore))$"),
    ("presentación", r"/(presentation|viewmodels?|presenters?|coordinators?|routers?|navigation)/",
     r"(ViewModel|Presenter|Reducer|Coordinator|Router|Feature|Navigator|UiState|ViewState)$"),
    ("UI", r"/(ui|views?|screens?|scenes?|components?|widgets?|compose|pages?)/",
     r"(View|Screen|ViewController|Controller|Activity|Fragment|Page|Cell|Dialog|Sheet|Content|Component)$"),
]
SUFFIX_RX = re.compile(r"(ViewModel|ViewController|ViewState|UiState|RepositoryImpl|Repository|DataSource|UseCase|UseCases|"
                       r"Interactor|Presenter|Coordinator|Router|Reducer|Screen|View|Activity|Fragment|Page|Cell|Dialog|"
                       r"Sheet|Content|Component|Dao|ApiService|Api|Service|Client|Mapper|Dto|DTO|Module|Assembly|"
                       r"Container|Request|Response|Entity|Navigator|Feature|Controller)$")
FEATURE_DIRS = {"features", "feature", "modules", "module", "scenes", "flows", "screens"}
SKIP_PATH = re.compile(r"(^|/)(tests?|__tests__|androidTest|testDebug|UITests|\w+Tests|spec|specs|e2e|build|"
                       r"Preview Content|fixtures?|mocks?)(/|$)|Tests?\.(swift|kt|java)$|\.(test|spec)\.[jt]sx?$", re.I)
DS_RX = re.compile(r"(^|/)(design-?system|ds|ui-?kit|core-?ui|ui-?components)(/|$)", re.I)
GENERIC = {"App", "Main", "Base", "Default", "Common", "Core", "Root"}


def extract(rel: str, text: str) -> list[dict]:
    """Símbolos de un archivo: [{name, kind, line, layer, feature, platform}]. Vacío para tests y otros lenguajes."""
    ext = "." + rel.rsplit(".", 1)[-1].lower() if "." in rel else ""
    lang = EXT_LANG.get(ext)
    if not lang or SKIP_PATH.search(rel):
        return []
    out, seen = [], set()
    for kind, rx in PATTERNS[lang]:
        for m in rx.finditer(text):
            name = m.group(2)
            if name in seen or len(name) < 3:
                continue
            seen.add(name)
            line = text.count("\n", 0, m.start(2)) + 1
            out.append({"name": name, "kind": (m.group(1) or kind).strip(), "line": line,
                        "layer": layer_of(rel, name), "platform": PLATFORM.get(lang, "web" if lang == "ts" else lang)})
    feat = feature_of(rel, [s["name"] for s in out])
    for s in out:
        s["feature"] = feat
    return out


def layer_of(rel: str, name: str) -> str:
    path = "/" + rel.lower().rsplit("/", 1)[0] + "/"
    for layer, dir_rx, _ in LAYER_RULES:
        if re.search(dir_rx, path):
            return layer
    for layer, _, suf in LAYER_RULES:
        if re.search(suf, name):
            return layer
    return ""


def _stem(name: str) -> str:
    prev = None
    while prev != name:
        prev, name = name, SUFFIX_RX.sub("", name)
    return name


def feature_of(rel: str, names: list[str]) -> str:
    parts = rel.split("/")
    for i, seg in enumerate(parts[:-1]):
        if seg.lower() in FEATURE_DIRS and i + 1 < len(parts) - 1:
            nxt = parts[i + 1]
            if nxt not in ("src", "Sources", "main"):
                return nxt[:1].upper() + nxt[1:]
    for n in names:  # sin carpeta de feature: el prefijo del tipo con sufijo de capa (CheckoutViewModel -> Checkout)
        if SUFFIX_RX.search(n):
            stem = _stem(n)
            if len(stem) >= 3 and stem not in GENERIC:
                return stem
    return ""


def save(store, rel: str, syms: list[dict]) -> None:
    store.db.execute("DELETE FROM symbols WHERE path=?", (rel,))
    if syms:
        store.db.executemany(
            "INSERT INTO symbols(name,kind,path,line,layer,feature,platform) VALUES (?,?,?,?,?,?,?)",
            [(s["name"], s["kind"], rel, s["line"], s["layer"], s["feature"], s["platform"]) for s in syms])


def catalog(store, ds_paths: list[str] | None = None, max_features: int = 25) -> list[str]:
    """Una línea por feature y plataforma: capas presentes (con ejemplos), carpeta y capas que faltan."""
    rows = store.db.execute("SELECT name, path, layer, feature, platform FROM symbols WHERE feature != ''").fetchall()
    ds_paths = [p.rstrip("/") + "/" for p in (ds_paths or []) if p]
    groups: "OrderedDict[tuple[str, str], dict]" = OrderedDict()
    for name, path, layer, feat, plat in rows:
        if any(path.startswith(p) for p in ds_paths) or DS_RX.search(path):
            continue  # el design system tiene su propio catálogo
        g = groups.setdefault((feat, plat), {"layers": defaultdict(list), "files": set(), "dirs": Counter()})
        g["files"].add(path)
        g["dirs"][path.rsplit("/", 1)[0] if "/" in path else "."] += 1
        if layer and name not in g["layers"][layer]:
            g["layers"][layer].append(name)
    # primero las features con más archivos; las de un solo archivo van al final (y se cortan primero)
    items = list(groups.items())
    items.sort(key=lambda kv: (-len(kv[1]["files"]), -len(kv[1]["layers"]), kv[0][0]))
    layered = any("dominio" in g["layers"] or "datos" in g["layers"] for _, g in items)
    lines = []
    for (feat, plat), g in items[:max_features]:
        parts = []
        for layer in LAYERS:
            names = sorted(g["layers"].get(layer, []), key=len)
            if names:
                more = f" +{len(names) - 3}" if len(names) > 3 else ""
                parts.append(f"{layer}: {', '.join(names[:3])}{more}")
        missing = [l for l in ("UI", "presentación", "dominio", "datos") if l not in g["layers"]]
        top_dir = _common_dir(list(g["dirs"]))
        line = f"- {feat} [{plat}] {top_dir} — " + (" · ".join(parts) or "sin capas reconocibles")
        if missing and layered and len(missing) < 4:
            line += f" (sin {', '.join(missing)})"
        lines.append(line)
    if len(items) > max_features:
        lines.append(f"- (+{len(items) - max_features} features más: usa code_locate)")
    return lines


def _common_dir(dirs: list[str]) -> str:
    if not dirs:
        return ""
    split = [d.split("/") for d in dirs]
    common = []
    for segs in zip(*split):
        if len(set(segs)) != 1:
            break
        common.append(segs[0])
    d = "/".join(common) or dirs[0]
    # rutas de paquetes Android muy profundas: acorta el medio
    segs = d.split("/")
    if len(segs) > 6:
        d = "/".join(segs[:2] + ["…"] + segs[-2:])
    return d + "/"


def lookup(store, words: list[str], k: int = 8) -> list[dict]:
    """Símbolos cuyo nombre coincide con alguna palabra (exacta = 2, prefijo = 1). Para code_locate y el triaje."""
    hits: dict[tuple[str, int], dict] = {}
    for w in words:
        if len(w) < 4:
            continue
        for name, path, line, feat in store.db.execute(
                "SELECT name, path, line, feature FROM symbols WHERE name LIKE ? ESCAPE '\\' LIMIT 40",
                (w.replace("_", "\\_") + "%",)):
            score = 2.0 if name.lower() == w.lower() else (1.2 if feat.lower() == w.lower() else 0.8)
            key = (path, line)
            if key not in hits or hits[key]["score"] < score:
                hits[key] = {"name": name, "path": path, "line": line, "score": score}
    return sorted(hits.values(), key=lambda h: -h["score"])[:k]


def features_in(store, text: str) -> list[str]:
    """Nombres de features del catálogo mencionados en el texto (checkout -> Checkout)."""
    low = text.lower()
    names = {r[0] for r in store.db.execute("SELECT DISTINCT feature FROM symbols WHERE feature != ''")}
    found = []
    for n in names:
        nl = n.lower()
        if len(nl) >= 4 and re.search(rf"\b{re.escape(nl)}(s|es)?\b", low):
            found.append(n)
    return sorted(found, key=len, reverse=True)[:3]
