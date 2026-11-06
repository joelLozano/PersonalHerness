# 04 · Proyectos mobile nativos (iOS y Android)

Para apps en Swift (SwiftUI/UIKit) y Kotlin (Compose/Views). Úsala junto con [01 · Proyecto nuevo](01-proyecto-nuevo.md) o [02 · Proyecto existente](02-proyecto-existente.md).

## Perfil mobile

Se activa solo si el proyecto tiene `.xcodeproj`/`.xcworkspace`, `Podfile`, `Package.swift` para iOS, `settings.gradle(.kts)` o un `AndroidManifest.xml`, **y no** es un proyecto web. En los demás casos:

```bash
agentes perfil set mobile       # o: agentes install --perfil mobile
agentes perfil list
```

| Cambia | Cómo |
|---|---|
| Agentes | `ios-dev` y `android-dev` reemplazan a `frontend-dev` y `fullstack-dev` |
| Diseño | `ux-designer` sigue Apple HIG y Material 3 |
| Seguridad | OWASP MASVS: Keychain/Keystore, ATS, componentes exportados |
| DevOps | Fastlane, firma, TestFlight y Play Console |
| Kickoff | SwiftUI o UIKit, Compose o Views, versiones mínimas, arquitectura, DI, offline, publicación |
| Escaneo | Esquemas de Xcode, minSdk/targetSdk, módulos Gradle, lanes y los comandos reales de build y test |

## Design system: configúralo primero

Es lo que más impacto tiene en mobile. El instalador busca carpetas o módulos `DesignSystem`, `DS`, `UIKit`, `CoreUI` o `:core:designsystem`. Comprueba lo que encontró y corrígelo si hace falta:

```bash
agentes ds show                     # catálogo compacto: ¿están todos tus componentes y tokens?
agentes ds map                      # mapeo nativo → DS (Button → DSButton…)
agentes ds index --ios Modules/DesignSystem --android core/designsystem   # rutas a mano (repetible)
```

Si el DS es un paquete SPM o un repo aparte, apunta a la ruta local donde lo tengas clonado.

Ajustes finos en `.agentes/team.local.yaml`, después `agentes sync`:

```yaml
settings:
  design_system:
    ios: [Modules/DesignSystem, Modules/Icons]
    android: core/designsystem
    map: {Button: PrimaryButton}     # corrige el mapeo automático
    ignore: [Image]                  # nativos permitidos
  ds_check_on_stop: true
```

**Cómo se usa durante el trabajo:**

- En tareas de UI, el triaje añade el catálogo compacto (~250–600 tokens) una vez por sesión y luego solo los componentes relevantes. Las tareas que no son de UI no cargan nada del DS.
- Los agentes consultan la firma y un ejemplo real con `ds_lookup`. Tú: `agentes ds lookup "botón primario" -P ios`.
- Al terminar cada turno, `ds check` revisa los cambios. Si hay un componente nativo con equivalente en el DS o un color literal, el agente lo corrige antes de entregarte.
- Excepción intencional: `// ds-ignore` en la línea. Previews, tests y el propio módulo del DS se ignoran.
- Revisión completa del código (no solo los cambios): `agentes ds check --todo`.

## Diseño desde capturas

```bash
agentes design ref ~/Desktop/perfil.png --nombre perfil --nota "iPhone 15"
```

En el IDE: `/design-ref perfil`. Para comparar tú mismo con el simulador o emulador abierto:

```bash
agentes design shot --ios                 # xcrun simctl (simulador activo)
agentes design shot --android             # adb (emulador o dispositivo)
agentes design compare perfil .agentes/design/shots/<captura>.png --movil
```

`--movil` ignora la barra de estado y el indicador de inicio. Usa una referencia del mismo tamaño de pantalla que el simulador.

## Kiro en mobile

Las recetas mobile marcan cada tarea con `[ios]`, `[android]` o `[backend]`; las ramas sin tareas terminan sin explorar. Al planear con Specs, etiqueta así las tareas para que solo corra la plataforma afectada. Deja **Use workflows** en *Only when asked*.

## Requisitos de software

`agentes requisitos` revisa Xcode, CocoaPods, SwiftLint, SwiftFormat, xcbeautify, Fastlane, JDK 17+, adb y el Android SDK, solo si el proyecto los usa.

## Seguridad específica

- Nunca se indexan `google-services.json`, `GoogleService-Info.plist`, `local.properties`, keystores ni perfiles de firma.
- Las contraseñas en `build.gradle` se redactan antes de entrar en la memoria.
- `/security` audita con MASVS: almacenamiento, red (ATS / network security config), componentes exportados, ofuscación.

## Repos mixtos (web + mobile)

Si en el mismo repo hay app nativa y web, el perfil no se activa solo. Para tener los dos equipos:

```bash
agentes perfil set mobile
agentes agent enable frontend-dev          # la reactiva aunque el perfil la desactive
agentes agent extend frontend-dev "La web vive en web/; no toques ios/ ni android/"
```

Si el backend está en otro repo, instala el harness también allí (equipo web) y registra en la app los contratos que consume: `agentes memory add "API v2: /bookings paginado por cursor" -k decision`.

## Errores comunes

- **Sin `ios-dev` / `android-dev`:** el perfil no se detectó (`agentes perfil set mobile`).
- **`ds show` vacío o incompleto:** rutas mal detectadas → `agentes ds index --ios … --android …`.
- **El hook bloquea por algo legítimo:** marca la línea con `// ds-ignore` o añade el nativo a `ignore`.
- **`design shot --ios` falla:** necesitas un simulador iniciado (`xcrun simctl list devices booted`).
- **Los comandos de test no corren:** revisa los esquemas detectados en `agentes context` y corrígelos con `/remember`.
