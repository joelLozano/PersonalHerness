# agentes: un equipo de desarrollo para Claude Code y Kiro

`agentes` instala en cualquier proyecto (para Claude Code, Kiro o ambos) un equipo de 10 agentes con 15 flujos de trabajo (comandos slash), una memoria persistente con búsqueda vectorial y un tablero de tareas. Todo se define en un solo archivo (`agentes/team.yaml`). La memoria se guarda en una base de datos dentro del proyecto, no en archivos `.md`.

```
Tú ─► Claude Code (orquestador)
        ├─ /kickoff · /onboard · /feature · /fix · /review · /test · /security …
        ├─ Subagentes: tech-lead · product-analyst · ux-designer · backend-dev · frontend-dev
        │              fullstack-dev · code-reviewer · qa-engineer · security-engineer · devops-engineer
        └─ MCP "agentes" ─► .agentes/agentes.db (SQLite + FTS5/BM25) + .agentes/vectors (ChromaDB)
                             memorias · perfil del proyecto · tareas · código indexado
Hooks: SessionStart inyecta el contexto del proyecto · UserPromptSubmit recupera memorias relevantes (auto-recall)
```

El mismo `team.yaml` genera los archivos de cada IDE. Claude Code usa `.claude/` y `CLAUDE.md`; Kiro usa `.kiro/` (ver la sección 4). La memoria, el perfil y las tareas son los mismos para ambos.

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
| `/bench` | Mide si la búsqueda vectorial mejora la memoria de tu proyecto, con preguntas sobre tus propias memorias |

## 3. Triaje: cada tarea con el esfuerzo justo

Cada mensaje que envías pasa por un **triaje automático**. Es determinista: no usa modelo, no gasta tokens y tarda unos 0.1 s. Agrega al mensaje un bloque como este:

```
Triaje agentes: tipo=fix · peso=S
Ruta: Directo en esta sesión: localiza, haz el cambio y ejecuta las pruebas relacionadas. Sin workflows; no delegues.
Código probable (lee solo estos rangos primero): src/lib/pricing.ts:1, src/app/api/orders/route.ts:1
```

| Peso | Ejemplos | Ruta |
|---|---|---|
| **XS** | typo, texto, color, una línea, preguntas | Directo en la sesión, sin sub-agentes ni workflows |
| **S** | fix acotado, campo nuevo, actualización menor | Directo en la sesión con las pruebas relacionadas |
| **M** | feature de varias piezas, versión mayor, refactor | Plan breve en el chat y una verificación con `qa-engineer` |
| **L** | toca varias capas, producción, datos, módulo de pagos | Spec y receta de workflow **solo con tu confirmación**, indicando el costo |
| **XL** | sistema o módulo nuevo de punta a punta | Dividir en entregas; ningún workflow sin confirmación |

- **Tipos detectados:** `feature`, `fix`, `issue`, `update`, `refactor`, `ajuste`, `test`, `docs`, `seguridad` y `pregunta`.
- **Dónde está el código:**
  - El escaneo genera un **mapa del código** (rol de cada carpeta y puntos de entrada) que entra en el contexto de cada sesión.
  - Si no indicas archivos, el triaje sugiere los más probables según el índice. Si mencionas un archivo, parte de ese.
  - Los agentes tienen la herramienta `code_locate` para lo mismo.
- **Índice al día:** el índice se actualiza en segundo plano al iniciar cada sesión (si tiene más de 15 min) y después de cada tarea de una Spec de Kiro.
- **Tu criterio manda:** si dices que una tarea es más grande o más chica, el equipo te hace caso.
- **Ajustes:**
  - Para ver el resultado sin abrir el IDE: `agentes triage "texto"`.
  - Para desactivarlo: `settings.triage: false` en `team.local.yaml`.

## 4. Kiro: Specs, sub-agentes y Workflows

```bash
agentes install --ide kiro      # o --ide ambos; sin --ide se detecta (.kiro/, .claude/, CLI instalados)
agentes ide add kiro            # agregar Kiro a un proyecto que ya tiene el harness
```

| Equipo agentes | En Kiro se genera como |
|---|---|
| 10 agentes | `.kiro/agents/<nombre>.md`: custom agents que Kiro usa como sub-agentes y como agentes de los pasos de Workflows |
| 14 comandos | `.kiro/steering/<nombre>.md` con `inclusion: manual`: se ejecutan escribiendo `/kickoff`, `/feature`… en el chat |
| Instrucciones del orquestador | `.kiro/steering/agentes-equipo.md` con `inclusion: always` |
| Hooks de contexto | `.kiro/hooks/agentes.json` (formato v1): `SessionStart`, `UserPromptSubmit` y `PostTaskExec` (re-indexa las specs) |
| Memoria / tareas (MCP) | servidor `agentes` en `.kiro/settings/mcp.json` (se fusiona con tus servidores) |
| Flujos con revisión | Recetas en `.kiro/workflows/`: `agentes-feature-lite` (5 sesiones como máximo), `agentes-feature` (14), `agentes-bugfix` (5), `agentes-security-audit` y `agentes-onboard` |
| Archivos que Kiro no debe leer | Bloque gestionado en `.kiroignore`: dependencias, builds, archivos lock, `.env`. Solo lo aplica el IDE |

**Importante: con Workflows activado, delegar en un agente del equipo lanza un workflow.** Kiro ejecuta cada delegación a un custom agent como un workflow en segundo plano, que es caro. Por eso, en Kiro:
- Las tareas **XS/S/M las hace el orquestador directamente**, sin delegar.
- **Ningún workflow se lanza sin tu confirmación.**
- En el chat de Kiro, revisa el control **Use workflows** (IDE 1.4.26 o posterior) y déjalo en **Only when asked**. Si nunca usas recetas, apaga Workflows: así la delegación vuelve a ser un sub-agente normal.

**¿Workflows o solo agentes? Recomendación: combinarlos, pero solo para tareas L/XL.**
- **Tareas pequeñas y preguntas:** chat y sub-agentes. Son rápidos y baratos.
- **Planear una feature:** usa Kiro Specs (`requirements.md` / `design.md` / `tasks.md`). Tienen la interfaz de Kiro para ejecutar tareas, y el equipo las redacta con la memoria del proyecto. Las specs se indexan solas en la base de datos.
- **Features medianas:** usa `agentes-feature-lite`: plan breve con tu aprobación → implementación full-stack → revisión + QA, con 2 ciclos como máximo.
- **Features grandes o de riesgo, bugs delicados y auditorías:** usa `agentes-feature`, `agentes-bugfix` y `agentes-security-audit`. Aportan lo que los sub-agentes no tienen: ciclos de revisión (implementar → revisar, QA y seguridad en paralelo → corregir, hasta 2 veces), una pausa para tu aprobación del plan, y ejecución en segundo plano.
- Deja *Workflow use* en **"Only when asked"**, que es el valor por defecto de Kiro: un workflow solo corre cuando lo pides (`/feature` o "ejecuta agentes-feature"). Evita "As much as possible", porque los workflows consumen bastantes más créditos que una sesión normal.
- **Por qué no conviene usar solo sub-agentes:** en Kiro los sub-agentes no ven las Specs y los hooks no se disparan dentro de ellos. El equipo compensa esto con el MCP de memoria, que sí funciona en sub-agentes y en los pasos de los workflows.
- Si no usas Workflows, añade a `.agentes/team.local.yaml`:
  ```yaml
  kiro:
    generate_workflows: false
  ```
  Los comandos (`/feature`, `/fix`…) detectan esto y trabajan solo con sub-agentes.
- **Modelos:** por defecto los agentes heredan el modelo de la sesión de Kiro. Para fijar uno, usa `kiro_model: claude-sonnet-4.6` en el agente dentro de `team.local.yaml`.

## 5. Migrar configuraciones y archivos .md existentes

`agentes install` detecta si el proyecto ya tiene configuraciones de agentes y te ofrece sustituirlas por el equipo (s/n). También puedes hacerlo cuando quieras:

```bash
agentes migrate                          # simulacro: muestra qué se migraría (no cambia nada)
agentes migrate --apply                  # respalda, importa a la BD, sustituye y regenera el equipo
agentes migrate --apply --keep           # importa pero conserva los archivos originales
agentes migrate --include "docs/decisiones/*.md" --apply   # tus propios .md
agentes migrate --backups                # lista los respaldos
agentes migrate --restore [FECHA]        # deshace la migración (la última por defecto)
```

| Detecta | Qué hace |
|---|---|
| `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `.cursorrules`, `.cursor/rules`, `.windsurfrules`, `.clinerules`, `.github/copilot-instructions.md`, steering de Kiro con `always` | Trocea por secciones → **reglas** (siempre presentes en el contexto) o memorias clasificadas (decisión, diseño, seguridad…) |
| Steering de Kiro `fileMatch`/`auto`, `memory-bank/`, `.memory/`, `.ai/`, los `--include` | Memorias clasificadas automáticamente |
| `.claude/agents/*.md`, `.kiro/agents/*.md`/`*.json` | Agentes del equipo en `team.local.yaml`; si el nombre coincide con uno del equipo, sus instrucciones se suman a él |
| `.claude/commands/**/*.md`, steering de Kiro `manual` | Comandos del equipo (si el nombre ya existe, se agrega como `<nombre>-migrado`) |

**Garantías para no afectar el proyecto:**
- Nunca toca código, `README`, documentación, specs de Kiro, tus hooks ni tus servidores MCP.
- Todo se respalda en `.agentes/backup/<fecha>/` antes de cambiar nada.
- La migración se puede deshacer por completo con `--restore`.
- Avisa si algún archivo tiene cambios sin commit.

### Ahorro de tokens
Lo que más consume es la cantidad de sesiones de agente y el código que lee cada una. El harness lo limita así:
- **`/feature` dimensiona primero la tarea:**
  - Pequeña: un solo agente más QA.
  - Mediana: plan breve, `fullstack-dev` y QA.
  - Grande: el flujo completo.
- **Recetas más cortas:**
  - La ligera abre 5 sesiones como máximo. La completa abre 14, antes eran 22.
  - Las ramas sin tareas terminan sin explorar el proyecto.
  - La aprobación del plan se hace dentro del paso de diseño, sin abrir otra sesión.
- **Esfuerzo por paso** (`effortLevel`): alto en diseño y revisión, bajo en los pasos mecánicos.
- **Traspasos cortos:** cada paso responde en 150 palabras o menos y deja los detalles en archivos.
- **Búsquedas compactas:** `memory_search` devuelve 5 fragmentos cortos con `archivo:línea` (antes llegaba a ~3,000 tokens; ahora ~660). Para obtener el texto completo, usa `full: true`.
- **Auto-recall selectivo:**
  - Ignora respuestas cortas ("sí", "continúa") y los comandos.
  - Exige relevancia real con el mensaje.
  - Nunca repite una memoria en la misma sesión.
  - No repite las reglas, porque ya llegan al inicio de la sesión.
- **Prompts y herramientas MCP compactos:** se recortaron entre 20% y 40%.

Ajustes en `.agentes/team.local.yaml`:
```yaml
kiro:
  economy_model: claude-haiku-4.5   # modelo para los pasos mecánicos (usa un id disponible en tu cuenta de Kiro)
  kiroignore: [node_modules/, dist/, "*.lock", .env, generated/]   # reemplaza la lista por defecto
settings:
  auto_recall: true        # false lo desactiva
  auto_recall_k: 3         # memorias por mensaje
```
Hábitos que también ayudan:
- Usa Quick Spec en lugar de la Spec completa cuando la feature ya está clara.
- Abre una sesión nueva por tarea.
- Menciona archivos concretos (`#archivo`).
- Desactiva los servidores MCP que no uses.
- Ejecuta `/retro` para mantener la memoria corta.

## 6. Memoria y contexto

- **Una base de datos por proyecto** (`.agentes/agentes.db`), con estos tipos de memoria: `rule` (reglas siempre presentes), `decision`, `convention`, `design`, `requirement`, `bug`, `security`, `learning`, `profile`, `scan`, `code`, `spec` (specs de Kiro) y `note`.
- **Búsqueda híbrida**: combina vectores (ChromaDB) con BM25 (SQLite FTS5) mediante Reciprocal Rank Fusion.
  - BM25 encuentra las palabras exactas, como nombres de funciones o términos.
  - Los vectores encuentran por significado: paráfrasis y preguntas en otro idioma.
  - El **código** se busca solo con BM25, que es exacto y no necesita cargar el modelo. Los vectores quedan para memorias y specs.
  - Si no hay vectores, todo sigue funcionando con BM25. Si el modelo no se puede descargar, se recuerda el fallo durante una hora para no reintentar en cada mensaje.

### ¿Me conviene la búsqueda vectorial?
La memoria en base de datos ya ahorra tokens frente a los `.md` siempre cargados, con o sin vectores. Los vectores mejoran *qué* se encuentra cuando la pregunta no usa las mismas palabras que la memoria. En el conjunto de prueba incluido, BM25 acierta el **100% de las preguntas literales**, pero solo el **15% de las paráfrasis** y el **17% de las preguntas en inglés**. Ese hueco es lo que pueden cubrir los vectores. Mídelo en tu máquina:

```bash
agentes bench                                  # BM25 vs inglés vs multilingüe con el conjunto de prueba en español
agentes bench --modelos bm25,multilingue,multilingue-grande
/bench                                         # en Claude Code o Kiro: el equipo escribe preguntas sobre TUS memorias y lo ejecuta
agentes bench --queries .agentes/bench.yaml    # tus propias preguntas: [{query, expect: "fragmento de la memoria"}]
```
La tabla muestra para cada modo:
- **Acierto@1 y acierto@3:** cuántas veces la memoria correcta sale primera o entre las tres primeras.
- **MRR** y el **acierto por tipo de pregunta** (literal, paráfrasis, inglés).
- **Latencia, tiempo de carga del modelo y tokens devueltos.**

Al final da una recomendación. Si BM25 rinde casi igual, te sugiere `./install.sh --lite`.

| `settings.embedding_model` | Modelo | Tamaño | Idiomas |
|---|---|---|---|
| `multilingue` (por defecto) | paraphrase-multilingual-MiniLM-L12-v2 (fastembed) | ~220 MB | ~50, incluido español |
| `multilingue-grande` | paraphrase-multilingual-mpnet-base-v2 (fastembed) | ~1 GB | ~50, más preciso y más lento |
| `ingles` | all-MiniLM-L6-v2 (por defecto de ChromaDB) | ~80 MB | Inglés |

Si cambias el modelo, ejecuta `agentes memory rebuild`. Cada modelo tiene su propia colección, que se rellena sola con las memorias existentes. El modelo se descarga una vez durante `agentes install`; el servidor MCP lo mantiene cargado, y el auto-recall solo lo usa si la búsqueda por palabras clave no encontró nada.
- **Contexto automático**: al iniciar cada sesión se inyecta el perfil, el stack, las decisiones, las convenciones, el diseño y las tareas abiertas. En cada prompt se añaden las memorias más relevantes (auto-recall).
- **Protocolo común**: todos los agentes leen el contexto antes de trabajar y guardan solo conocimiento durable al terminar.
- **Compartir con tu equipo**: la base de datos no se sube a git. Usa `agentes memory export` para generar `.agentes/memory.json` y súbelo; quien lo reciba ejecuta `agentes memory import`.

## 7. Comandos para modificar y mejorar el harness

### Instalación y mantenimiento
```bash
agentes install [ruta] [--no-scan] [--no-index]   # instalar en un proyecto
agentes sync                                      # regenerar todo tras cambiar team.yaml / team.local.yaml
agentes doctor                                    # diagnóstico: PATH, MCP, hooks, vectores, estadísticas
agentes requisitos                                # software del harness + del proyecto; instala lo que falte (s/n)
agentes requisitos --check | --yes | --solo-requeridos | --lista
agentes uninstall [--purge]                       # quitar del proyecto (--purge borra también la memoria)
agentes ide list | add kiro | remove claude       # IDEs para los que se genera el equipo
agentes migrate [--apply] [--keep] [--include G]  # migrar .md y configuraciones previas (ver sección 5)
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
agentes memory export [archivo] · import [archivo] · rebuild   # rebuild: re-vectorizar (tras cambiar de modelo)
agentes bench [--modelos bm25,ingles,multilingue] [--queries archivo.yaml]   # ¿conviene la búsqueda vectorial?
agentes triage "texto de la tarea" [--tipo fix]  # tipo, peso XS-XL, ruta y código probable
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

## 8. Estructura

```
agentes/
  team.yaml        # ÚNICA fuente de verdad: agentes, flujos, cuestionarios, protocolo, ajustes
  cli.py           # CLI `agentes`
  installer.py     # genera .claude/* , hooks, .mcp.json y el bloque de CLAUDE.md (sin pisar lo tuyo)
  kiro.py          # genera .kiro/agents, steering, hooks v1, mcp.json y recetas de workflows
  migrate.py       # detección, migración a la BD, respaldo y restauración de configuraciones previas
  embeddings.py    # modelos de embeddings (multilingüe con fastembed, inglés de ChromaDB)
  bench.py         # benchmark BM25 vs búsqueda híbrida
  triage.py        # triaje: tipo y peso de la tarea, ruta más barata y localización de código
  store.py         # memoria: SQLite + FTS5 + ChromaDB (híbrida), perfil, tareas
  scanner.py       # análisis de proyectos existentes + indexado incremental de código
  mcp_server.py    # servidor MCP sin dependencias (memory_*, profile_*, task_*, project_context)
tests/test_harness.py
```

Los archivos `.claude/agents/*.md` y `.claude/commands/*.md` de cada proyecto se generan automáticamente y llevan una marca. `agentes sync` los regenera y elimina los obsoletos. Nunca toca los archivos que tú hayas creado: tus comandos, tus hooks y tu contenido de `CLAUDE.md` se conservan.

Ejecuta los tests con `uv run --extra dev --extra vector pytest -q`.
