# Guías: qué hacer en cada caso

Cada proyecto cae en **una situación** (nuevo o existente) y **una plataforma** (web o mobile). Lee una guía de cada columna:

| ¿El proyecto ya tiene código? | ¿Qué plataforma? |
|---|---|
| No → [01 · Proyecto nuevo](01-proyecto-nuevo.md) | Web (React, Next, Vue, Angular, backend) → [03 · Web](03-web.md) |
| Sí → [02 · Integrar en un proyecto existente](02-proyecto-existente.md) | iOS / Android nativo → [04 · Mobile](04-mobile.md) |

## Primer comando según el caso

| Caso | Comando de instalación | Primer paso en el IDE |
|---|---|---|
| Nuevo · web | `agentes install --ide <claude\|kiro\|ambos>` | `/kickoff <idea>` |
| Nuevo · mobile | `agentes install --ide … --perfil mobile` | `/kickoff <idea>` |
| Existente · web | `agentes migrate` (simulacro) → `agentes install --ide …` | `/onboard <objetivo>` |
| Existente · mobile | `agentes migrate` (simulacro) → `agentes install --ide …` (el perfil mobile se detecta solo) | `/onboard <objetivo>` |
| Repo con web y mobile | Ver [04 · Mobile → Repos mixtos](04-mobile.md#repos-mixtos-web--mobile) | `/onboard <objetivo>` |

## Una sola vez por máquina

```bash
cd ~/PersonalProyects/Agents
./requisitos.sh          # revisa e instala lo que falte (s/n por herramienta)
./install.sh             # CLI `agentes` con búsqueda vectorial  (o ./install.sh --lite)
agentes --version
```

Después de actualizar el harness: `agentes upgrade` re-sincroniza todos tus proyectos registrados (`agentes projects`).

## Reglas que aplican siempre

- **Tamaño de la tarea = costo.** Cada mensaje pasa por el triaje (XS–XL). Lo pequeño se hace en la sesión, sin workflows. Si el equipo se excede, dilo: "esto es XS".
- **Una sesión por tarea.** Menciona archivos concretos cuando los sepas.
- **Lo que el IDE no ve, regístralo.** Capturas → `agentes design ref`; decisiones → `/remember`.
- **Los commits y las ramas los haces tú.** Ningún agente hace commit, crea ramas ni hace push; al terminar te dejan el mensaje de commit sugerido.
- **No subas la memoria a git.** Para compartirla: `agentes memory export` y súbelo como `.agentes/memory.json`.
- **Si algo falla:** `agentes doctor` y `.agentes/agentes.log`.
