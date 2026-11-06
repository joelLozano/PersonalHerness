# agentes: un equipo de desarrollo para Claude Code

`agentes` instala en cualquier proyecto un equipo de 9 agentes con 14 flujos de trabajo (comandos slash), una memoria persistente con búsqueda vectorial y un tablero de tareas. Todo se define en un solo archivo (`agentes/team.yaml`). La memoria se guarda en una base de datos dentro del proyecto, no en archivos `.md`.

```
Tú ─► Claude Code (orquestador)
        ├─ /kickoff · /onboard · /feature · /fix · /review · /test · /security …
        ├─ Subagentes: tech-lead · product-analyst · ux-designer · backend-dev · frontend-dev
        │              code-reviewer · qa-engineer · security-engineer · devops-engineer
        └─ MCP "agentes" ─► .agentes/agentes.db (SQLite + FTS5/BM25) + .agentes/vectors (ChromaDB)
                             memorias · perfil del proyecto · tareas · código indexado
Hooks: SessionStart inyecta el contexto del proyecto · UserPromptSubmit recupera memorias relevantes (auto-recall)
```

## 1. Instalación (una vez por máquina)

```bash
cd ~/PersonalProyects/Agents
./requisitos.sh         # revisa lo que tienes y te ofrece instalar lo que falte, uno por uno (s/n)
```

`requisitos.sh` muestra el software necesario con la versión mínima y la instalada (✔ instalado · ↑ versión antigua · ✘ falta). Luego te pregunta por cada herramienta faltante: `s` = instalar, `n` = omitir, `t` = instalar todas las que faltan, `q` = salir. Revisa Command Line Tools y Homebrew (en Mac), git, curl, uv, Claude Code, el propio CLI `agentes`, ChromaDB, python3 y gh. Si el CLI `agentes` falta, ejecuta `install.sh` por ti.

También puedes instalar solo el CLI:
```bash
./install.sh            # con base vectorial (ChromaDB)
./install.sh --lite     # sin ChromaDB (solo búsqueda por palabras clave BM25)
```

El script usa `uv` (o `pipx`) y deja el comando `agentes` disponible en todas tus terminales. La instalación es *editable*: si modificas este repositorio, el cambio se aplica a todos tus proyectos al ejecutar `agentes sync` en cada uno.

Requisitos: Python 3.10 o superior y Claude Code (`claude`). La primera vez que se usan los vectores, ChromaDB descarga su modelo de embeddings (unos 80 MB).

Si subes este repositorio a GitHub, también puedes instalarlo desde cualquier máquina con:
`uv tool install "agentes[vector] @ git+https://github.com/<tu-usuario>/agentes"`

## 2. Usarlo en un proyecto

```bash
cd mi-proyecto
agentes install     # genera .claude/agents, .claude/commands, hooks, .mcp.json y .agentes/
claude              # abre Claude Code y acepta el servidor MCP "agentes"
```

**Proyecto nuevo** → `/kickoff una app para reservar canchas de pádel`
Claude te hace el cuestionario por secciones: producto, stack, diseño (colores, estilo, tipografía, modo oscuro, referencias) y calidad. Guarda tus respuestas en el perfil del proyecto. Después el equipo genera los requisitos, el sistema de diseño, la arquitectura y el backlog.
Si prefieres responder en la terminal: `agentes kickoff`.

**Proyecto existente** → `/onboard quiero agregar pagos con Stripe`
1. `agentes install` detecta que el proyecto ya tiene código y lo escanea: stack, scripts, CI, tests, variables de entorno, git, deuda técnica y archivos más modificados. Luego indexa el código en la base vectorial.
2. `/onboard` pide al equipo que explore la arquitectura, las pruebas, la seguridad y el diseño existente.
3. Solo te pregunta lo que el código no responde y propone un plan con tareas.

**Día a día**

| Comando | Qué hace |
|---|---|
| `/feature <desc>` | Flujo completo: requisitos → diseño → plan → implementación → revisión, pruebas y seguridad en paralelo → corrección (hasta 3 ciclos) → cierre |
| `/plan <desc>` | Solo requisitos, diseño técnico y tareas en el tablero |
| `/implement <id\|desc>` | Implementa una tarea con el agente adecuado y la verifica |
| `/fix <bug>` | Reproduce el bug con un test, busca la causa raíz, corrige y verifica |
| `/review [alcance]` | Code review por severidad (🔴/🟠/🟡) con veredicto |
| `/test [alcance]` | QA: diseña, escribe y ejecuta pruebas |
| `/security [alcance]` | Auditoría OWASP, secretos, dependencias e infraestructura, con tareas de remediación |
| `/design <pantalla\|sistema>` | Diseño UX/UI basado en tus preferencias |
| `/tasks` | Tablero de tareas |
| `/remember <x>` · `/recall <q>` | Guardar o buscar en la memoria |
| `/retro` | Consolida la memoria y propone mejoras al harness para ese proyecto |

## 3. Memoria y contexto

- **Una base de datos por proyecto** (`.agentes/agentes.db`), con estos tipos de memoria: `decision`, `convention`, `design`, `requirement`, `bug`, `security`, `learning`, `profile`, `scan`, `code` y `note`.
- **Búsqueda híbrida**: combina vectores (ChromaDB) con BM25 (SQLite FTS5) mediante Reciprocal Rank Fusion. Encuentra tanto por significado como por nombres exactos de funciones o variables. Si ChromaDB no está disponible, sigue funcionando solo con BM25.
- **Contexto automático**: al iniciar cada sesión se inyecta el perfil, el stack, las decisiones, las convenciones, el diseño y las tareas abiertas. En cada prompt se añaden las memorias más relevantes (auto-recall).
- **Protocolo común**: todos los agentes leen el contexto antes de trabajar y guardan solo conocimiento durable al terminar.
- **Compartir con tu equipo**: la base de datos no se sube a git. Usa `agentes memory export` para generar `.agentes/memory.json` y súbelo; quien lo reciba ejecuta `agentes memory import`.

## 4. Comandos para modificar y mejorar el harness

### Instalación y mantenimiento
```bash
agentes install [ruta] [--no-scan] [--no-index]   # instalar en un proyecto
agentes sync                                      # regenerar todo tras cambiar team.yaml / team.local.yaml
agentes doctor                                    # diagnóstico: PATH, MCP, hooks, vectores, estadísticas
agentes requisitos                                # software del harness + del proyecto; instala lo que falte (s/n)
agentes requisitos --check | --yes | --solo-requeridos | --lista
agentes uninstall [--purge]                       # quitar del proyecto (--purge borra también la memoria)
./install.sh                                      # reinstalar el CLI (por ejemplo, tras añadir dependencias)
```

### Requisitos de software
`agentes requisitos` (o `./requisitos.sh --proyecto ruta`) detecta también lo que pide cada proyecto según sus archivos: Node y npm (`package.json`), pnpm, yarn, bun, Docker (`Dockerfile`/compose), Go, Rust, Poetry, Java y Maven, Ruby y Bundler, PHP y Composer, y Make. Usa Homebrew en Mac y apt, dnf, pacman, zypper o apk en Linux. Dentro de Claude, `/onboard` y `/kickoff` ejecutan `agentes requisitos --check` y te avisan si falta algo.

Para requisitos propios de un proyecto, crea `.agentes/requisitos.conf`. Cada línea sigue este formato:
```
# id|nivel|version_min|comando_version|instalar_mac|instalar_linux|cuando|descripcion
psql|requerido|15|psql --version|brew:postgresql@16|pkg:postgresql-client|siempre|Cliente de PostgreSQL
stripe|opcional|-|stripe --version|brew:stripe/stripe-cli/stripe|cmd:echo instala desde stripe.com|siempre|Stripe CLI
```
- **nivel:** `requerido`, `recomendado` u `opcional`.
- **instalar:** `brew:`, `cask:`, `pkg:`, `npm:`, `fn:` o `cmd:`, o `-` si no aplica en ese sistema. En `cmd:` no puedes usar `|`.
- **cuando:** `siempre`, `mac`, `linux` o una lista de archivos que activan el requisito.

Para que un requisito aplique a todos tus proyectos, agrégalo al catálogo de `agentes/requisitos.sh`.

### Equipo de agentes
Los cambios se guardan en `.agentes/team.local.yaml` (solo afectan a ese proyecto) y se sincronizan automáticamente.
```bash
agentes agent list                                        # ver el equipo
agentes agent show frontend-dev                           # ver el prompt final generado
agentes agent add data-engineer -d "Pipelines y SQL" --prompt "Eres..." -m sonnet -t full
agentes agent extend frontend-dev "Usa Server Components salvo interactividad"   # añade instrucciones de proyecto
agentes agent model code-reviewer opus                    # cambiar modelo (opus|sonnet|haiku|inherit)
agentes agent override qa-engineer -e                     # copiar la definición completa a local y editarla
agentes agent disable devops-engineer | enable | reset | remove
```

### Flujos (comandos slash)
```bash
agentes command list
agentes command add release -d "Prepara un release" -b 'Genera changelog y versión semver. $ARGUMENTS'
agentes command disable retro | reset release
```

### Definición del equipo
```bash
agentes team path              # ubicación del team.yaml base y del local
agentes team edit              # editar el team.local.yaml del proyecto (y sincronizar)
agentes team edit --base       # editar el team.yaml base: afecta a TODOS los proyectos al hacer sync
agentes team export            # ver el equipo final ya fusionado
agentes team validate          # validar la definición
agentes questions [new|existing]   # ver los cuestionarios
```
Para cambiar las preguntas del kickoff, edita `questions:` en `team.yaml` (para todos los proyectos) o en `team.local.yaml` (para uno solo).

### Memoria, contexto y tareas
```bash
agentes context                                  # lo que reciben los agentes al iniciar
agentes scan [--json]                            # re-analizar el proyecto
agentes index [--rebuild]                        # re-indexar el código (incremental)
agentes memory search "cómo manejamos auth" [-k decision] [-n 5]
agentes memory add "Precios en centavos" -k convention
agentes memory list [-k decision] · delete <ids> · stats · kinds
agentes memory profile [clave valor --tags seccion]   # ver o editar el perfil
agentes memory export [archivo] · import [archivo] · rebuild
agentes task add "Paginar productos" -a backend-dev -p alta -f catalogo
agentes task list [--all] [-s doing] · set <id> <estado> [nota] · done <ids> · show <id>
```

### Ciclo de mejora continua
1. Después de cada feature grande ejecuta `/retro`: limpia la memoria y propone cambios en `team.local.yaml`.
2. Si una mejora sirve para todos tus proyectos, llévala a `team.yaml` base (`agentes team edit --base`) y ejecuta `agentes sync` en cada proyecto.
3. Si quieres desactivar el auto-recall en un proyecto, añade a `team.local.yaml`:
   ```yaml
   settings:
     auto_recall: false
   ```

## 5. Estructura

```
agentes/
  team.yaml        # ÚNICA fuente de verdad: agentes, flujos, cuestionarios, protocolo, ajustes
  cli.py           # CLI `agentes`
  installer.py     # genera .claude/* , hooks, .mcp.json y el bloque de CLAUDE.md (sin pisar lo tuyo)
  store.py         # memoria: SQLite + FTS5 + ChromaDB (híbrida), perfil, tareas
  scanner.py       # análisis de proyectos existentes + indexado incremental de código
  mcp_server.py    # servidor MCP sin dependencias (memory_*, profile_*, task_*, project_context)
tests/test_harness.py
```

Los archivos `.claude/agents/*.md` y `.claude/commands/*.md` de cada proyecto se generan automáticamente y llevan una marca. `agentes sync` los regenera y elimina los obsoletos. Nunca toca los archivos que tú hayas creado: tus comandos, tus hooks y tu contenido de `CLAUDE.md` se conservan.

Ejecuta los tests con `uv run --extra dev --extra vector pytest -q`.
