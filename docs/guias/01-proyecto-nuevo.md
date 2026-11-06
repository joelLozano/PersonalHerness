# 01 · Proyecto nuevo

Para cuando empiezas desde cero: carpeta vacía o solo con una idea. Complementa con [03 · Web](03-web.md) o [04 · Mobile](04-mobile.md).

## Antes de instalar

Ten a mano lo que el cuestionario te va a pedir; responderlo bien ahorra muchas correcciones después:

- **Producto:** qué problema resuelve, usuarios, las 3–5 funciones del MVP y lo que queda fuera.
- **Stack:** lenguajes y frameworks si ya los decidiste (si no, el tech-lead propone).
- **Diseño:** colores en hex, tipografía, estilo (minimalista, corporativo…), modo oscuro, apps o sitios de referencia.
- **Referencias visuales:** capturas o frames de Figma exportados como PNG.
- **Calidad:** nivel de pruebas esperado, accesibilidad, requisitos de seguridad o normativos.

## Pasos

### 1. Crea el repositorio

```bash
mkdir mi-app && cd mi-app
git init
```

En **mobile** puedes crear antes el proyecto en Xcode o Android Studio. Si la carpeta está vacía, indica el perfil a mano en el paso 2: sin archivos de Xcode o Gradle no se detecta.

### 2. Instala el harness

```bash
agentes install --ide claude              # o kiro, o ambos
agentes install --ide kiro --perfil mobile   # app nativa iOS/Android
agentes doctor                            # todo debe salir ✔
```

Como no hay código, no se escanea nada; el instalador te sugiere `/kickoff`.

### 3. Registra tus referencias visuales (opcional, recomendado)

```bash
agentes design ref ~/Desktop/home.png --nombre home --nota "pantalla principal"
agentes design ref ~/Desktop/login.png --nombre login
agentes design list
```

Así cualquier agente las ve con su paleta exacta, no solo la conversación donde las pegaste.

### 4. Ejecuta el kickoff

En el IDE:

```
/kickoff una app para reservar canchas de pádel
```

El equipo te pregunta por secciones (producto, stack, diseño, calidad) y guarda las respuestas en el perfil del proyecto. Con eso genera requisitos, sistema de diseño, arquitectura y backlog.

¿Prefieres contestar en la terminal? `agentes kickoff`. Para ver las preguntas antes: `agentes questions new`.

### 5. Revisa lo que quedó

```bash
agentes context        # lo que los agentes recibirán en cada sesión
agentes task list      # el backlog generado
```

En el IDE, `/tasks` muestra el mismo tablero. Corrige ahora lo que no te convenza: es lo más barato que vas a pagar.

### 6. Primera entrega

Empieza por una tarea pequeña para comprobar que todo fluye:

```
/implement <id de tarea>
```

Para algo más grande, `/plan` (solo planear) o `/feature` (de punta a punta). En Kiro, las tareas L/XL te proponen Spec o receta con su costo y esperan tu confirmación.

### 7. Cuando ya hay código

```bash
agentes scan           # registra stack, scripts y comandos reales de build/test
agentes index          # indexa el código para que el triaje sepa dónde buscar
```

A partir de aquí el índice se actualiza solo al iniciar sesión. En mobile, cuando exista el módulo del design system: `agentes ds index` (ver [04 · Mobile](04-mobile.md)).

## Qué subir a git

| Sí | No |
|---|---|
| `.claude/`, `.kiro/`, `.mcp.json`, `CLAUDE.md` | `.agentes/agentes.db*`, `.agentes/vectors/` |
| `.agentes/team.local.yaml`, `.agentes/config.json` | `.agentes/backup/`, logs, capturas |
| `.agentes/design/refs/` | Tokens (el de Figma vive en `~/.config/agentes/`) |
| `.agentes/memory.json` (si exportas la memoria) | |

El `.gitignore` que genera `agentes install` ya cubre la columna derecha.

## Errores comunes

- **El equipo pregunta lo que ya contestaste.** Revisa `agentes memory profile`; si falta algo, `agentes memory profile <clave> <valor> --tags <sección>`.
- **Mobile sin `ios-dev` / `android-dev`.** Se instaló sin perfil: `agentes perfil set mobile`.
- **Los colores no coinciden con tu marca.** Pásalos en hex en el kickoff o registra una referencia; no los describas con palabras.
