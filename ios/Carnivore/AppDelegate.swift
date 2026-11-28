import UIKit
@preconcurrency import UserNotifications

final class AppDelegate: NSObject, UIApplicationDelegate, @preconcurrency UNUserNotificationCenterDelegate {
    func application(_ application: UIApplication,
                     didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        UNUserNotificationCenter.current().delegate = self
        PushKeyStore.migrateAccessibility()
        Self.excludeSensitiveDirectoriesFromBackup()
        UNUserNotificationCenter.current().setNotificationCategories(NotifyCategories.all())
        #if DEBUG && targetEnvironment(simulator)
        NotifySeed.run()
        #endif
        return true
    }

    func application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken token: Data) {
        Task { @MainActor in
            PushRegistrar.shared.didRegister(token: token)
        }
    }

    func application(_ application: UIApplication, didFailToRegisterForRemoteNotificationsWithError error: Error) {
        Task { @MainActor in
            PushRegistrar.shared.didFail()
        }
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                withCompletionHandler completionHandler: @escaping () -> Void) {
        let actionId = response.actionIdentifier
        let userInfo = response.notification.request.content.userInfo
        Task { @MainActor in
            if actionId == UNNotificationDefaultActionIdentifier {
                TapRouter.shared.tapped(userInfo: userInfo, requireValidMAC: true)
            } else {
                await NotifyActions.handle(response)
            }
            completionHandler()
        }
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        let info = notification.request.content.userInfo
        Task { @MainActor in
            completionHandler(Self.presentation(for: info, viewing: ShellBridge.viewing))
        }
    }

    static func presentation(for info: [AnyHashable: Any], viewing: (origin: String, session: String)?) -> UNNotificationPresentationOptions {
        if let viewing, info["origin"] as? String == viewing.origin, info["thread"] as? String == viewing.session {
            return [.list]
        }
        return [.banner, .sound]
    }

    private static func excludeSensitiveDirectoriesFromBackup() {
        let fm = FileManager.default
        let roots: [URL?] = [
            fm.urls(for: .cachesDirectory, in: .userDomainMask).first,
            fm.urls(for: .libraryDirectory, in: .userDomainMask).first?.appendingPathComponent("WebKit", isDirectory: true),
            fm.urls(for: .libraryDirectory, in: .userDomainMask).first?.appendingPathComponent("Cookies", isDirectory: true),
        ]
        for case var url? in roots where fm.fileExists(atPath: url.path) {
            var values = URLResourceValues()
            values.isExcludedFromBackup = true
            try? url.setResourceValues(values)
        }
    }
}
