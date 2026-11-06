"""Diseño a partir de referencias visuales (capturas, exportaciones de Figma).

  ref      guarda la referencia en .agentes/design/refs/, extrae la paleta EXACTA (colores dominantes en hex),
           asigna roles (fondo, texto, acentos), calcula contrastes WCAG y lo registra en la memoria.
  compare  compara una captura de la implementación contra la referencia: % de diferencia, regiones con más
           diferencias, colores de la referencia que faltan, e imagen con las diferencias marcadas.
  shot     toma una captura de una URL con Playwright (python o npx) para el ciclo de verificación visual.
  figma    importa un frame de Figma con un token personal usando solo 2 llamadas (nodo + render), con caché.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

from .store import HARNESS_DIR, Store


def _pil():
    try:
        from PIL import Image  # type: ignore
        return Image
    except ImportError as e:  # pragma: no cover
        raise SystemExit("Falta Pillow: reinstala el CLI con ./install.sh") from e


def design_dir(root: Path) -> Path:
    d = root / HARNESS_DIR / "design"
    (d / "refs").mkdir(parents=True, exist_ok=True)
    return d


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:50] or "ref"


# ------------------------------------------------------------------------------ color
def hex_of(rgb) -> str:
    return "#{:02X}{:02X}{:02X}".format(*[int(c) for c in rgb[:3]])


def rgb_of(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore


def luminance(rgb) -> float:
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb[:3]
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a, b) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def dist(a, b) -> float:
    # distancia perceptual simple ("redmean")
    rm = (a[0] + b[0]) / 2
    dr, dg, db = a[0] - b[0], a[1] - b[1], a[2] - b[2]
    return ((2 + rm / 256) * dr * dr + 4 * dg * dg + (2 + (255 - rm) / 256) * db * db) ** 0.5


def saturation(rgb) -> float:
    """Croma (0-1): qué tan "de color" es; los grises y blancos dan ~0 aunque sean muy claros."""
    return (max(rgb[:3]) - min(rgb[:3])) / 255


def palette(img_path: Path, n: int = 8) -> list[dict]:
    """Colores dominantes con su proporción (cuantización median-cut + fusión de tonos casi iguales)."""
    Image = _pil()
    im = Image.open(img_path).convert("RGB")
    im.thumbnail((480, 480), resample=Image.NEAREST)  # NEAREST conserva los colores exactos (sin mezclas de bordes)
    q = im.quantize(colors=24, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()
    total = im.size[0] * im.size[1]
    raw = sorted(((cnt, tuple(pal[i * 3:i * 3 + 3])) for cnt, i in q.getcolors()), reverse=True)
    merged: list[list] = []
    for cnt, rgb in raw:
        for m in merged:
            if dist(m[1], rgb) < 14:  # solo fusiona tonos casi idénticos (conserva grises de superficie)
                m[0] += cnt
                break
        else:
            merged.append([cnt, rgb])
    merged.sort(key=lambda m: -m[0])
    return [{"hex": hex_of(rgb), "pct": round(100 * cnt / total, 1), "rgb": list(rgb)}
            for cnt, rgb in merged if cnt / total >= 0.003][:n]


def roles(colors: list[dict]) -> dict:
    """Asigna roles probables: fondo (más extenso), texto (mayor contraste con el fondo), acentos (más saturados)."""
    if not colors:
        return {}
    bg = colors[0]
    rest = colors[1:]
    text = max(rest, key=lambda c: contrast(c["rgb"], bg["rgb"]), default=None)
    accents = sorted([c for c in rest if c is not text and saturation(c["rgb"]) > 0.25 and c["pct"] >= 0.5],
                     key=lambda c: -saturation(c["rgb"]) * (c["pct"] ** 0.5))[:3]
    surfaces = [c for c in rest if c is not text and c not in accents and saturation(c["rgb"]) <= 0.25][:2]
    out = {"fondo": bg["hex"]}
    if text:
        out["texto"] = text["hex"]
        out["contraste_texto"] = round(contrast(text["rgb"], bg["rgb"]), 2)
    if accents:
        out["acentos"] = [a["hex"] for a in accents]
        out["contraste_acentos"] = {a["hex"]: round(contrast(a["rgb"], bg["rgb"]), 2) for a in accents}
    if surfaces:
        out["superficies"] = [s["hex"] for s in surfaces]
    return out


# ------------------------------------------------------------------------------ referencias
def add_reference(root: Path, src: Path, name: str | None = None, note: str = "", source: str = "") -> dict:
    Image = _pil()
    src = src.expanduser().resolve()
    if not src.is_file():
        raise SystemExit(f"No existe la imagen: {src}")
    name = slugify(name or src.stem)
    d = design_dir(root) / "refs"
    dst = d / f"{name}{src.suffix.lower()}"
    if src != dst:
        shutil.copy2(src, dst)
    with Image.open(dst) as im:
        w, h = im.size
    colors = palette(dst)
    info = {
        "nombre": name, "archivo": dst.relative_to(root).as_posix(), "ancho": w, "alto": h,
        "formato": "móvil" if w < 600 or h / max(w, 1) > 1.6 else ("tablet" if w < 1100 else "escritorio"),
        "paleta": [{k: c[k] for k in ("hex", "pct")} for c in colors], "roles": roles(colors),
        "nota": note, "origen": source or str(src), "fecha": time.strftime("%Y-%m-%d %H:%M"),
    }
    (d / f"{name}.json").write_text(json.dumps(info, indent=2, ensure_ascii=False))
    r = info["roles"]
    texto = (f"Referencia visual '{name}' ({info['archivo']}, {w}×{h}, {info['formato']}). Paleta EXACTA medida de "
             f"los píxeles: fondo {r.get('fondo')}, texto {r.get('texto', '?')} (contraste {r.get('contraste_texto', '?')}:1)"
             + (f", acentos {', '.join(r['acentos'])}" if r.get("acentos") else "")
             + (f", superficies {', '.join(r['superficies'])}" if r.get("superficies") else "")
             + f". Todos: {', '.join(c['hex'] + ' ' + str(c['pct']) + '%' for c in info['paleta'])}."
             + (f" Nota: {note}" if note else ""))
    st = Store(root)
    old = [m["id"] for m in st.list("design", 200) if m.get("source") == info["archivo"]]
    st.delete(old)
    st.add(texto, kind="design", tags="referencia", source=info["archivo"], agent="design-ref")
    return info


def list_references(root: Path) -> list[dict]:
    d = design_dir(root) / "refs"
    return [json.loads(p.read_text()) for p in sorted(d.glob("*.json"))]


def resolve_ref(root: Path, ref: str) -> Path:
    p = Path(ref)
    if p.exists():
        return p
    for cand in (design_dir(root) / "refs").glob(f"{slugify(ref)}.*"):
        if cand.suffix != ".json":
            return cand
    raise SystemExit(f"No encuentro la referencia '{ref}' (usa `agentes design list`).")


# ------------------------------------------------------------------------------ comparación visual
REGIONS = [["arriba-izquierda", "arriba-centro", "arriba-derecha"],
           ["centro-izquierda", "centro", "centro-derecha"],
           ["abajo-izquierda", "abajo-centro", "abajo-derecha"]]


def _crop(im, top: float, bottom: float):
    w, h = im.size
    return im.crop((0, round(h * top), w, h - round(h * bottom))) if (top or bottom) else im


def out_dir_tmp(root: Path, tag: str, im) -> Path:
    p = design_dir(root) / "compare" / f".tmp-{tag}.png"
    p.parent.mkdir(parents=True, exist_ok=True)
    im.save(p)
    return p


def compare(root: Path, ref_path: Path, actual_path: Path, out: Path | None = None, threshold: int = 40,
            ignore_top: float = 0.0, ignore_bottom: float = 0.0) -> dict:
    Image = _pil()
    from PIL import ImageChops  # type: ignore
    ref = _crop(Image.open(ref_path).convert("RGB"), ignore_top, ignore_bottom)
    act = _crop(Image.open(actual_path).convert("RGB"), ignore_top, ignore_bottom)
    warn = []
    ra, aa = ref.size[0] / ref.size[1], act.size[0] / act.size[1]
    if abs(ra - aa) / ra > 0.05:
        warn.append(f"proporciones distintas (ref {ref.size[0]}×{ref.size[1]}, actual {act.size[0]}×{act.size[1]}): "
                    "captura con el mismo viewport para una comparación justa")
    w = min(ref.size[0], 1200)
    size = (w, round(ref.size[1] * w / ref.size[0]))
    ref_s, act_s = ref.resize(size), act.resize(size)
    diff = ImageChops.difference(ref_s, act_s).convert("L")
    mask = diff.point(lambda v: 255 if v > threshold else 0)
    hist = mask.histogram()
    pct = 100 * hist[255] / (size[0] * size[1])
    regions = []
    for r in range(3):
        for c in range(3):
            box = (c * size[0] // 3, r * size[1] // 3, (c + 1) * size[0] // 3, (r + 1) * size[1] // 3)
            h = mask.crop(box).histogram()
            area = (box[2] - box[0]) * (box[3] - box[1])
            regions.append((round(100 * h[255] / area, 1), REGIONS[r][c]))
    regions.sort(reverse=True)
    tmp_r, tmp_a = out_dir_tmp(root, "r", ref), out_dir_tmp(root, "a", act)
    pal_ref, pal_act = palette(tmp_r), palette(tmp_a, 12)
    missing = [c["hex"] for c in pal_ref if c["pct"] >= 1
               and min((dist(c["rgb"], a["rgb"]) for a in pal_act), default=999) > 45]
    out = out or design_dir(root) / "compare" / f"diff-{Path(actual_path).stem}-{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 10**6}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    red = Image.new("RGB", size, (255, 0, 0))
    overlay = Image.composite(red, ref_s.convert("L").convert("RGB"), mask)
    side = Image.new("RGB", (size[0] * 3, size[1]), "white")
    side.paste(ref_s, (0, 0))
    side.paste(act_s, (size[0], 0))
    side.paste(overlay, (size[0] * 2, 0))
    side.save(out)
    worst = regions[0][0]
    accents = set(roles(pal_ref).get("acentos", []))
    if pct >= 10 or worst >= 15 or len(missing) >= 2 or accents & set(missing):
        verdict = "diferencias importantes"
    elif pct >= 2 or worst >= 4 or missing:
        verdict = "diferencias menores"
    else:
        verdict = "muy parecido"
    return {"diferencia_pct": round(pct, 1), "veredicto": verdict, "regiones": regions[:3],
            "colores_faltantes": missing, "imagen": out.relative_to(root).as_posix() if out.is_relative_to(root) else str(out),
            "avisos": warn}


# ------------------------------------------------------------------------------ captura
def device_screenshot(platform: str, out: Path, device: str | None = None) -> Path:
    """Captura del simulador de iOS (xcrun simctl) o del emulador/dispositivo Android (adb)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    if platform == "ios":
        if not shutil.which("xcrun"):
            raise SystemExit("Necesitas Xcode (xcrun simctl) y un simulador abierto.")
        r = subprocess.run(["xcrun", "simctl", "io", device or "booted", "screenshot", "--type=png", str(out)],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise SystemExit("No se pudo capturar el simulador (¿hay uno iniciado?):\n" + (r.stderr or r.stdout)[-400:])
        return out
    if not shutil.which("adb"):
        raise SystemExit("Necesitas adb (Android platform-tools) y un emulador o dispositivo conectado.")
    cmd = ["adb"] + (["-s", device] if device else []) + ["exec-out", "screencap", "-p"]
    r = subprocess.run(cmd, capture_output=True, timeout=60)
    if r.returncode != 0 or not r.stdout.startswith(b"\x89PNG"):
        raise SystemExit("No se pudo capturar con adb (¿emulador iniciado? `adb devices`):\n"
                         + r.stderr.decode(errors="ignore")[-400:])
    out.write_bytes(r.stdout)
    return out


def screenshot(url: str, out: Path, width: int = 1440, height: int = 900, full: bool = False) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": width, "height": height})
            pg.goto(url, wait_until="networkidle")
            pg.screenshot(path=str(out), full_page=full)
            b.close()
        return out
    except ImportError:
        pass
    if shutil.which("npx"):
        cmd = ["npx", "-y", "playwright", "screenshot", f"--viewport-size={width},{height}", url, str(out)]
        if full:
            cmd.insert(3, "--full-page")
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if r.returncode == 0 and out.exists():
            return out
        raise SystemExit("No se pudo capturar con Playwright (¿falta el navegador? ejecuta `npx playwright install chromium`).\n"
                         + (r.stderr or r.stdout)[-500:])
    raise SystemExit("Necesitas Playwright: `npx playwright install chromium` (Node) o `pip install playwright`.")


# ------------------------------------------------------------------------------ Figma (REST, 2 llamadas)
def parse_figma_url(url: str) -> tuple[str, str | None]:
    m = re.search(r"figma\.com/(?:design|file|proto)/([A-Za-z0-9]+)", url)
    if not m:
        raise SystemExit("URL de Figma no válida (esperado figma.com/design/<clave>/...).")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    node = q.get("node-id", [None])[0]
    return m.group(1), node.replace("-", ":") if node else None


def _paint_hex(p: dict) -> str | None:
    if p.get("type") == "SOLID" and p.get("visible", True):
        c = p["color"]
        return hex_of((c["r"] * 255, c["g"] * 255, c["b"] * 255))
    return None


def figma_tokens(node: dict) -> dict:
    """Extrae colores, tipografías, radios, espaciados y sombras de un árbol de nodos de Figma."""
    colors: dict[str, int] = {}
    fonts: dict[str, int] = {}
    radii, gaps, pads, shadows = set(), set(), set(), set()

    def walk(n):
        for key in ("fills", "strokes"):
            for p in n.get(key, []) or []:
                h = _paint_hex(p)
                if h:
                    colors[h] = colors.get(h, 0) + 1
        st = n.get("style") or {}
        if n.get("type") == "TEXT" and st:
            f = f"{st.get('fontFamily')} {int(st.get('fontWeight', 400))} {round(st.get('fontSize', 0))}px"
            if st.get("lineHeightPx"):
                f += f"/{round(st['lineHeightPx'])}px"
            fonts[f] = fonts.get(f, 0) + 1
        if n.get("cornerRadius"):
            radii.add(round(n["cornerRadius"]))
        if n.get("itemSpacing"):
            gaps.add(round(n["itemSpacing"]))
        for k in ("paddingLeft", "paddingTop"):
            if n.get(k):
                pads.add(round(n[k]))
        for e in n.get("effects", []) or []:
            if e.get("type") == "DROP_SHADOW" and e.get("visible", True):
                o, c = e.get("offset", {}), e.get("color", {})
                shadows.add(f"{round(o.get('x', 0))}px {round(o.get('y', 0))}px {round(e.get('radius', 0))}px "
                            f"rgba({round(c.get('r', 0) * 255)},{round(c.get('g', 0) * 255)},{round(c.get('b', 0) * 255)},"
                            f"{round(c.get('a', 1), 2)})")
        for ch in n.get("children", []) or []:
            walk(ch)
    walk(node)
    return {"colores": [h for h, _ in sorted(colors.items(), key=lambda kv: -kv[1])][:16],
            "tipografias": [f for f, _ in sorted(fonts.items(), key=lambda kv: -kv[1])][:10],
            "radios": sorted(radii)[:8], "espaciados": sorted(gaps | pads)[:12], "sombras": sorted(shadows)[:4],
            "nombre": node.get("name", "")}


def _figma_get(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={"X-Figma-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise SystemExit(f"Figma limitó las llamadas (429). Reintenta después de {e.headers.get('Retry-After', '?')} s; "
                             "en el plan gratuito los límites son muy bajos: usa exportaciones PNG con `agentes design ref`.")
        raise SystemExit(f"Error de Figma {e.code}: {e.read()[:300]!r}")


def figma_token() -> str | None:
    import os
    if os.environ.get("FIGMA_TOKEN"):
        return os.environ["FIGMA_TOKEN"]
    p = Path.home() / ".config" / "agentes" / "figma.json"
    if p.exists():
        return json.loads(p.read_text()).get("token")
    return None


def save_figma_token(token: str) -> Path:
    import os
    p = Path.home() / ".config" / "agentes" / "figma.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"token": token}))
    os.chmod(p, 0o600)
    return p


def figma_import(root: Path, url: str, name: str | None = None, token: str | None = None, scale: int = 2) -> dict:
    key, node = parse_figma_url(url)
    if not node:
        raise SystemExit("Falta el nodo: en Figma haz clic derecho en el frame → Copy/Paste as → Copy link to selection.")
    token = token or figma_token()
    if not token:
        raise SystemExit("Falta el token: Figma → Settings → Security → Personal access tokens (scope file_content:read).\n"
                         "Luego: export FIGMA_TOKEN=figd_...  o  agentes design figma --save-token figd_...")
    cache = design_dir(root) / "figma"
    cache.mkdir(exist_ok=True)
    base = f"{key}-{node.replace(':', '-')}"
    data_p, png_p = cache / f"{base}.json", cache / f"{base}.png"
    calls = 0
    if data_p.exists():
        data = json.loads(data_p.read_text())
    else:
        data = _figma_get(f"https://api.figma.com/v1/files/{key}/nodes?ids={urllib.parse.quote(node)}", token)
        calls += 1
        data_p.write_text(json.dumps(data))
    doc = (data.get("nodes", {}).get(node) or {}).get("document")
    if not doc:
        raise SystemExit("Figma no devolvió el nodo (¿tienes acceso al archivo?).")
    if not png_p.exists():
        imgs = _figma_get(f"https://api.figma.com/v1/images/{key}?ids={urllib.parse.quote(node)}&format=png&scale={scale}", token)
        calls += 1
        img_url = (imgs.get("images") or {}).get(node)
        if not img_url:
            raise SystemExit("Figma no pudo renderizar el frame.")
        with urllib.request.urlopen(img_url, timeout=120) as r:
            png_p.write_bytes(r.read())
    tokens = figma_tokens(doc)
    info = add_reference(root, png_p, name or tokens["nombre"] or base, source=url,
                         note="Tokens de Figma: " + json.dumps({k: v for k, v in tokens.items() if v and k != "nombre"},
                                                               ensure_ascii=False))
    info["figma"] = tokens
    info["llamadas_api"] = calls
    (design_dir(root) / "refs" / f"{info['nombre']}.json").write_text(json.dumps(info, indent=2, ensure_ascii=False))
    return info
