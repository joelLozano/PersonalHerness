# 03 · Proyectos web

Para frontends web (React, Next, Vue, Nuxt, Svelte, Angular), backends y full-stack. Úsala junto con [01 · Proyecto nuevo](01-proyecto-nuevo.md) o [02 · Proyecto existente](02-proyecto-existente.md).

## Equipo

Sin perfil (el equipo base). Si el proyecto tiene `package.json` con un framework web, el instalador **no** activa el perfil mobile aunque haya carpetas nativas.

| Agente | Para qué |
|---|---|
| `frontend-dev` | Componentes, páginas, estado, consumo de APIs |
| `backend-dev` | APIs, lógica de negocio, base de datos, migraciones |
| `fullstack-dev` | Features pequeñas o medianas que tocan ambas capas |
| `ux-designer` | Flujos, layout, sistema de diseño |
| `code-reviewer` · `qa-engineer` · `security-engineer` · `devops-engineer` | Revisión, pruebas, OWASP, CI/CD y despliegue |

Ajusta el equipo a tu stack (se guarda en `team.local.yaml`):

```bash
agentes agent extend frontend-dev "Next 15 App Router; Server Components salvo interactividad; Tailwind; nada de CSS-in-JS"
agentes agent extend backend-dev "Prisma + Postgres; precios en centavos; errores con RFC 7807"
agentes agent disable devops-engineer     # si no hay infraestructura que mantener
```

## Design system en web

`agentes ds` (índice, `ds check` automático) está pensado para iOS y Android. En web, el DS se mantiene en contexto así:

1. **Kickoff / onboarding:** colores, tipografía y estilo quedan en el perfil del proyecto.
2. **Dónde viven tus componentes** (una línea, siempre presente para el agente de UI):
   ```bash
   agentes agent extend frontend-dev "UI: usa solo componentes de src/components/ui (shadcn) y tokens de tailwind.config.ts; nada de colores literales"
   ```
3. **Decisiones de diseño** como memoria (se recuperan cuando son relevantes, sin gastar tokens el resto del tiempo):
   ```bash
   agentes memory add "Botón primario: <Button variant='default'>; destructivo: variant='destructive'" -k design
   ```

Evita meter el catálogo entero como regla: las reglas entran en **todas** las sesiones.

## Diseño desde capturas y Figma

```bash
npx playwright install chromium                  # una vez, para capturas
agentes design ref ~/Desktop/checkout.png --nombre checkout --nota "escritorio 1440"
```

En el IDE: `/design-ref checkout` registra, analiza la paleta, implementa y **verifica visualmente**. Para revisarlo tú:

```bash
agentes design shot http://localhost:3000/checkout --ancho 1440 --alto 900
agentes design compare checkout .agentes/design/shots/<captura>.png
```

Repite con `--ancho 390 --alto 844` para validar la versión móvil del sitio.

**Figma (plan gratuito):** exporta el frame como PNG y usa `agentes design ref`. Para importaciones ocasionales con tokens (tipografías, radios, espaciados): `agentes design figma --save-token figd_…` y luego `agentes design figma "<url con node-id>"`.

## Requisitos de software

`agentes requisitos` detecta Node/npm, pnpm, yarn, bun, Docker, etc. según los archivos del proyecto. Para algo propio (por ejemplo, la CLI de Stripe o `psql`), crea `.agentes/requisitos.conf` (formato en la sección 11 del README principal).

## Pruebas y seguridad

- `/test [alcance]`: QA escribe y ejecuta pruebas (unitarias, integración, e2e si hay Playwright o Cypress).
- `/security`: OWASP Top 10, secretos, dependencias, cabeceras e infraestructura. Genera tareas de remediación.
- Los agentes no pueden leer `.env*` (salvo `.env.example`) ni llaves; tampoco se indexan.

## Kiro en web

Recetas disponibles: `agentes-feature-lite` (features medianas), `agentes-feature` (grandes), `agentes-bugfix`, `agentes-security-audit` y `agentes-onboard`. Deja **Use workflows** en *Only when asked*; las tareas XS/S/M se resuelven en la sesión.

## Errores comunes

- **El triaje no encuentra el código.** `agentes index --rebuild` y comprueba con `agentes triage "<tarea>"`.
- **Monorepo con varias apps.** Instala el harness en la raíz y dile al frontend dónde está cada app con `agent extend`, o instálalo por app si son independientes.
- **Las capturas no coinciden por el contenido dinámico** (fechas, datos). Usa datos de prueba fijos antes de comparar.
