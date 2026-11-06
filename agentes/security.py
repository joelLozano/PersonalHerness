"""Controles de seguridad del harness.

- Archivos sensibles: nunca se indexan (credenciales, llaves, keystores, perfiles de firma, configs de servicios).
- Redacción: antes de guardar cualquier texto en la memoria se reemplazan secretos conocidos por «REDACTADO».
- Instrucciones sospechosas: lo que un agente intenta guardar en memoria no puede parecer una orden peligrosa
  (descargar y ejecutar scripts, ignorar instrucciones, exfiltrar datos...), porque la memoria vuelve al contexto.
- Confianza: las personalizaciones versionadas en un repo (team.local.yaml, requisitos.conf) pueden cambiar los
  prompts de los agentes o ejecutar comandos; se piden confirmar la primera vez y cada vez que cambian.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

SENSITIVE_NAME = re.compile(
    r"(?i)(^|/)("
    r"\.env(\.(?!example$|sample$|template$|dist$)[\w.-]+)?"            # .env, .env.local ... (no .env.example)
    r"|[^/]*\.(pem|key|p8|p12|pfx|jks|keystore|mobileprovision|provisionprofile|cer|crt|der|asc|gpg|kdbx|tfstate|tfvars)"
    r"|id_(rsa|dsa|ecdsa|ed25519)(\.pub)?|known_hosts|\.netrc|\.npmrc|\.pypirc|\.git-credentials|\.htpasswd"
    r"|credentials(\.[\w]+)?|secrets?(\.[\w.]+)?|[^/]*\.secrets?\.[\w]+|service[-_]?account[^/]*\.json"
    r"|google-services\.json|GoogleService-Info\.plist|local\.properties|keystore\.properties|signing\.properties"
    r"|auth\.json|\.aws/[^/]+|\.ssh/[^/]+|\.docker/config\.json"
    r")$")

REDACT = "«REDACTADO»"
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(-----END [A-Z ]*PRIVATE KEY-----|$)"),
    re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"),                                    # AWS access key id
    re.compile(r"\b(sk|rk|pk)_(live|test)_[0-9A-Za-z]{10,}\b"),                     # Stripe
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}\b"),                                     # Google API key
    re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[0-9A-Za-z]{30,}\b|\bgithub_pat_[0-9A-Za-z_]{40,}\b"),  # GitHub
    re.compile(r"\bxox[abprs]-[0-9A-Za-z-]{10,}\b"),                                # Slack
    re.compile(r"\bglpat-[0-9A-Za-z_\-]{20,}\b"),                                   # GitLab
    re.compile(r"\bfigd_[0-9A-Za-z_\-]{20,}\b"),                                    # Figma
    re.compile(r"\bsk-(ant-|proj-)?[0-9A-Za-z_\-]{20,}\b"),                         # claves de APIs de IA
    re.compile(r"\beyJ[0-9A-Za-z_\-]{10,}\.eyJ[0-9A-Za-z_\-]{10,}\.[0-9A-Za-z_\-]{10,}\b"),  # JWT
]
URL_CREDS = re.compile(r"\b([a-z][a-z0-9+.-]*://)[^\s:/@]+:[^\s/@]{3,}@")             # usuario:password@host
GRADLE_PW = re.compile(r"(?i)\b(\w*(password|secret|token|apikey|api_key)\w*)\s+([\"'])([^\"']{6,})\3")
ASSIGN = re.compile(
    r"""(?ix)
    (["']?[\w.-]*(secret|password|passwd|pwd|token|api[_-]?key|apikey|client[_-]?secret|private[_-]?key|access[_-]?key|
     auth[_-]?key|signing[_-]?key|store[_-]?password|key[_-]?password)[\w.-]*["']?\s*[:=]\s*)
    (["']?)([^\s"',;}{]{8,})(\3)""")
PLACEHOLDER = re.compile(r"(?i)^(\$\{?[\w.]+\}?|<[^>]+>|x{4,}|\*{4,}|changeme|your[_-].*|example.*|placeholder.*|"
                         r"process\.env\.|os\.environ|getenv|BuildConfig\.|System\.getenv|ProcessInfo|Bundle\.main).*")

SUSPICIOUS = [
    (r"(curl|wget|iwr|invoke-webrequest)\b[^\n]*\|\s*(ba|z)?sh\b", "descarga y ejecuta un script"),
    (r"\b(ignore|ignora|olvida|disregard)\b[^\n]{0,40}\b(previous|anteriores|instrucciones|instructions|reglas|system)", "intenta anular instrucciones"),
    (r"\brm\s+-rf\s+(/|~|\$HOME|\*)", "borrado masivo"),
    (r"\b(base64\s+-d|eval\s*\(|exec\s*\()[^\n]*(curl|http)", "ejecución de código remoto"),
    (r"\b(exfiltra|envía|send|post|upload|sube)\b[^\n]{0,60}\b(secret|secreto|token|credencial|credential|\.env|clave|password)", "posible exfiltración"),
    (r"\b(desactiva|disable|deshabilita|salta|skip|bypass)\b[^\n]{0,40}\b(seguridad|security|review|revisi[oó]n|ds check|tests?|hooks?)", "desactiva controles"),
    (r"\bchmod\s+777\b|\bsudo\s+", "privilegios elevados"),
]


def is_sensitive(rel_path: str) -> bool:
    return bool(SENSITIVE_NAME.search(rel_path.replace("\\", "/")))


def redact(text: str) -> tuple[str, int]:
    """Reemplaza secretos conocidos y asignaciones `clave = valor` sensibles. Devuelve (texto, reemplazos)."""
    n = 0
    for rx in SECRET_PATTERNS:
        text, k = rx.subn(REDACT, text)
        n += k

    text, k = URL_CREDS.subn(lambda m: m.group(1) + REDACT + "@", text)
    n += k
    text, k = GRADLE_PW.subn(lambda m: f"{m.group(1)} {m.group(3)}{REDACT}{m.group(3)}", text)
    n += k

    def sub(m):
        nonlocal n
        val = m.group(4)
        if REDACT in val or PLACEHOLDER.match(val) or re.fullmatch(r"[A-Za-z_][\w.]*(\(\))?", val) and not re.search(r"\d", val):
            return m.group(0)  # referencias a variables/config, no secretos literales
        n += 1
        return f"{m.group(1)}{m.group(3)}{REDACT}{m.group(5)}"
    text = ASSIGN.sub(sub, text)
    return text, n


def suspicious(text: str) -> list[str]:
    low = text.lower()
    return [why for rx, why in SUSPICIOUS if re.search(rx, low)]


# ------------------------------------------------------------------------------ confianza
def _trust_file() -> Path:
    return Path.home() / ".config" / "agentes" / "trusted.json"


TRUSTED_FILES = (".agentes/team.local.yaml", ".agentes/requisitos.conf")


def fingerprint(root: Path) -> str:
    h = hashlib.sha256()
    for rel in TRUSTED_FILES:
        p = root / rel
        if p.exists():
            h.update(rel.encode() + b"\0" + p.read_bytes())
    return h.hexdigest()[:24]


def _load_trust() -> dict:
    try:
        return json.loads(_trust_file().read_text())
    except Exception:
        return {}


def mark_trusted(root: Path) -> None:
    """Registra el estado actual de las personalizaciones como confiable (las escribió el harness o el usuario)."""
    data = _load_trust()
    data[str(Path(root).resolve())] = fingerprint(root)
    p = _trust_file()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2))
        p.chmod(0o600)
    except OSError:
        pass


def is_trusted(root: Path) -> bool:
    if not any((root / r).exists() for r in TRUSTED_FILES):
        return True
    return _load_trust().get(str(Path(root).resolve())) == fingerprint(root)


def describe_local(root: Path) -> list[str]:
    """Resumen legible de lo que las personalizaciones del repo cambiarían."""
    import yaml
    out = []
    p = root / ".agentes/team.local.yaml"
    if p.exists():
        try:
            d = yaml.safe_load(p.read_text()) or {}
        except Exception as e:
            return [f"team.local.yaml inválido: {e}"]
        for name, a in (d.get("agents") or {}).items():
            a = a or {}
            what = [k for k in ("prompt", "extra_prompt", "tools", "kiro_tools", "model", "disabled") if k in a]
            text = (a.get("prompt") or "") + (a.get("extra_prompt") or "")
            flags = suspicious(text)
            out.append(f"agente {name}: {', '.join(what) or 'ajustes'}" + (f"  ⚠ {', '.join(flags)}" if flags else ""))
        for name, c in (d.get("commands") or {}).items():
            flags = suspicious((c or {}).get("body", ""))
            out.append(f"comando /{name}" + (f"  ⚠ {', '.join(flags)}" if flags else ""))
        for k in (d.get("settings") or {}):
            out.append(f"ajuste settings.{k}")
        if d.get("kiro"):
            out.append("ajustes de Kiro: " + ", ".join(d["kiro"]))
    r = root / ".agentes/requisitos.conf"
    if r.exists():
        for line in r.read_text().splitlines():
            if "|" in line and not line.strip().startswith("#"):
                f = line.split("|")
                out.append(f"requisito {f[0]}: instala con «{f[4] if len(f) > 4 else '?'}» / «{f[5] if len(f) > 5 else '?'}»")
    return out


def ensure_trusted(root: Path, interactive: bool | None = None) -> bool:
    """Si las personalizaciones del repo son nuevas o cambiaron, muestra qué hacen y pide confirmación."""
    root = Path(root)
    if is_trusted(root):
        return True
    interactive = sys.stdin.isatty() if interactive is None else interactive
    items = describe_local(root)
    print("⚠ Este proyecto trae personalizaciones del equipo que aún no has aprobado (o que cambiaron):", file=sys.stderr)
    for it in items[:40]:
        print(f"   • {it}", file=sys.stderr)
    print("   Revisa .agentes/team.local.yaml y .agentes/requisitos.conf: pueden cambiar los prompts de los agentes "
          "o ejecutar comandos de instalación.", file=sys.stderr)
    if not interactive:
        print("   Sin terminal interactiva: no se aplican. Aprueba con `agentes trust` después de revisarlas.", file=sys.stderr)
        return False
    ans = input("¿Confías en estas personalizaciones y quieres aplicarlas? [s/n] ").strip().lower()
    if ans in ("s", "si", "sí", "y", "yes"):
        mark_trusted(root)
        return True
    return False
