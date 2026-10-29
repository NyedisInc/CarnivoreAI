import Foundation
import UIKit
import UserNotifications

final class PushRegistrar {
    static let shared = PushRegistrar()
    weak var bridge: ShellBridge?
    private var waiting = false
    private var origin: String?

    static var environment: String {
        (Bundle.main.object(forInfoDictionaryKey: "CarnivorePushEnvironment") as? String) == "sandbox"
            ? "sandbox" : "production"
    }

    func start(origin: String) {
        waiting = true
        self.origin = origin
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge]) { granted, _ in
            DispatchQueue.main.async {
                if granted { UIApplication.shared.registerForRemoteNotifications() }
                else { self.fail("denied") }
            }
        }
    }

    func didRegister(token: Data) {
        guard waiting else { return }
        waiting = false
        guard let origin, let key = PushKeyStore.keyForRegistration(origin: origin) else { return fail("key") }
        let info = Bundle.main.infoDictionary
        bridge?.send(["type": "pushToken", "token": token.map { String(format: "%02x", $0) }.joined(),
                      "environment": Self.environment, "payload_key": PushKeyStore.base64url(key),
                      "bundle_id": Bundle.main.bundleIdentifier ?? "ai.carnivore.ios",
                      "app_version": (info?["CFBundleShortVersionString"] as? String) ?? "0"])
    }

    func didFail() { if waiting { fail("unavailable") } }

    private func fail(_ reason: String) {
        waiting = false
        bridge?.send(["type": "pushFailed", "reason": reason])
    }
}
