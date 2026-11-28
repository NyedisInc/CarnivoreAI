import SwiftUI

@main
struct CarnivoreApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var computerStore = ComputerStore()
    @StateObject private var sessionStore = AppSessionStore()
    @StateObject private var lockManager = AppLockManager()
    @StateObject private var theme = ThemeStore.shared
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            ZStack {
                RootShellView(
                    computerStore: computerStore,
                    sessionStore: sessionStore,
                    lockManager: lockManager
                )

                if lockManager.isLocked || scenePhase != .active {
                    PrivacyShieldView(
                        locked: lockManager.isLocked,
                        biometricLabel: lockManager.biometricLabel,
                        biometricIcon: lockManager.biometricIcon,
                        error: lockManager.lastError,
                        onUnlock: { Task { await lockManager.unlock() } }
                    )
                    .transition(.opacity)
                }
            }
            .environmentObject(theme)
            .preferredColorScheme(theme.palette.isDark ? .dark : .light)
            .onOpenURL { url in
                TapRouter.shared.handleURL(url)
            }
            .onChange(of: scenePhase) { _, newPhase in
                lockManager.handleScenePhase(newPhase)
            }
            .task {
                if lockManager.isLocked {
                    await lockManager.unlock()
                }
            }
        }
    }
}
