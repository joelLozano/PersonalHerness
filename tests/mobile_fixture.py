"""Proyecto mobile sintético (iOS SwiftUI+UIKit con DS en módulo SPM, Android Compose con módulo :core:designsystem)."""
from pathlib import Path

FILES = {
    # ---------- iOS ----------
    "Tienda.xcodeproj/project.pbxproj": "IPHONEOS_DEPLOYMENT_TARGET = 16.0;\nIPHONEOS_DEPLOYMENT_TARGET = 17.0;\n",
    "Tienda.xcodeproj/xcshareddata/xcschemes/Tienda.xcscheme": "<Scheme/>",
    "Tienda/TiendaApp.swift": "import SwiftUI\n@main\nstruct TiendaApp: App { var body: some Scene { WindowGroup { CheckoutView() } } }\n",
    "Tienda/Features/Checkout/CheckoutView.swift": (
        "import SwiftUI\nimport DesignSystem\n\nstruct CheckoutView: View {\n    var body: some View {\n"
        "        VStack {\n            DSText(\"Total\", style: .title)\n            DSButton(title: \"Pagar\", style: .primary) {}\n"
        "        }\n    }\n}\n"),
    "Tienda/Features/Checkout/CheckoutViewModel.swift": "import Foundation\nfinal class CheckoutViewModel {}\n",
    "Tienda/Legacy/ProfileViewController.swift": "import UIKit\nfinal class ProfileViewController: UIViewController {}\n",
    "Package.resolved": '{"pins":[{"identity":"alamofire","location":"https://github.com/Alamofire/Alamofire.git"},'
                        '{"identity":"swift-snapshot-testing","location":"https://github.com/pointfreeco/swift-snapshot-testing"}]}',
    ".swiftlint.yml": "disabled_rules: []\n",
    "Modules/DesignSystem/Package.swift": "// swift-tools-version:5.9\nimport PackageDescription\nlet package = Package(name: \"DesignSystem\", platforms: [.iOS(.v16)])\n",
    "Modules/DesignSystem/Sources/DesignSystem/Components/DSButton.swift": (
        "import SwiftUI\n\n/// Botón principal del design system.\npublic struct DSButton: View {\n"
        "    public enum Style { case primary, secondary, destructive }\n"
        "    let title: String\n    let style: Style\n    let action: () -> Void\n\n"
        "    public init(title: String, style: Style = .primary, isLoading: Bool = false, action: @escaping () -> Void) {\n"
        "        self.title = title; self.style = style; self.action = action\n    }\n"
        "    public var body: some View { Text(title) }\n}\n"),
    "Modules/DesignSystem/Sources/DesignSystem/Components/DSText.swift": (
        "import SwiftUI\n\n/// Texto con la tipografía del DS.\npublic struct DSText: View {\n"
        "    public init(_ text: String, style: DSTypography = .body) {}\n    public var body: some View { EmptyView() }\n}\n"),
    "Modules/DesignSystem/Sources/DesignSystem/Components/DSCard.swift": (
        "import SwiftUI\n\npublic struct DSCard<Content: View>: View {\n    public init(padding: DSSpacing = .m, @ViewBuilder content: () -> Content) {}\n"
        "    public var body: some View { EmptyView() }\n}\n"),
    "Modules/DesignSystem/Sources/DesignSystem/Components/DSTextField.swift": (
        "import SwiftUI\n\npublic struct DSTextField: View {\n    public init(_ placeholder: String, text: Binding<String>, error: String? = nil) {}\n"
        "    public var body: some View { EmptyView() }\n}\n"),
    "Modules/DesignSystem/Sources/DesignSystem/Components/DSBadgeView.swift": (
        "import UIKit\n\n/// Badge para pantallas UIKit.\npublic final class DSBadgeView: UIView {\n    public init(text: String) { super.init(frame: .zero) }\n"
        "    required init?(coder: NSCoder) { fatalError() }\n}\n"),
    "Modules/DesignSystem/Sources/DesignSystem/Tokens/Tokens.swift": (
        "import SwiftUI\n\npublic extension Color {\n    static let dsPrimary = Color(\"BrandPrimary\")\n    static let dsBackground = Color(\"Background\")\n}\n\n"
        "public enum DSSpacing: CGFloat { case xs = 4, s = 8, m = 16, l = 24 }\n\n"
        "public enum DSTypography { case title, body, caption }\n\n"
        "public extension View {\n    /// Sombra estándar de tarjetas.\n    func dsShadow() -> some View { shadow(radius: 4) }\n}\n"),
    "Modules/DesignSystem/Sources/DesignSystem/Resources/Colors.xcassets/BrandPrimary.colorset/Contents.json": (
        '{"colors":[{"color":{"color-space":"srgb","components":{"red":"0x22","green":"0xC5","blue":"0x5E","alpha":"1.000"}},"idiom":"universal"},'
        '{"appearances":[{"appearance":"luminosity","value":"dark"}],"color":{"color-space":"srgb","components":'
        '{"red":"0.525","green":"0.937","blue":"0.675","alpha":"1.000"}},"idiom":"universal"}]}'),
    # ---------- Android ----------
    "settings.gradle.kts": 'rootProject.name = "Tienda"\ninclude(":app")\ninclude(":core:designsystem", ":feature:checkout")\n',
    "gradle/libs.versions.toml": '[versions]\nminSdk = "26"\ntargetSdk = "35"\ncompileSdk = "35"\n[libraries]\n'
                                 'compose-bom = { module = "androidx.compose:compose-bom" }\nhilt = { module = "com.google.dagger:hilt-android" }\n'
                                 'retrofit = { module = "com.squareup.retrofit2:retrofit" }\npaparazzi = { module = "app.cash.paparazzi:paparazzi" }\n',
    "app/build.gradle.kts": 'plugins { id("com.android.application") }\nandroid { buildFeatures { compose = true } }\n',
    "app/src/main/AndroidManifest.xml": '<manifest package="com.acme.tienda"/>',
    "app/src/main/java/com/acme/tienda/MainActivity.kt": "package com.acme.tienda\nclass MainActivity\n",
    "app/src/main/java/com/acme/tienda/ui/checkout/CheckoutScreen.kt": (
        "package com.acme.tienda.ui.checkout\n\nimport androidx.compose.runtime.Composable\n"
        "@Composable\nfun CheckoutScreen(onPay: () -> Unit) {\n    DsButton(text = \"Pagar\", onClick = onPay)\n}\n"),
    "app/src/main/java/com/acme/tienda/data/OrdersRepository.kt": "package com.acme.tienda.data\nclass OrdersRepository\n",
    "core/designsystem/build.gradle.kts": 'plugins { id("com.android.library") }\n',
    "core/designsystem/src/main/java/com/acme/designsystem/component/Button.kt": (
        "package com.acme.designsystem.component\n\nimport androidx.compose.runtime.Composable\n\n"
        "/** Botón principal del design system. */\n@Composable\nfun DsButton(\n    text: String,\n    onClick: () -> Unit,\n"
        "    modifier: Modifier = Modifier,\n    variant: DsButtonVariant = DsButtonVariant.Primary,\n    enabled: Boolean = true,\n) {}\n\n"
        "@Preview\n@Composable\nprivate fun DsButtonPreview() { DsButton(\"Hola\", {}) }\n\n"
        "@Composable\ninternal fun InternalHelper() {}\n"),
    "core/designsystem/src/main/java/com/acme/designsystem/component/Text.kt": (
        "package com.acme.designsystem.component\n\n@Composable\nfun DsText(text: String, style: TextStyle = DsTheme.typography.body, modifier: Modifier = Modifier) {}\n"),
    "core/designsystem/src/main/java/com/acme/designsystem/component/Card.kt": (
        "package com.acme.designsystem.component\n\n@Composable\nfun DsCard(modifier: Modifier = Modifier, content: @Composable () -> Unit) {}\n"),
    "core/designsystem/src/main/java/com/acme/designsystem/theme/Color.kt": (
        "package com.acme.designsystem.theme\n\nval BrandPrimary = Color(0xFF22C55E)\nval Background = Color(0xFFFFFFFF)\nval TextPrimary = Color(0xFF0F172A)\n"),
    "core/designsystem/src/main/java/com/acme/designsystem/theme/Spacing.kt": (
        "package com.acme.designsystem.theme\n\nobject DsSpacing {\n    val xs = 4.dp\n    val s = 8.dp\n    val m = 16.dp\n}\n"),
    "core/designsystem/src/main/res/values/colors.xml": '<resources><color name="brand_primary">#22C55E</color></resources>',
    "fastlane/Fastfile": "lane :beta do\nend\nlane :release do\nend\n",
}


def make(root: Path) -> Path:
    for rel, text in FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return root
