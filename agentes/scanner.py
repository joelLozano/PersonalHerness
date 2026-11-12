"""Análisis automático de proyectos existentes + indexado de código en la memoria vectorial."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections import Counter
from pathlib import Path

from .store import Store

IGNORE_DIRS = {".git", "node_modules", ".venv", "venv", "env", "__pycache__", "dist", "build", ".next",
               ".nuxt", "target", ".agentes", ".claude", "coverage", ".idea", ".vscode", "vendor",
               ".turbo", ".cache", ".pytest_cache", ".mypy_cache", "out", "bin", "obj", ".gradle", "Pods"}

LANG_BY_EXT = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".go": "Go", ".rs": "Rust", ".java": "Java", ".kt": "Kotlin",
    ".rb": "Ruby", ".php": "PHP", ".cs": "C#", ".swift": "Swift", ".dart": "Dart", ".vue": "Vue",
    ".svelte": "Svelte", ".c": "C", ".h": "C", ".cpp": "C++", ".hpp": "C++", ".scala": "Scala",
    ".ex": "Elixir", ".exs": "Elixir", ".sql": "SQL", ".css": "CSS", ".scss": "SCSS", ".html": "HTML",
    ".sh": "Shell", ".tf": "Terraform", ".prisma": "Prisma", ".graphql": "GraphQL",
    ".m": "Objective-C", ".mm": "Objective-C++", ".kts": "Kotlin",
}
CODE_EXTS = set(LANG_BY_EXT) | {".md", ".yaml", ".yml", ".toml", ".json", ".xml", ".strings", ".gradle", ".plist"}

# ---- mobile ----
IOS_LIBS = {"alamofire": "Alamofire", "kingfisher": "Kingfisher", "snapkit": "SnapKit", "rxswift": "RxSwift",
            "swift-composable-architecture": "TCA", "swift-snapshot-testing": "SnapshotTesting", "quick": "Quick",
            "nimble": "Nimble", "firebase-ios-sdk": "Firebase", "firebase": "Firebase", "realm": "Realm",
            "lottie": "Lottie", "swinject": "Swinject", "factory": "Factory", "sdwebimage": "SDWebImage", "moya": "Moya",
            "swiftlint": "SwiftLint", "swift-dependencies": "swift-dependencies", "grdb": "GRDB"}
ANDROID_LIBS = {"androidx.compose": "Jetpack Compose", "hilt": "Hilt", "koin": "Koin", "dagger": "Dagger",
                "retrofit": "Retrofit", "okhttp": "OkHttp", "ktor": "Ktor", "androidx.room": "Room", "room-": "Room",
                "kotlinx-coroutines": "Coroutines", "coil": "Coil", "glide": "Glide", "paparazzi": "Paparazzi",
                "roborazzi": "Roborazzi", "robolectric": "Robolectric", "espresso": "Espresso", "turbine": "Turbine",
                "mockk": "MockK", "detekt": "detekt", "ktlint": "ktlint", "firebase": "Firebase",
                "navigation-compose": "Navigation Compose", "kotlinx-serialization": "kotlinx.serialization",
                "moshi": "Moshi", "gson": "Gson", "datastore": "DataStore", "work-runtime": "WorkManager"}

# dependencia -> etiqueta de framework
FRAMEWORKS = {
    "next": "Next.js", "react": "React", "vue": "Vue", "nuxt": "Nuxt", "svelte": "Svelte",
    "@sveltejs/kit": "SvelteKit", "@angular/core": "Angular", "express": "Express", "fastify": "Fastify",
    "@nestjs/core": "NestJS", "hono": "Hono", "vite": "Vite", "tailwindcss": "Tailwind CSS",
    "prisma": "Prisma", "@prisma/client": "Prisma", "drizzle-orm": "Drizzle", "typeorm": "TypeORM",
    "mongoose": "Mongoose", "jest": "Jest", "vitest": "Vitest", "@playwright/test": "Playwright",
    "cypress": "Cypress", "@testing-library/react": "Testing Library", "react-native": "React Native",
    "expo": "Expo", "electron": "Electron", "@supabase/supabase-js": "Supabase", "firebase": "Firebase",
    "zod": "Zod", "redux": "Redux", "@reduxjs/toolkit": "Redux Toolkit", "zustand": "Zustand",
    "@tanstack/react-query": "TanStack Query", "@mui/material": "Material UI", "@chakra-ui/react": "Chakra UI",
    "django": "Django", "fastapi": "FastAPI", "flask": "Flask", "sqlalchemy": "SQLAlchemy", "pydantic": "Pydantic",
    "pytest": "pytest", "celery": "Celery", "alembic": "Alembic", "langchain": "LangChain",
    "gin-gonic/gin": "Gin", "labstack/echo": "Echo", "gofiber/fiber": "Fiber",
    "actix-web": "Actix", "axum": "Axum", "tokio": "Tokio", "rails": "Rails", "laravel/framework": "Laravel",
    "spring-boot": "Spring Boot",
}


def _run(cmd: list[str], cwd: Path, timeout: int = 15) -> str:
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except Exception:
        return ""


def list_files(root: Path) -> list[Path]:
    """Archivos del proyecto respetando .gitignore cuando hay git."""
    out = _run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], root)
    if out:
        files = [root / f for f in out.splitlines()]
        return [f for f in files if f.is_file() and not (set(f.relative_to(root).parts) & IGNORE_DIRS)]
    files = []
    for p in root.rglob("*"):
        if p.is_file() and not (set(p.relative_to(root).parts) & IGNORE_DIRS):
            files.append(p)
    return files


def _read(p: Path, limit: int = 200_000) -> str:
    try:
        if p.stat().st_size > limit:
            return ""
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _tree(root: Path, files: list[Path], depth: int = 2) -> list[str]:
    counts: Counter = Counter()
    for f in files:
        parts = f.relative_to(root).parts
        if parts[0] in (".kiro", ".claude", ".github", ".cursor", ".windsurf"):
            continue
        for d in range(1, min(depth, len(parts) - 1) + 1):
            counts["/".join(parts[:d]) + "/"] += 1
    return [f"{k} ({v} archivos)" for k, v in sorted(counts.items())][:60]


ROLES = [
    ("API / rutas", r"(^|/)(api|routes?|controllers?|endpoints?|handlers?|resolvers?|graphql)(/|$)"),
    ("páginas / vistas", r"(^|/)(pages|app|views?|screens?|routes)(/|$)"),
    ("componentes UI", r"(^|/)(components?|ui|widgets?|layouts?)(/|$)"),
    ("datos / modelos", r"(^|/)(models?|entities|schemas?|prisma|db|database|migrations?|repositor(y|ies)|dao|data|persistence|storage)(/|$)"),
    ("servicios / lógica", r"(^|/)(services?|domain|core|use-?cases?|business|lib)(/|$)"),
    ("autenticación", r"(^|/)(auth|authentication|login|session|security)(/|$)"),
    ("estado (frontend)", r"(^|/)(store|stores|state|redux|context|hooks?)(/|$)"),
    ("utilidades", r"(^|/)(utils?|helpers?|common|shared)(/|$)"),
    ("estilos", r"(^|/)(styles?|css|theme|tokens?)(/|$)"),
    ("pruebas", r"(^|/)(tests?|__tests__|spec|specs|e2e|cypress|playwright)(/|$)"),
    ("configuración / infra", r"(^|/)(config|configs?|infra|deploy|docker|k8s|terraform|\.github)(/|$)"),
    ("scripts / jobs", r"(^|/)(scripts?|jobs?|workers?|cron|tasks?|queues?)(/|$)"),
    ("design system / tema", r"(^|/)(design-?system|ds|ui-?kit|core-?ui|ui-?components|theme)(/|$)"),
    ("pantallas", r"(^|/)(screens?|scenes?|features?|feature)(/|$)"),
    ("ViewModels / presentación", r"(^|/)(view-?models?|presenters?|presentation)(/|$)"),
    ("navegación", r"(^|/)(navigation|coordinators?|routers?|routing|nav)(/|$)"),
    ("red / networking", r"(^|/)(network|networking|remote|api-?client)(/|$)"),
    ("inyección de dependencias", r"(^|/)(di|injection)(/|$)"),
    ("recursos", r"(^|/)(resources|res|assets\.xcassets|values|drawable)(/|$)"),
]
ENTRY = (r"(^|/)(main|index|app|server|manage|wsgi|asgi|program|cli)\.(py|ts|tsx|js|jsx|go|rs|java|kt|rb|php|cs)$"
         r"|(^|/)(AppDelegate|SceneDelegate|\w+App)\.swift$|(^|/)(MainActivity|\w+Application)\.kt$|(^|/)src/main/AndroidManifest\.xml$")
SUFFIX_ROLES = [("pantallas", r"(Screen|View|ViewController|Activity|Fragment|Page)$"),
                ("ViewModels / presentación", r"(ViewModel|Presenter|Store|Reducer)$"),
                ("datos / modelos", r"(Repository|Dao|Entity|Model|DataSource)$"),
                ("red / networking", r"(Api|Client|Service|Endpoint)$"),
                ("entrada de la app", r"^(MainActivity|AppDelegate|SceneDelegate|\w+App|\w+Application)$")]
BUILD_FILES = {"build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts", "Package.swift", "Podfile",
               "Fastfile", "Project.swift"}
ANDROID_SRC = re.compile(r"^(.*?/src/(?:main|debug|release)/(?:java|kotlin))/(.+)$")


def code_map(root: Path, files: list[Path], max_lines: int = 18) -> list[str]:
    """Qué hay en cada carpeta del código: rol probable, tamaño y archivos de ejemplo."""
    groups: dict[str, list[str]] = {}
    rels = [f.relative_to(root).as_posix() for f in files if f.suffix.lower() in LANG_BY_EXT]
    # Android: los paquetes (com/empresa/app/...) son profundos; agrupa por la carpeta tras la raíz común del módulo
    pkg_root: dict[str, str] = {}
    by_src: dict[str, list[str]] = {}
    for r in rels:
        m = ANDROID_SRC.match(r)
        if m:
            by_src.setdefault(m.group(1), []).append(m.group(2))
    for base, paths in by_src.items():
        dirs = [p.rsplit("/", 1)[0] if "/" in p else "" for p in paths]
        common = os.path.commonpath(dirs) if all(dirs) else ""
        pkg_root[base] = f"{base}/{common}".rstrip("/")
    for f in files:
        rel = f.relative_to(root).as_posix()
        if f.suffix.lower() not in LANG_BY_EXT or rel.startswith((".kiro/", ".claude/", ".github/")) \
                or f.name in BUILD_FILES:
            continue
        m = ANDROID_SRC.match(rel)
        if m and m.group(1) in pkg_root:
            sub = rel[len(pkg_root[m.group(1)]) + 1:]
            key = pkg_root[m.group(1)] + ("/" + sub.split("/")[0] if "/" in sub else "")
            groups.setdefault(key, []).append(rel)
            continue
        parts = rel.split("/")
        depth = 3 if parts[0] in ("src", "app", "packages", "apps", "lib", "internal", "pkg") else 2
        key = "/".join(parts[:min(len(parts) - 1, depth)]) or "."
        groups.setdefault(key, []).append(rel)
    lines = []
    for key, rels in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:max_lines]:
        segs = [x for x in key.split("/") if x and x != "."]
        roles = []
        for seg in reversed(segs[-2:]):  # el rol lo da la carpeta final (no "app/" o "core/" como módulo)
            roles = [name for name, pat in ROLES if re.search(pat, "/" + seg + "/", re.I)]
            if roles:
                break
        if not roles:  # inferir por sufijos de los nombres de archivo
            names = [Path(r).stem for r in rels]
            for name, rx in SUFFIX_ROLES:
                if sum(bool(re.search(rx, n)) for n in names) >= max(1, len(names) // 3):
                    roles.append(name)
            roles = roles[:2]
        sample = ", ".join(sorted({Path(r).name for r in rels}, key=len)[:4])
        lines.append(f"{key}/ — {' + '.join(roles[:2]) or 'código'} ({len(rels)} arch.; ej. {sample})")
    entries = sorted({f.relative_to(root).as_posix() for f in files if re.search(ENTRY, f.relative_to(root).as_posix())},
                     key=lambda r: (r.count("/"), r))[:6]
    if entries:
        lines.append("Puntos de entrada: " + ", ".join(entries))
    return lines


def mobile_scan(root: Path, files: list[Path], rel: set[str]) -> dict:
    """Detecta proyectos iOS y Android: UI, versiones mínimas, librerías, esquemas/módulos y comandos reales."""
    out: dict = {}
    swift = [f for f in files if f.suffix == ".swift"]
    pbx = [f for f in files if f.name == "project.pbxproj"]
    pkg = root / "Package.swift"
    if swift or pbx or pkg.exists() or "Podfile" in rel:
        ios: dict = {}
        ui = {"SwiftUI": 0, "UIKit": 0}
        for f in swift[:400]:
            t = _read(f, 80_000)
            ui["SwiftUI"] += "import SwiftUI" in t
            ui["UIKit"] += "import UIKit" in t
        ios["ui"] = "SwiftUI + UIKit" if ui["SwiftUI"] and ui["UIKit"] else ("SwiftUI" if ui["SwiftUI"] else ("UIKit" if ui["UIKit"] else "?"))
        targets = []
        for f in pbx:
            targets += re.findall(r"IPHONEOS_DEPLOYMENT_TARGET = ([\d.]+);", _read(f, 3_000_000))
        targets += re.findall(r"\.iOS\(\.v(\d+)", _read(pkg))
        if targets:
            ios["min_ios"] = min(targets, key=lambda v: [int(x) for x in v.split(".")])
        projects = sorted({f.parent.name for f in pbx if f.parent.suffix == ".xcodeproj"})
        workspaces = sorted({p.split("/")[0] for p in rel if ".xcworkspace/" in p and "xcodeproj" not in p.split("/")[0]})
        schemes = sorted({Path(p).stem for p in rel if p.endswith(".xcscheme")})
        ios.update({"proyectos": projects, "workspaces": workspaces, "esquemas": schemes[:8]})
        libs = set()
        deps_text = " ".join(_read(root / n).lower() for n in ("Package.swift", "Package.resolved", "Podfile.lock", "Cartfile"))
        deps_text += " ".join(_read(root / p).lower() for p in rel if p.endswith("Package.resolved"))
        for k, v in IOS_LIBS.items():
            if re.search(rf"[\"/ ]{re.escape(k)}[\"/. ]", deps_text):
                libs.add(v)
        ios["librerias"] = sorted(libs)
        ios["gestor"] = [g for g, cond in (("SPM", pkg.exists() or any(p.endswith("Package.resolved") for p in rel)),
                                            ("CocoaPods", "Podfile" in rel), ("Carthage", "Cartfile" in rel),
                                            ("Tuist", "Project.swift" in rel)) if cond]
        scheme = schemes[0] if schemes else (projects[0].replace(".xcodeproj", "") if projects else "<Esquema>")
        container = f"-workspace {workspaces[0]}" if workspaces else (f"-project {projects[0]}" if projects else "")
        dest = "-destination 'platform=iOS Simulator,name=iPhone 16'"
        ios["comandos"] = {"build": f"xcodebuild {container} -scheme {scheme} {dest} build".replace("  ", " "),
                           "test": f"xcodebuild {container} -scheme {scheme} {dest} test".replace("  ", " ")}
        if ".swiftlint.yml" in rel:
            ios["comandos"]["lint"] = "swiftlint"
        out["ios"] = ios
    gradle_settings = next((root / n for n in ("settings.gradle.kts", "settings.gradle") if (root / n).exists()), None)
    manifests = [p for p in rel if p.endswith("AndroidManifest.xml")]
    if manifests or (gradle_settings and "android" in " ".join(_read(f) for f in files if f.name.startswith("build.gradle")).lower()):
        an: dict = {}
        st = _read(gradle_settings) if gradle_settings else ""
        modules = re.findall(r"['\"](:[\w:-]+)['\"]", " ".join(re.findall(r"include\s*\(?([^\n]+)", st)))
        an["modulos"] = modules[:30]
        gtext = " ".join(_read(f) for f in files if f.name in ("build.gradle", "build.gradle.kts"))
        toml = _read(root / "gradle" / "libs.versions.toml")
        alltext = (gtext + " " + toml).lower()
        for key, name in (("min_sdk", "minsdk"), ("target_sdk", "targetsdk"), ("compile_sdk", "compilesdk")):
            vals = re.findall(name + r'(?:version)?\s*(?:=|:)?\s*\(?\s*"?(\d+)', alltext)
            if vals:
                an[key] = min(vals, key=int) if key == "min_sdk" else max(vals, key=int)
        kt = [f for f in files if f.suffix == ".kt"]
        compose = "androidx.compose" in alltext or "compose = true" in alltext or any("@Composable" in _read(f, 60_000) for f in kt[:200])
        views = sum(1 for p in rel if "/res/layout" in p and p.endswith(".xml"))
        an["ui"] = "Compose + Views" if compose and views else ("Jetpack Compose" if compose else ("Views XML" if views else "?"))
        an["librerias"] = sorted({v for k, v in ANDROID_LIBS.items() if k in alltext})
        app_mod = next((m for m in modules if m in (":app", ":androidApp")), ":app")
        cmds = {"build": f"./gradlew {app_mod}:assembleDebug", "test": "./gradlew testDebugUnitTest",
                "ui-test": "./gradlew connectedDebugAndroidTest", "lint": "./gradlew lint"}
        if "detekt" in alltext:
            cmds["detekt"] = "./gradlew detekt"
        if "ktlint" in alltext:
            cmds["ktlint"] = "./gradlew ktlintCheck"
        an["comandos"] = cmds
        out["android"] = an
    fastfile = next((root / p for p in rel if p.endswith("Fastfile")), None)
    if fastfile:
        out["fastlane_lanes"] = re.findall(r"lane\s+:(\w+)", _read(fastfile))[:15]
    return out


def scan(root: Path) -> dict:
    files = list_files(root)
    rel = {str(f.relative_to(root)) for f in files}
    report: dict = {"root": str(root), "total_files": len(files)}

    langs: Counter = Counter()
    loc: Counter = Counter()
    for f in files:
        lang = LANG_BY_EXT.get(f.suffix.lower())
        if lang:
            langs[lang] += 1
            if f.stat().st_size < 400_000:
                loc[lang] += _read(f).count("\n")
    report["languages"] = {k: {"files": v, "lines": loc[k]} for k, v in langs.most_common(12)}

    frameworks, scripts, managers, deps_all = set(), {}, set(), {}
    # Node
    for pj in [f for f in files if f.name == "package.json" and "node_modules" not in str(f)][:10]:
        try:
            data = json.loads(_read(pj))
        except Exception:
            continue
        deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        deps_all[str(pj.relative_to(root))] = sorted(deps)[:80]
        frameworks |= {FRAMEWORKS[d] for d in deps if d in FRAMEWORKS}
        if data.get("scripts"):
            scripts[str(pj.relative_to(root))] = data["scripts"]
    for lock, mgr in (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"), ("package-lock.json", "npm"),
                      ("bun.lockb", "bun"), ("bun.lock", "bun"), ("poetry.lock", "poetry"), ("uv.lock", "uv"),
                      ("Pipfile.lock", "pipenv"), ("Cargo.lock", "cargo"), ("go.sum", "go modules"),
                      ("Gemfile.lock", "bundler"), ("composer.lock", "composer")):
        if lock in rel:
            managers.add(mgr)
    # Python
    py_text = " ".join(_read(root / n) for n in ("pyproject.toml", "requirements.txt", "requirements-dev.txt",
                                                 "Pipfile", "setup.py") if (root / n).exists()).lower()
    for dep, fw in FRAMEWORKS.items():
        if re.search(rf"(^|[\s\"'\[,]){re.escape(dep)}([\s\"'=<>~\],;]|$)", py_text):
            frameworks.add(fw)
    # Go / Rust / otros
    gomod = _read(root / "go.mod")
    cargo = _read(root / "Cargo.toml")
    other = gomod + cargo + _read(root / "Gemfile") + _read(root / "composer.json") + _read(root / "pom.xml") + _read(root / "build.gradle")
    for dep, fw in FRAMEWORKS.items():
        if "/" in dep or dep in ("actix-web", "axum", "tokio", "rails", "spring-boot"):
            if dep in other:
                frameworks.add(fw)
    mob = mobile_scan(root, files, rel)
    if mob:
        report["mobile"] = mob
        for plat in ("ios", "android"):
            if plat in mob:
                frameworks |= set(mob[plat].get("librerias", []))
                if mob[plat].get("ui", "?") != "?":
                    frameworks |= set(mob[plat]["ui"].replace(" + ", ",").replace("Views XML", "Android Views").split(","))
                scripts[plat] = mob[plat]["comandos"]
        if mob.get("fastlane_lanes"):
            scripts["fastlane"] = {l: f"bundle exec fastlane {l}" for l in mob["fastlane_lanes"]}
    report["frameworks"] = sorted(frameworks)
    report["package_managers"] = sorted(managers)
    report["scripts"] = scripts
    report["dependencies"] = deps_all

    mk = _read(root / "Makefile")
    if mk:
        report["make_targets"] = re.findall(r"^([a-zA-Z0-9_.-]+):(?!=)", mk, re.M)[:30]

    infra = []
    checks = {
        "Dockerfile": "Docker", "docker-compose.yml": "Docker Compose", "docker-compose.yaml": "Docker Compose",
        "compose.yaml": "Docker Compose", "vercel.json": "Vercel", "netlify.toml": "Netlify", "fly.toml": "Fly.io",
        "render.yaml": "Render", "serverless.yml": "Serverless", "Procfile": "Heroku", "k8s": "Kubernetes",
        ".gitlab-ci.yml": "GitLab CI", "Jenkinsfile": "Jenkins", "terraform": "Terraform",
    }
    for name, label in checks.items():
        if name in rel or any(r.startswith(name + "/") for r in rel):
            infra.append(label)
    workflows = sorted(r for r in rel if r.startswith(".github/workflows/"))
    if workflows:
        infra.append("GitHub Actions")
        report["ci_workflows"] = workflows
    report["infra"] = sorted(set(infra))

    tests = [r for r in rel if re.search(r"(^|/)(tests?|__tests__|spec|e2e|androidTest|\w+Tests|\w+UITests)(/|$)|Tests?\.swift$|Test\.kt$|[._-](test|spec)\.[a-z]+$|^test_.*\.py$|/test_[^/]*\.py$", r)]
    report["test_files"] = len(tests)
    report["test_sample"] = tests[:10]

    lint = [n for n in (".swiftlint.yml", ".swiftformat", "detekt.yml", "config/detekt/detekt.yml", ".eslintrc", ".eslintrc.js", ".eslintrc.json", "eslint.config.js", "eslint.config.mjs",
                        ".prettierrc", "prettier.config.js", "biome.json", "ruff.toml", ".flake8", "mypy.ini",
                        "tsconfig.json", ".editorconfig", ".pre-commit-config.yaml", "golangci.yml", ".rubocop.yml")
            if n in rel]
    if "pyproject.toml" in rel:
        pp = _read(root / "pyproject.toml")
        lint += [t for t in ("ruff", "black", "mypy", "isort", "pytest") if f"[tool.{t}" in pp]
    report["quality_tools"] = lint

    env_files = [r for r in rel if re.search(r"(^|/)\.env(\.[a-z]+)?$", r)]
    report["env_files"] = env_files
    ex = next((root / r for r in env_files if "example" in r or "sample" in r), None)
    if ex:
        report["env_keys"] = re.findall(r"^([A-Z][A-Z0-9_]+)=", _read(ex), re.M)[:40]
    report["env_committed_warning"] = [r for r in env_files if not re.search(r"example|sample|template", r)]

    todo = Counter()
    for f in files:
        if f.suffix.lower() in LANG_BY_EXT:
            for m in re.findall(r"\b(TODO|FIXME|HACK|XXX)\b", _read(f)):
                todo[m] += 1
    report["todo_markers"] = dict(todo)

    big = sorted(((f.stat().st_size, str(f.relative_to(root))) for f in files if f.suffix.lower() in LANG_BY_EXT),
                 reverse=True)[:8]
    report["largest_source_files"] = [f"{p} ({s // 1024} KB)" for s, p in big]
    report["structure"] = _tree(root, files)
    report["code_map"] = code_map(root, files)

    if (root / ".git").exists():
        report["git"] = {
            "branch": _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], root),
            "commits": _run(["git", "rev-list", "--count", "HEAD"], root),
            "recent": _run(["git", "log", "--oneline", "-15"], root).splitlines(),
            "hot_files": [l.strip() for l in _run(
                ["bash", "-c", "git log --since='6 months ago' --name-only --pretty=format: | grep -v '^$' | sort | uniq -c | sort -rn | head -12"],
                root).splitlines()],
            "uncommitted": len(_run(["git", "status", "--porcelain"], root).splitlines()),
        }
    readme = next((root / r for r in ("README.md", "README.rst", "README.txt", "readme.md") if r in rel), None)
    if readme:
        report["readme_head"] = _read(readme)[:1500]
    return report


def report_to_text(r: dict) -> str:
    L = [f"# Escaneo de {r['root']}", f"Archivos: {r['total_files']}"]
    if r.get("languages"):
        L.append("Lenguajes: " + ", ".join(f"{k} ({v['files']} arch, {v['lines']} líneas)" for k, v in r["languages"].items()))
    for key, label in (("frameworks", "Frameworks/librerías"), ("package_managers", "Gestores"),
                       ("infra", "Infra/CI"), ("quality_tools", "Calidad (lint/format/types)")):
        if r.get(key):
            L.append(f"{label}: {', '.join(r[key])}")
    mob = r.get("mobile") or {}
    if mob.get("ios"):
        i = mob["ios"]
        L.append(f"iOS: UI {i.get('ui')} · mínimo iOS {i.get('min_ios', '?')} · {', '.join(i.get('gestor', [])) or '?'} · "
                 f"esquemas {', '.join(i.get('esquemas', [])) or '?'}")
    if mob.get("android"):
        a = mob["android"]
        L.append(f"Android: UI {a.get('ui')} · minSdk {a.get('min_sdk', '?')} · targetSdk {a.get('target_sdk', '?')} · "
                 f"módulos {', '.join(a.get('modulos', [])) or '?'}")
    if r.get("scripts"):
        for f, s in r["scripts"].items():
            L.append(f"Scripts ({f}): " + "; ".join(f"{k}=`{v}`" for k, v in list(s.items())[:15]))
    if r.get("make_targets"):
        L.append("Make: " + ", ".join(r["make_targets"]))
    L.append(f"Archivos de test: {r.get('test_files', 0)}" + (f" (ej. {', '.join(r['test_sample'][:4])})" if r.get("test_sample") else ""))
    if r.get("env_keys"):
        L.append("Variables de entorno: " + ", ".join(r["env_keys"]))
    if r.get("env_committed_warning"):
        L.append("⚠️ Archivos .env sin 'example' versionados/presentes: " + ", ".join(r["env_committed_warning"]))
    if r.get("todo_markers"):
        L.append("Marcadores de deuda: " + ", ".join(f"{k}={v}" for k, v in r["todo_markers"].items()))
    if r.get("largest_source_files"):
        L.append("Archivos fuente más grandes: " + ", ".join(r["largest_source_files"][:5]))
    if r.get("git"):
        g = r["git"]
        L.append(f"Git: rama {g['branch']}, {g['commits']} commits, {g['uncommitted']} cambios sin commit")
        if g["recent"]:
            L.append("Commits recientes:\n  " + "\n  ".join(g["recent"][:10]))
        if g["hot_files"]:
            L.append("Archivos más modificados (6 meses):\n  " + "\n  ".join(g["hot_files"][:8]))
    if r.get("code_map"):
        L.append("Mapa del código:\n  " + "\n  ".join(r["code_map"]))
    elif r.get("structure"):
        L.append("Estructura:\n  " + "\n  ".join(r["structure"][:40]))
    return "\n".join(L)


def save_scan(store: Store, r: dict) -> None:
    """Guarda hechos del escaneo como memorias (reemplaza el escaneo anterior)."""
    old = [m["id"] for m in store.list("scan", 500)]
    store.delete(old)
    facts = []
    if r.get("languages"):
        facts.append("Lenguajes principales: " + ", ".join(r["languages"]))
    if r.get("frameworks"):
        facts.append("Stack detectado: " + ", ".join(r["frameworks"]))
    if r.get("package_managers"):
        facts.append("Gestores de paquetes: " + ", ".join(r["package_managers"]))
    for f, s in (r.get("scripts") or {}).items():
        facts.append(f"Comandos del proyecto en {f}: " + "; ".join(f"{k} => {v}" for k, v in s.items()))
    if r.get("make_targets"):
        facts.append("Targets de Makefile: " + ", ".join(r["make_targets"]))
    if r.get("infra"):
        facts.append("Infraestructura/CI: " + ", ".join(r["infra"]))
    mob = r.get("mobile") or {}
    if mob.get("ios"):
        i = mob["ios"]
        facts.append(f"iOS: UI {i.get('ui')}, iOS mínimo {i.get('min_ios', '?')}, gestor {', '.join(i.get('gestor', [])) or '?'}, "
                     f"esquemas {', '.join(i.get('esquemas', [])) or '?'}, librerías {', '.join(i.get('librerias', [])) or '-'}.")
    if mob.get("android"):
        a = mob["android"]
        facts.append(f"Android: UI {a.get('ui')}, minSdk {a.get('min_sdk', '?')}, targetSdk {a.get('target_sdk', '?')}, "
                     f"módulos {', '.join(a.get('modulos', [])[:12]) or '?'}, librerías {', '.join(a.get('librerias', [])) or '-'}.")
    if r.get("quality_tools"):
        facts.append("Herramientas de calidad configuradas: " + ", ".join(r["quality_tools"]))
    facts.append(f"El proyecto tiene {r.get('test_files', 0)} archivos de prueba.")
    if r.get("env_keys"):
        facts.append("Variables de entorno esperadas: " + ", ".join(r["env_keys"]))
    if r.get("structure") and not r.get("code_map"):
        facts.append("Estructura de carpetas: " + "; ".join(r["structure"][:30]))
    for fact in facts:
        store.add(fact, kind="scan", source="agentes scan", _vector=True)
    if r.get("code_map"):
        store.add("Mapa del código:\n" + "\n".join(f"- {l}" for l in r["code_map"]), kind="scan",
                  tags="mapa", source="agentes scan")
    (store.dir / "scan.json").write_text(json.dumps(r, ensure_ascii=False, indent=2))
    refresh_catalog(store, Path(store.root))


def refresh_catalog(store: Store, root: Path) -> list[str]:
    """Regenera la memoria con el catálogo de features (desde la tabla de símbolos; no lee archivos)."""
    from . import features
    try:
        from .ds import configured_paths
        ds_paths = [p for ps in configured_paths(root).values() for p in ps]
    except Exception:
        ds_paths = []
    lines = features.catalog(store, ds_paths)
    text = "Features del proyecto (capas detectadas en el código):\n" + "\n".join(lines) if lines else ""
    old = store.db.execute("SELECT id, text FROM memories WHERE kind='scan' AND tags='features'").fetchall()
    if [r[1] for r in old] == ([text] if text else []):
        return lines  # sin cambios: no reescribir la memoria
    if old:
        store.delete([r[0] for r in old])
    if text:
        store.add(text, kind="scan", tags="features", source="agentes index")
    return lines


# ------------------------------------------------------------------------------ indexado
def _chunks(text: str, size: int = 60, overlap: int = 10) -> list[tuple[int, str]]:
    lines = text.splitlines()
    if len(lines) <= size:
        return [(1, text)]
    out, i = [], 0
    while i < len(lines):
        out.append((i + 1, "\n".join(lines[i:i + size])))
        i += size - overlap
    return out


def _indexable(root: Path, f: Path) -> bool:
    from .security import is_sensitive
    rel = f.relative_to(root).as_posix()
    if is_sensitive(rel):
        return False  # credenciales, llaves, keystores, configs de servicios: nunca a la memoria
    if rel.startswith(".kiro/"):
        return rel.startswith(".kiro/specs/")  # de .kiro solo se indexan las specs
    return True


def index_code(store: Store, root: Path, max_file_kb: int = 150, progress=None) -> dict:
    files = [f for f in list_files(root)
             if _indexable(root, f) and f.suffix.lower() in CODE_EXTS and f.stat().st_size <= max_file_kb * 1024
             and not f.name.endswith((".lock", "-lock.json", ".min.js", ".map"))
             and f.name not in ("package-lock.json", "pnpm-lock.yaml", "yarn.lock", "CLAUDE.md", ".mcp.json", "AGENTS.md")]
    from . import features
    known = {r["path"]: (r["hash"], r["chunk_ids"]) for r in store.db.execute("SELECT * FROM files")}
    ver = store.db.execute("SELECT value FROM meta WHERE key='symbols_version'").fetchone()
    backfill = not ver or ver[0] != features.SYMBOLS_VERSION  # índice de símbolos nuevo o con otra versión: rehacer
    if backfill:
        store.db.execute("DELETE FROM symbols")
    seen, added, skipped, removed = set(), 0, 0, 0
    for n, f in enumerate(files):
        rel = f.relative_to(root).as_posix()
        seen.add(rel)
        text = _read(f)
        if not text.strip():
            continue
        h = hashlib.sha256(text.encode()).hexdigest()[:24]
        if rel in known and known[rel][0] == h:
            if backfill:
                features.save(store, rel, features.extract(rel, text))
            skipped += 1
            continue
        features.save(store, rel, features.extract(rel, text))
        if rel in known:
            store.delete(json.loads(known[rel][1]))
        kind = "spec" if rel.startswith(".kiro/specs/") else "code"
        items = [{"text": f"// {rel}:{start}\n{chunk}", "kind": kind, "source": f"{rel}:{start}",
                  "tags": LANG_BY_EXT.get(f.suffix.lower(), f.suffix.lstrip("."))}
                 for start, chunk in _chunks(text)]
        ids = store.add_many(items)
        store.db.execute("INSERT OR REPLACE INTO files(path,hash,chunk_ids,indexed_at) VALUES (?,?,?,strftime('%s','now'))",
                         (rel, h, json.dumps(ids)))
        store.db.commit()
        added += 1
        if progress and n % 25 == 0:
            progress(n, len(files))
    for rel, (_, ids) in known.items():
        if rel not in seen:
            store.delete(json.loads(ids))
            store.db.execute("DELETE FROM files WHERE path=?", (rel,))
            store.db.execute("DELETE FROM symbols WHERE path=?", (rel,))
            removed += 1
    store.db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('symbols_version', ?)", (features.SYMBOLS_VERSION,))
    store.db.commit()
    feats = refresh_catalog(store, root)
    n_syms = store.db.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
    return {"files": len(files), "indexed": added, "unchanged": skipped, "removed": removed, "symbols": n_syms,
            "features": len([l for l in feats if not l.startswith("- (+")])}
