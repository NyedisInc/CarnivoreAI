import SwiftUI

@main
struct CarnivoreApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var store = ComputerStore()
    @StateObject private var theme = ThemeStore.shared

    var body: some Scene {
        WindowGroup {
            ComputerListView(store: store)
                .environmentObject(theme)
                .preferredColorScheme(theme.palette.isDark ? .dark : .light)
        }
    }
}
