# 02 · Integrar el harness en un proyecto existente

Para proyectos que ya tienen código, quizá con otras configuraciones de agentes (`CLAUDE.md`, `.cursorrules`, `.kiro/steering`…). Complementa con [03 · Web](03-web.md) o [04 · Mobile](04-mobile.md).

El harness **no toca tu código**, ni tu README, ni tus specs de Kiro, ni tus hooks o servidores MCP. Todo lo que reemplaza queda respaldado y se puede deshacer.

## Pasos

### 1. Parte de un estado limpio

```bash
git status                     # sin cambios pendientes
git switch -c chore/agentes    # rama para revisar el resultado antes de integrarlo
```

### 2. Revisa qué configuraciones existentes se migrarían (simulacro)

```bash
agentes migrate
```

No cambia nada. Muestra cada archivo detectado y qué pasará con él:

- `CLAUDE.md`, `AGENTS.md`, `.cursorrules`, steering `always` → **reglas** (siempre en contexto) o memorias.
- `memory-bank/`, `.ai/`, steering `fileMatch` → memorias clasificadas.
- `.claude/agents`, `.kiro/agents` → agentes del equipo (o instrucciones sumadas a uno existente).
- `.claude/commands`, steering `manual` → comandos.

¿Tienes documentación propia útil (decisiones, ADRs)? Inclúyela: `agentes migrate --include "docs/adr/*.md"`.

### 3. Instala

```bash
agentes install --ide claude     # o kiro, o ambos
```

El instalador:
1. Genera el equipo (perfil mobile automático si hay Xcode/Gradle y no hay web).
2. Te ofrece la migración del paso 2 (s/n). Para conservar los originales: `agentes migrate --apply --keep` después.
3. Escanea el proyecto: stack, scripts, CI, tests, variables de entorno, deuda técnica, archivos más modificados y mapa del código.
4. Indexa el código y, en mobile, el design system.

¿Proyecto muy grande? `agentes install --no-index` y después `agentes index` cuando te convenga.

### 4. Si el repo ya traía el harness de otra persona

Las personalizaciones versionadas (`team.local.yaml`, `requisitos.conf`) no se aplican hasta que las apruebes:

```bash
agentes trust        # muestra qué cambian y marca lo sospechoso
```

Si vienes de una versión anterior del harness, ejecuta también `agentes audit --fix` una vez.

### 5. Verifica

```bash
agentes doctor       # instalación, hooks (latencia y tokens), MCP
agentes audit        # sin hallazgos altos
agentes context      # ¿el resumen describe bien tu proyecto?
agentes triage "corrige el texto del botón de pago"   # ¿apunta a los archivos correctos?
agentes requisitos --check                            # ¿falta software que el proyecto usa?
```

Si el contexto describe mal el proyecto, corrígelo antes de seguir: `agentes scan` vuelve a escanear y `/remember` o `agentes memory add` guardan lo que el escaneo no puede saber.

### 6. Onboarding con el equipo

En el IDE:

```
/onboard quiero agregar pagos con Stripe
```

El equipo explora arquitectura, pruebas, seguridad y diseño existente; **solo te pregunta lo que el código no responde** y propone un plan con tareas. Para ver esas preguntas antes: `agentes questions existing`.

### 7. Trabajo diario

| Tarea | Qué pedir |
|---|---|
| Typo, texto, color, una línea | Pídelo directo; el triaje lo marca XS y se hace en la sesión |
| Bug | `/fix <descripción>`: test que lo reproduce → causa raíz → corrección |
| Feature | `/feature <descripción>`: se dimensiona primero (S, M o L) |
| Revisión antes de un PR | `/review`, `/test`, `/security` |

Si el triaje elige un peso equivocado, corrígelo en el mismo mensaje ("es S, no delegues").

## Si algo salió mal

```bash
agentes migrate --backups        # respaldos disponibles
agentes migrate --restore        # deshace la última migración
agentes uninstall                # quita el harness (conserva la memoria)
agentes uninstall --purge        # también borra .agentes/
```

## Equipo de varias personas

1. Una persona integra el harness y sube `.claude/`, `.kiro/`, `.mcp.json` y `.agentes/team.local.yaml`.
2. Cada persona ejecuta `agentes install` en su clon y `agentes trust` para aprobar la configuración compartida.
3. Para compartir memoria: `agentes memory export` → subir `.agentes/memory.json` → los demás `agentes memory import`.

## Lista de verificación

La prueba piloto completa (8 pasos) está en la sección 10 del README principal. Lo mínimo: `doctor` en verde, `/onboard` coherente, un cambio XS resuelto sin workflows y una tarea L que espere tu confirmación.
