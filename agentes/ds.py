"""Design system (DS) del proyecto: índice, catálogo compacto, búsqueda y verificación de uso.

Cada proyecto puede tener su DS en un lugar distinto (módulo del repo, paquete SPM, módulo Gradle, ruta externa).
Se configura en `.agentes/team.local.yaml`:

    settings:
      design_system:
        ios: Modules/DesignSystem          # una ruta o lista de rutas (relativas al proyecto o absolutas)
        android: core/designsystem
        map: {Button: PrimaryButton}       # opcional: mapeo nativo → DS que corrige al automático
        ignore: [Image]                    # opcional: nativos permitidos

Si no se configura, `agentes ds index` lo detecta (carpetas/módulos tipo DesignSystem, DS, UIKit, CoreUI).
El catálogo se guarda en `.agentes/ds/catalog.json`; el contexto solo recibe una versión compacta y solo en
tareas de UI. El detalle se consulta con `ds_lookup` y el uso se verifica con `agentes ds check`.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from pathlib import Path

import yaml

from .store import HARNESS_DIR

DS_NAME = re.compile(r"(?i)^(design[-_]?system|\w*designsystem|ds|ui[-_]?kit|core[-_]?ui|ui[-_]?components|"
                     r"components[-_]?kit|\w+[-_]ds)$")
SKIP_DIRS = {"build", ".build", "DerivedData", "Pods", ".gradle", "node_modules", ".git", "Tests", "test",
             "androidTest", "testFixtures", "Preview Content", ".agentes"}

# familias de componentes nativos → sufijo que buscamos en el DS
FAMILIES = {
    "ios": {
        "Button": ["Button"], "Text": ["Text"], "TextField": ["TextField", "SecureField", "TextEditor"],
        "Toggle": ["Toggle"], "Label": ["Label"], "ProgressView": ["ProgressView"], "Picker": ["Picker"],
        "Divider": ["Divider"], "Image": ["Image", "AsyncImage"], "Card": [], "Badge": [], "Chip": [],
        "Alert": [".alert"], "Sheet": [], "Icon": ["Image(systemName"], "Avatar": [],
    },
    "uikit": {"Button": ["UIButton"], "Label": ["UILabel"], "Text": ["UILabel"], "TextField": ["UITextField", "UITextView"],
              "Switch": ["UISwitch"], "Toggle": ["UISwitch"], "Image": ["UIImageView"]},
    "android": {
        "Button": ["Button", "OutlinedButton", "TextButton", "ElevatedButton", "FilledTonalButton", "IconButton"],
        "Text": ["Text"], "TextField": ["TextField", "OutlinedTextField", "BasicTextField"],
        "Card": ["Card", "ElevatedCard", "OutlinedCard"], "Switch": ["Switch"], "Toggle": ["Switch"],
        "Checkbox": ["Checkbox"], "TopAppBar": ["TopAppBar", "CenterAlignedTopAppBar", "LargeTopAppBar"],
        "Dialog": ["AlertDialog", "Dialog"], "Progress": ["CircularProgressIndicator", "LinearProgressIndicator"],
        "ProgressIndicator": ["CircularProgressIndicator", "LinearProgressIndicator"],
        "Divider": ["Divider", "HorizontalDivider"], "Icon": ["Icon"], "Chip": ["AssistChip", "FilterChip", "SuggestionChip"],
        "Scaffold": ["Scaffold"], "BottomSheet": ["ModalBottomSheet"], "Snackbar": ["Snackbar"],
    },
    "android_xml": {"Button": ["Button", "com.google.android.material.button.MaterialButton"], "Text": ["TextView"],
                    "TextField": ["EditText", "com.google.android.material.textfield.TextInputEditText"],
                    "Card": ["androidx.cardview.widget.CardView", "com.google.android.material.card.MaterialCardView"]},
}
SWIFT_COLOR_RX = [
    (r"\bColor\s*\(\s*(red|hue|white|\.sRGB|#colorLiteral|hex)", "color literal"),
    (r"\bUIColor\s*\(\s*(red|white|hue|displayP3Red|hex)", "color literal"),
    (r"#colorLiteral", "color literal"),
    (r"\.(foregroundColor|foregroundStyle|background|tint|fill|stroke|accentColor)\s*\(\s*(Color)?\.(red|blue|green|gray|grey|black|white|orange|yellow|pink|purple|mint|teal|cyan|indigo|brown)\b", "color del sistema"),
]
SWIFT_FONT_RX = [(r"\.font\s*\(\s*\.system\s*\(\s*size", "tamaño de fuente literal"),
                 (r"\bFont\.custom\s*\(|\.font\s*\(\s*\.custom\s*\(", "fuente literal"),
                 (r"UIFont\.(systemFont|boldSystemFont)\s*\(\s*ofSize", "tamaño de fuente literal")]
SWIFT_SPACE_RX = [(r"\.padding\s*\(\s*(\.\w+\s*,\s*)?[1-9]\d*(\.\d+)?\s*\)", "espaciado literal"),
                  (r"spacing\s*:\s*[1-9]\d*(\.\d+)?\b", "espaciado literal"),
                  (r"\.cornerRadius\s*\(\s*[1-9]", "radio literal")]
KT_COLOR_RX = [(r"\bColor\s*\(\s*0x", "color literal"), (r"\bColor\s*\(\s*(red\s*=|[1-9]|0\.\d)", "color literal"),
               (r"\bColor\.(Red|Blue|Green|Gray|Black|White|Yellow|Magenta|Cyan|DarkGray|LightGray)\b", "color literal"),
               (r"android\.graphics\.Color\.parseColor", "color literal")]
KT_FONT_RX = [(r"\b\d+(\.\d+)?\.sp\b", "tamaño de fuente literal")]
KT_SPACE_RX = [(r"\b(?:padding|spacedBy|height|width|size)\s*\(\s*(?:[a-z]+\s*=\s*)?[1-9]\d*(\.\d+)?\.dp", "espaciado literal")]
XML_RX = [(r'android:textColor\s*=\s*"#', "color literal"), (r'android:background\s*=\s*"#', "color literal"),
          (r'android:textSize\s*=\s*"\d', "tamaño de fuente literal")]


# ------------------------------------------------------------------------------ utilidades
def ds_dir(root: Path) -> Path:
    d = root / HARNESS_DIR / "ds"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read(p: Path, limit: int = 400_000) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="ignore") if p.stat().st_size <= limit else ""
    except OSError:
        return ""


def _balanced(text: str, start: int, open_ch: str = "(", close_ch: str = ")") -> tuple[str, int]:
    """Devuelve el contenido entre el delimitador en `start` y su cierre (maneja anidamiento y strings)."""
    depth, i, in_str = 0, start, None
    while i < len(text):
        c = text[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == in_str:
                in_str = None
        elif c in "\"'":
            in_str = c
        elif c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i
        i += 1
    return text[start + 1:], len(text)


def _split_top(s: str) -> list[str]:
    out, depth, cur, in_str = [], 0, "", None
    for i, c in enumerate(s):
        if c == ">" and i > 0 and s[i - 1] == "-":  # flecha de closure/lambda (-> Unit), no cierra genérico
            cur += c
            continue
        if in_str:
            cur += c
            if c == in_str:
                in_str = None
            continue
        if c in "\"'":
            in_str = c
        elif c in "([{<":
            depth += 1
        elif c in ")]}>":
            depth -= 1
        if c == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += c
    if cur.strip():
        out.append(cur.strip())
    return out


def _doc_before(text: str, pos: int) -> str:
    """Comentario de documentación (/// o /** */) justo antes de la declaración."""
    before = text[:pos].rstrip()
    lines = before.split("\n")
    doc = []
    for ln in reversed(lines):
        t = ln.strip()
        if t.startswith("@") and not doc:
            continue  # anotaciones entre el doc y la declaración
        if t.startswith("///"):
            doc.insert(0, t[3:].strip())
        elif t.startswith("*/") or t.startswith("/**") or (t.startswith("*") and doc is not None and before.rstrip().endswith("*/")):
            doc.insert(0, t.strip("/* ").strip())
            if t.startswith("/**"):
                break
        else:
            break
    return " ".join(x for x in doc if x)[:200]


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


# ------------------------------------------------------------------------------ configuración y detección
def load_settings(root: Path) -> dict:
    from .installer import load_team
    return (load_team(root).get("settings", {}) or {}).get("design_system") or {}


def save_paths(root: Path, platform: str, paths: list[str]) -> None:
    from .installer import local_team_path
    p = local_team_path(root)
    data = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}
    ds = data.setdefault("settings", {}).setdefault("design_system", {})
    ds[platform] = paths[0] if len(paths) == 1 else paths
    p.parent.mkdir(exist_ok=True)
    p.write_text("# Personalización del equipo para este proyecto. Aplica con: agentes sync\n"
                 + yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=110), encoding="utf-8")


def _walk(base: Path, exts: tuple[str, ...]) -> list[Path]:
    out = []
    if not base.exists():
        return out
    for p in base.rglob("*"):
        if p.is_file() and p.suffix in exts and not (set(p.relative_to(base).parts[:-1]) & SKIP_DIRS):
            out.append(p)
    return out


def detect(root: Path) -> dict[str, list[str]]:
    """Encuentra módulos de DS por plataforma (nombres de carpeta y módulos Gradle)."""
    found: dict[str, list[str]] = {"ios": [], "android": []}
    settings = next((root / n for n in ("settings.gradle.kts", "settings.gradle") if (root / n).exists()), None)
    if settings:
        for mod in re.findall(r"['\"](:[\w:-]+)['\"]", _read(settings)):
            if re.search(r"(?i)design|(^|:)ds($|:)|ui-?kit|core-?ui", mod):
                d = root / mod.strip(":").replace(":", "/")
                if d.exists():
                    found["android"].append(d.relative_to(root).as_posix())
    candidates = []
    for d in root.rglob("*"):
        if not d.is_dir() or set(d.relative_to(root).parts) & (SKIP_DIRS | {".kiro", ".claude"}):
            continue
        if len(d.relative_to(root).parts) > 5 or not DS_NAME.match(d.name):
            continue
        candidates.append(d)
    for d in sorted(candidates, key=lambda x: len(x.parts)):
        rel = d.relative_to(root).as_posix()
        if any(rel.startswith(x + "/") or rel == x for x in found["ios"] + found["android"]):
            continue
        has_swift = any(True for _ in _walk(d, (".swift",))[:1])
        has_kt = any(True for _ in _walk(d, (".kt",))[:1])
        if has_swift:
            found["ios"].append(rel)
        elif has_kt and not any(rel.startswith(x) for x in found["android"]):
            found["android"].append(rel)
    return {k: v for k, v in found.items() if v}


def configured_paths(root: Path) -> dict[str, list[str]]:
    cfg = load_settings(root)
    out = {}
    for plat in ("ios", "android"):
        v = cfg.get(plat)
        if v:
            out[plat] = v if isinstance(v, list) else [v]
    return out


def _abs(root: Path, p: str) -> Path:
    q = Path(p).expanduser()
    return q if q.is_absolute() else (root / q).resolve()


# ------------------------------------------------------------------------------ parsers
SWIFT_DECL = re.compile(r"(?m)^[ \t]*(?:@\w+(?:\([^)]*\))?\s+)*(public|open)\s+(?:final\s+)?(struct|class|enum)\s+(\w+)"
                        r"(\s*<[^>{]*>)?\s*(?::\s*([^{]+))?\{")
UIKIT_BASES = r"\b(UIView|UIButton|UILabel|UIControl|UITextField|UITextView|UIStackView|UIImageView|UICollectionViewCell|UITableViewCell|UIViewController|UISwitch)\b"


def _swift_params(body: str) -> tuple[str, list[str]] | None:
    m = re.search(r"public\s+(?:convenience\s+)?init\s*\(", body)
    if not m:
        return None
    inner, _ = _balanced(body, m.end() - 1)
    params = _split_top(inner)
    labels = []
    for p in params:
        head = [w for w in p.split(":", 1)[0].strip().split() if not w.startswith("@")]
        labels.append(head[0] if head else "_")
    sig = ", ".join(re.sub(r"\s+", " ", p) for p in params)
    return sig, labels


def parse_swift(path: Path, root: Path) -> dict:
    text = _read(path)
    rel = path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)
    comps, mods, colors, fonts, spacing = [], [], {}, [], {}
    for m in SWIFT_DECL.finditer(text):
        _, kind, name, generic, inherits = m.groups()
        inherits = inherits or ""
        body, _ = _balanced(text, m.end() - 1, "{", "}")
        typ = None
        if kind == "struct" and re.search(r"\bView\b", inherits):
            typ = "SwiftUI"
        elif re.search(r"\b(ButtonStyle|ViewModifier|LabelStyle|ToggleStyle|TextFieldStyle)\b", inherits):
            typ = "estilo SwiftUI"
        elif kind == "class" and re.search(UIKIT_BASES, inherits):
            typ = "UIKit"
        if typ:
            ps = _swift_params(body)
            if ps:
                sig, labels = ps
            else:  # init memberwise: propiedades almacenadas sin valor por defecto
                props = re.findall(r"(?m)^\s*(?:public\s+)?(?:let|var)\s+(\w+)\s*:\s*([^=\n{]+)$", body)
                sig, labels = ", ".join(f"{n}: {t.strip()}" for n, t in props), [n for n, _ in props]
            comps.append({"nombre": name, "tipo": typ, "firma": f"{name}({sig})",
                          "corta": f"{name}({''.join(l + ':' for l in labels)})" if labels else f"{name}()",
                          "params": labels, "doc": _doc_before(text, m.start()), "archivo": rel,
                          "linea": _line_of(text, m.start())})
        lname = name.lower()
        if kind == "enum" and re.search(r"spacing|spacer|padding|radius|radii|size", lname):
            for cm in re.finditer(r"case\s+([^\n]+)", body):
                for part in cm.group(1).split(","):
                    k, _, v = part.partition("=")
                    if k.strip():
                        spacing[f"{name}.{k.strip()}"] = v.strip() or "?"
        if kind == "enum" and re.search(r"typograph|font|textstyle", lname):
            fonts += [f"{name}.{c.strip()}" for cm in re.finditer(r"case\s+([^\n=]+)", body)
                      for c in cm.group(1).split(",") if c.strip()]
    for em in re.finditer(r"(?m)^\s*(?:public\s+)?extension\s+(Color|UIColor|ShapeStyle|Font|UIFont|CGFloat|View)\b[^{]*\{", text):
        target = em.group(1)
        body, _ = _balanced(text, em.end() - 1, "{", "}")
        if target == "View":
            for fm in re.finditer(r"func\s+(\w+)\s*\(([^)]*)\)\s*->\s*some\s+View", body):
                mods.append({"nombre": f".{fm.group(1)}", "tipo": "modificador SwiftUI",
                             "firma": f".{fm.group(1)}({fm.group(2).strip()})", "corta": f".{fm.group(1)}()",
                             "params": [], "doc": _doc_before(body, fm.start()), "archivo": rel,
                             "linea": _line_of(text, em.end() + fm.start())})
            continue
        for sm in re.finditer(r"static\s+(?:let|var)\s+(\w+)\s*(?::\s*\w+)?\s*=\s*([^\n]+)", body):
            val = sm.group(2).strip()[:60]
            if target in ("Color", "UIColor", "ShapeStyle"):
                colors[f"{'Color' if target != 'UIColor' else 'UIColor'}.{sm.group(1)}"] = val
            elif target in ("Font", "UIFont"):
                fonts.append(f"{target}.{sm.group(1)}")
            else:
                spacing[f"CGFloat.{sm.group(1)}"] = val
    return {"componentes": comps, "modificadores": mods, "colores": colors, "tipografia": fonts, "espaciado": spacing}


def parse_colorset(path: Path) -> tuple[str, str] | None:
    try:
        data = json.loads(path.read_text())
    except Exception:
        return None
    def hx(comp):
        vals = []
        for k in ("red", "green", "blue"):
            v = str(comp.get(k, "0"))
            if v.lower().startswith("0x"):
                vals.append(int(v, 16))
            elif "." in v:
                vals.append(round(float(v) * 255))
            else:
                vals.append(int(float(v)))
        return "#{:02X}{:02X}{:02X}".format(*vals)
    light = dark = None
    for c in data.get("colors", []):
        comp = (c.get("color") or {}).get("components")
        if not comp:
            continue
        if any(a.get("value") == "dark" for a in c.get("appearances", [])):
            dark = hx(comp)
        elif light is None:
            light = hx(comp)
    if not light:
        return None
    return path.parent.name.replace(".colorset", ""), light + (f" (oscuro {dark})" if dark else "")


KT_COMPOSABLE = re.compile(r"@Composable\s+(?:@\w+(?:\([^)]*\))?\s+)*((?:public|internal|private)\s+)?fun\s+(?:[\w<>]+\.)?([A-Z]\w*)\s*\(")
KT_VIEW = re.compile(r"(?m)^\s*(?:open\s+)?class\s+(\w+)\s*(?:@JvmOverloads\s+)?(?:constructor\s*)?\(([^)]*)\)\s*:\s*([\w.]+)")


def parse_kotlin(path: Path, root: Path) -> dict:
    text = _read(path)
    rel = path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)
    comps, colors, fonts, spacing = [], {}, [], {}
    for m in KT_COMPOSABLE.finditer(text):
        vis, name = m.group(1), m.group(2)
        if vis and vis.strip() in ("private", "internal"):
            continue
        pre = text[max(0, m.start() - 120):m.start()]
        if "@Preview" in pre.split("\n\n")[-1] or name.endswith("Preview"):
            continue
        inner, _ = _balanced(text, m.end() - 1)
        params = _split_top(inner)
        names = [p.split(":", 1)[0].strip().split()[-1] for p in params if ":" in p]
        short = [n for n in names if n != "modifier"]
        joined = ", ".join(re.sub(r"\s+", " ", p) for p in params)
        comps.append({"nombre": name, "tipo": "Compose", "firma": f"{name}({joined})",
                      "corta": f"{name}({', '.join(short)})", "params": names, "doc": _doc_before(text, m.start()),
                      "archivo": rel, "linea": _line_of(text, m.start())})
    for m in KT_VIEW.finditer(text):
        if re.search(r"(View|Layout|Button|TextView|EditText|ImageView|CardView)$", m.group(3)):
            comps.append({"nombre": m.group(1), "tipo": "Android View", "firma": f"{m.group(1)}({m.group(2).strip()})",
                          "corta": f"{m.group(1)}()", "params": [], "doc": _doc_before(text, m.start()),
                          "archivo": rel, "linea": _line_of(text, m.start())})
    for m in re.finditer(r"val\s+(\w+)\s*=\s*Color\s*\(\s*0x([0-9A-Fa-f]{6,8})\s*\)", text):
        h = m.group(2)[-6:].upper()
        colors[m.group(1)] = f"#{h}"
    for m in re.finditer(r"val\s+(\w+)\s*(?::\s*TextStyle)?\s*=\s*TextStyle\s*\(", text):
        fonts.append(m.group(1))
    for om in re.finditer(r"object\s+(\w*(?:Spacing|Dimens|Radius|Size)\w*)\s*\{", text):
        body, _ = _balanced(text, om.end() - 1, "{", "}")
        for vm in re.finditer(r"val\s+(\w+)\s*(?::\s*Dp)?\s*=\s*([\d.]+)\.dp", body):
            spacing[f"{om.group(1)}.{vm.group(1)}"] = f"{vm.group(2)}dp"
    return {"componentes": comps, "modificadores": [], "colores": colors, "tipografia": fonts, "espaciado": spacing}


def parse_xml_values(path: Path) -> dict:
    text = _read(path)
    colors = {f"@color/{n}": v for n, v in re.findall(r'<color\s+name="([^"]+)"\s*>\s*([^<]+)<', text)}
    spacing = {f"@dimen/{n}": v for n, v in re.findall(r'<dimen\s+name="([^"]+)"\s*>\s*([^<]+)<', text)}
    return {"componentes": [], "modificadores": [], "colores": colors, "tipografia": [], "espaciado": spacing}


# ------------------------------------------------------------------------------ índice
def _merge(acc: dict, part: dict) -> None:
    acc["componentes"] += part["componentes"]
    acc["modificadores"] += part["modificadores"]
    acc["tokens"]["colores"].update(part["colores"])
    acc["tokens"]["tipografia"] += [f for f in part["tipografia"] if f not in acc["tokens"]["tipografia"]]
    acc["tokens"]["espaciado"].update(part["espaciado"])


def build_map(platform: str, comps: list[dict], overrides: dict | None = None, ignore: list | None = None) -> dict:
    """Mapeo nativo → componente(s) del DS, por sufijo del nombre (DSButton, DsButton, PrimaryButton → Button)."""
    names = [c["nombre"] for c in comps]
    fams = dict(FAMILIES["ios"]) if platform == "ios" else dict(FAMILIES["android"])
    extra = FAMILIES["uikit"] if platform == "ios" else FAMILIES["android_xml"]
    mapping: dict[str, list[str]] = {}
    for fam, natives in list(fams.items()) + [(k, v) for k, v in extra.items()]:
        cands = [n for n in names if n.endswith(fam) and n != fam and not n.endswith("Preview")]
        if not cands and fam in ("Button", "Text"):
            continue
        cands = sorted(set(cands), key=len)
        for nat in natives:
            if cands and not nat.startswith("."):
                mapping.setdefault(nat, [])
                mapping[nat] += [c for c in cands if c not in mapping[nat]]
    for nat, ds in (overrides or {}).items():
        mapping[nat] = ds if isinstance(ds, list) else [ds]
    for nat in ignore or []:
        mapping.pop(nat, None)
    return {k: v[:3] for k, v in mapping.items() if v}


def _sources(root: Path, paths: dict[str, list[str]]) -> dict[str, list[Path]]:
    srcs = {}
    for plat, ps in paths.items():
        files = []
        for p in ps:
            base = _abs(root, p)
            if plat == "ios":
                files += _walk(base, (".swift",)) + [q for q in base.rglob("*.colorset/Contents.json")]
            else:
                files += _walk(base, (".kt",)) + [q for q in base.rglob("res/values*/*.xml")]
        srcs[plat] = sorted(set(files))
    return srcs


def _fingerprint(srcs: dict[str, list[Path]]) -> str:
    h = hashlib.sha256()
    for plat in sorted(srcs):
        for f in srcs[plat]:
            try:
                st = f.stat()
                h.update(f"{f}:{st.st_size}:{int(st.st_mtime)}".encode())
            except OSError:
                pass
    return h.hexdigest()[:16]


def index(root: Path, paths: dict[str, list[str]] | None = None, force: bool = False) -> dict:
    root = Path(root).resolve()
    paths = paths or configured_paths(root) or detect(root)
    if not paths:
        return {}
    srcs = _sources(root, paths)
    fp = _fingerprint(srcs)
    cat_p = ds_dir(root) / "catalog.json"
    if not force and cat_p.exists():
        old = json.loads(cat_p.read_text())
        if old.get("huella") == fp:
            return old
    cfg = load_settings(root)
    cat: dict = {"generado": time.strftime("%Y-%m-%d %H:%M"), "huella": fp, "plataformas": {}}
    for plat, files in srcs.items():
        acc = {"rutas": paths[plat], "componentes": [], "modificadores": [],
               "tokens": {"colores": {}, "tipografia": [], "espaciado": {}}}
        for f in files:
            if f.name == "Contents.json":
                cs = parse_colorset(f)
                if cs:
                    acc["tokens"]["colores"][f"Color(\"{cs[0]}\")"] = cs[1]
            elif f.suffix == ".swift":
                _merge(acc, parse_swift(f, root))
            elif f.suffix == ".kt":
                _merge(acc, parse_kotlin(f, root))
            elif f.suffix == ".xml":
                _merge(acc, parse_xml_values(f))
        sets = {k[len('Color("'):-2]: v for k, v in acc["tokens"]["colores"].items() if k.startswith('Color("')}
        for k, v in list(acc["tokens"]["colores"].items()):
            m = re.match(r'(?:UI)?Color\(\s*(?:named:\s*)?"([^"]+)"', str(v))
            if m and m.group(1) in sets:
                acc["tokens"]["colores"][k] = sets[m.group(1)]
        seen = set()
        acc["componentes"] = [c for c in acc["componentes"] if not (c["nombre"] in seen or seen.add(c["nombre"]))]
        acc["mapa"] = build_map(plat, acc["componentes"], (cfg.get("map") or {}), cfg.get("ignore") or [])
        cat["plataformas"][plat] = acc
    cat_p.write_text(json.dumps(cat, indent=2, ensure_ascii=False))
    return cat


def load_catalog(root: Path) -> dict:
    p = Path(root) / HARNESS_DIR / "ds" / "catalog.json"
    try:
        return json.loads(p.read_text()) if p.exists() else {}
    except Exception:
        return {}


# ------------------------------------------------------------------------------ contexto compacto
PLAT_NAMES = {"ios": "iOS", "android": "Android"}


def platforms_in(text: str) -> list[str]:
    low = text.lower()
    out = []
    if re.search(r"\bios\b|swift|swiftui|uikit|iphone|ipad|xcode", low):
        out.append("ios")
    if re.search(r"android|kotlin|compose|jetpack|gradle", low):
        out.append("android")
    return out


def compact(cat: dict, platforms: list[str] | None = None, max_chars: int = 2400) -> str:
    lines = []
    for plat, data in cat.get("plataformas", {}).items():
        if platforms and plat not in platforms:
            continue
        comps = ", ".join(c["corta"] for c in data["componentes"])
        mods = ", ".join(m["corta"] for m in data["modificadores"])
        t = data["tokens"]
        tok = []
        if t["colores"]:
            tok.append("colores " + ", ".join(f"{n}={v.split(' ')[0]}" if str(v).startswith("#") else n
                                              for n, v in list(t["colores"].items())[:12]))
        if t["tipografia"]:
            tok.append("tipografía " + ", ".join(t["tipografia"][:10]))
        if t["espaciado"]:
            tok.append("espaciado " + ", ".join(f"{k}={v}" for k, v in list(t["espaciado"].items())[:10]))
        groups: dict[str, list[str]] = {}
        for n, d in data["mapa"].items():
            if "." not in n:  # omite nombres completos de clases XML
                groups.setdefault(" | ".join(d), []).append(n)
        mp = ", ".join(f"{'/'.join(ns)} → {ds}" for ds, ns in groups.items())
        lines.append(f"[{PLAT_NAMES.get(plat, plat)}] Componentes: {comps}" + (f" · Modificadores: {mods}" if mods else ""))
        if tok:
            lines.append(f"[{PLAT_NAMES.get(plat, plat)}] Tokens: " + "; ".join(tok))
        if mp:
            lines.append(f"[{PLAT_NAMES.get(plat, plat)}] Usa en lugar de nativos: {mp}")
    text = "\n".join(lines)
    return text[:max_chars] + (" …" if len(text) > max_chars else "")


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-záéíóúñ]{3,}", re.sub(r"([a-z])([A-Z])", r"\1 \2", s).lower())}


ES_EN = {"boton": "button", "botón": "button", "texto": "text", "campo": "field", "tarjeta": "card", "insignia": "badge",
         "etiqueta": "label", "interruptor": "switch toggle", "casilla": "checkbox", "dialogo": "dialog alert",
         "diálogo": "dialog alert", "barra": "bar", "icono": "icon", "imagen": "image", "lista": "list row cell",
         "chip": "chip", "avatar": "avatar", "cargando": "progress loading", "sombra": "shadow", "color": "color",
         "colores": "color", "tipografia": "typography font", "tipografía": "typography font", "espaciado": "spacing"}


def relevant(cat: dict, query: str, platforms: list[str] | None = None, k: int = 4) -> list[dict]:
    q = _words(query)
    q |= {w for x in list(q) for w in ES_EN.get(x, "").split()}
    scored = []
    for plat, data in cat.get("plataformas", {}).items():
        if platforms and plat not in platforms:
            continue
        for c in data["componentes"] + data["modificadores"]:
            words = _words(c["nombre"]) | _words(c.get("doc", ""))
            score = len(q & words) * 2 + len(q & _words(" ".join(c.get("params", []))))
            if score:
                scored.append((score, plat, c))
    scored.sort(key=lambda x: -x[0])
    return [{**c, "plataforma": plat} for _, plat, c in scored[:k]]


def usage_example(root: Path, name: str, ds_paths: list[str]) -> str | None:
    """Primer uso real del componente fuera del DS (git grep, barato)."""
    try:
        out = subprocess.run(["git", "grep", "-n", "-m", "1", "-e", f"{name}(", "--", "*.swift", "*.kt"], cwd=root,
                             capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return None
    for line in out.splitlines():
        path = line.split(":", 1)[0]
        if not any(path.startswith(p.rstrip("/") + "/") for p in ds_paths):
            return line[:200]
    return None


def lookup(root: Path, query: str, platform: str | None = None, k: int = 5) -> str:
    cat = load_catalog(root)
    if not cat:
        return "No hay catálogo del design system: ejecuta `agentes ds index`."
    plats = [platform] if platform else None
    if re.search(r"(?i)\btoken|color|tipograf|font|espaciado|spacing", query) and not relevant(cat, query, plats, 1):
        out = []
        for plat, d in cat["plataformas"].items():
            if plats and plat not in plats:
                continue
            t = d["tokens"]
            out.append(f"[{PLAT_NAMES[plat]}] colores: " + ", ".join(f"{n} {v}" for n, v in t["colores"].items()))
            out.append(f"[{PLAT_NAMES[plat]}] tipografía: " + ", ".join(t["tipografia"]))
            out.append(f"[{PLAT_NAMES[plat]}] espaciado: " + ", ".join(f"{n}={v}" for n, v in t["espaciado"].items()))
        return "\n".join(out)
    exact = [{**c, "plataforma": p} for p, d in cat["plataformas"].items() if not plats or p in plats
             for c in d["componentes"] + d["modificadores"] if c["nombre"].lower() == query.strip().lower()]
    hits = exact or relevant(cat, query, plats, k)
    if not hits:
        return "Sin coincidencias en el DS. Componentes: " + compact(cat, plats, 600)
    out = []
    for c in hits:
        ds_paths = cat["plataformas"][c["plataforma"]]["rutas"]
        ex = usage_example(root, c["nombre"], ds_paths)
        out.append(f"[{PLAT_NAMES[c['plataforma']]}] {c['tipo']}: {c['firma']}\n  {c.get('doc') or ''}\n"
                   f"  Definido en {c['archivo']}:{c['linea']}" + (f"\n  Ejemplo de uso: {ex}" if ex else ""))
    return "\n".join(out)


def summary_line(cat: dict) -> str:
    if not cat:
        return ""
    parts = [f"{PLAT_NAMES[p]} {len(d['componentes'])} componentes ({', '.join(d['rutas'])})"
             for p, d in cat.get("plataformas", {}).items()]
    return ("Design system indexado: " + "; ".join(parts)
            + ". En tareas de UI recibirás el catálogo; detalle con `ds_lookup`; verifica con `agentes ds check`.")


# ------------------------------------------------------------------------------ verificación
def _changed_lines(root: Path, all_files: bool = False, files: list[str] | None = None) -> dict[str, list[tuple[int, str]]]:
    out: dict[str, list[tuple[int, str]]] = {}
    exts = (".swift", ".kt", ".xml")

    def whole(rel):
        p = root / rel
        if p.is_file() and p.suffix in exts:
            out[rel] = list(enumerate(_read(p).splitlines(), 1))

    if files:
        for f in files:
            whole(f)
        return out
    if all_files:
        for p in root.rglob("*"):
            if p.is_file() and p.suffix in exts and not (set(p.relative_to(root).parts) & SKIP_DIRS):
                whole(p.relative_to(root).as_posix())
        return out
    try:
        diff = subprocess.run(["git", "diff", "--unified=0", "--no-color", "HEAD", "--", "*.swift", "*.kt", "*.xml"],
                              cwd=root, capture_output=True, text=True, timeout=20).stdout
        untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard", "--", "*.swift", "*.kt", "*.xml"],
                                   cwd=root, capture_output=True, text=True, timeout=20).stdout.split()
    except Exception:
        return out
    cur, ln = None, 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            cur = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@") and cur:
            m = re.search(r"\+(\d+)", line)
            ln = int(m.group(1)) if m else 0
        elif cur and line.startswith("+") and not line.startswith("+++"):
            out.setdefault(cur, []).append((ln, line[1:]))
            ln += 1
    for rel in untracked:
        whole(rel)
    return out


def _in_preview(lines: list[str], idx: int) -> bool:
    for j in range(idx, max(-1, idx - 60), -1):
        t = lines[j].strip()
        if t.startswith(("#Preview", "@Preview")) or "PreviewProvider" in t:
            return True
        if re.match(r"^(public |private |internal |fileprivate )?(struct|class|fun|func|@Composable)\b", lines[j]) and j != idx:
            prev = lines[j - 1].strip() if j > 0 else ""
            return prev.startswith(("@Preview", "#Preview"))
    return False


def check(root: Path, all_files: bool = False, files: list[str] | None = None) -> dict:
    root = Path(root).resolve()
    cat = load_catalog(root)
    if not cat:
        return {"estado": "sin-catalogo", "violaciones": []}
    ds_paths = [p.rstrip("/") for d in cat["plataformas"].values() for p in d["rutas"]]
    viol = []
    for rel, lines in _changed_lines(root, all_files, files).items():
        if any(rel.startswith(p + "/") for p in ds_paths) or re.search(r"(Tests?/|/test/|androidTest|Tests?\.swift$|Test\.kt$|Preview)", rel):
            continue
        full = _read(root / rel).splitlines()
        plat = "ios" if rel.endswith(".swift") else "android"
        data = cat["plataformas"].get(plat)
        if not data:
            continue
        mapa = data["mapa"]
        has_space = bool(data["tokens"]["espaciado"])
        has_font = bool(data["tokens"]["tipografia"])
        for ln, code in lines:
            if "ds-ignore" in code or code.strip().startswith(("//", "*", "import ")):
                continue
            if 0 < ln <= len(full) and _in_preview(full, ln - 1):
                continue
            rules = []
            if rel.endswith(".xml"):
                for nat, ds in mapa.items():
                    if re.search(rf"<{re.escape(nat)}[\s>/]", code):
                        rules.append(("componente", "error", f"<{nat}>", "usa " + " | ".join(ds)))
                rules += [("token", "error", lbl, "usa un token del DS") for rx, lbl in XML_RX if re.search(rx, code)]
            else:
                for nat, ds in mapa.items():
                    if re.search(rf"(?<![\w.]){re.escape(nat)}\s*[\(\{{]", code):
                        rules.append(("componente", "error", nat, "usa " + " | ".join(ds)))
                color_rx = SWIFT_COLOR_RX if plat == "ios" else KT_COLOR_RX
                font_rx = SWIFT_FONT_RX if plat == "ios" else KT_FONT_RX
                space_rx = SWIFT_SPACE_RX if plat == "ios" else KT_SPACE_RX
                rules += [("color", "error", lbl, "usa un color del DS") for rx, lbl in color_rx if re.search(rx, code)]
                if has_font:
                    rules += [("tipografía", "aviso", lbl, "usa la tipografía del DS") for rx, lbl in font_rx if re.search(rx, code)]
                if has_space:
                    rules += [("espaciado", "aviso", lbl, "usa un token de espaciado del DS") for rx, lbl in space_rx if re.search(rx, code)]
            uniq = {}
            for r_ in rules:
                uniq.setdefault((r_[0], r_[2]), r_)
            for regla, sev, found, sug in uniq.values():
                viol.append({"archivo": rel, "linea": ln, "regla": regla, "severidad": sev, "encontrado": found,
                             "sugerencia": sug, "codigo": code.strip()[:120]})
    errors = sum(v["severidad"] == "error" for v in viol)
    return {"estado": "ok" if not viol else ("errores" if errors else "avisos"), "violaciones": viol,
            "errores": errors, "avisos": len(viol) - errors}


def render_check(res: dict, limit: int = 25) -> str:
    if res["estado"] == "sin-catalogo":
        return "Sin catálogo del design system (ejecuta `agentes ds index`)."
    if res["estado"] == "ok":
        return "✔ Design system: sin usos nativos ni valores literales en los cambios."
    lines = [f"Design system: {res['errores']} error(es), {res['avisos']} aviso(s) en los cambios:"]
    for v in res["violaciones"][:limit]:
        icon = "✘" if v["severidad"] == "error" else "!"
        lines.append(f"  {icon} {v['archivo']}:{v['linea']} {v['regla']}: {v['encontrado']} → {v['sugerencia']}   | {v['codigo']}")
    if len(res["violaciones"]) > limit:
        lines.append(f"  … y {len(res['violaciones']) - limit} más")
    lines.append("Corrige usando componentes/tokens del DS (`ds_lookup`), o marca la línea con `// ds-ignore` si es intencional.")
    return "\n".join(lines)
