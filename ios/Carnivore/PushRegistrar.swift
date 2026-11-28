import CryptoKit
import Foundation
import UIKit
import UserNotifications

@MainActor
final class PushRegistrar: ObservableObject {
    static let shared = PushRegistrar()
    weak var bridge: ShellBridge?

    @Published private(set) var lastTokenHex: String?
    @Published private(set) var isRegisteredForActiveOrigin = false

    private var waiting = false
    private var pendingBridgeOrigin: String?
    private var pendingNativeContinuations: [CheckedContinuation<String?, Never>] = []

    static var environment: String {
        (Bundle.main.object(forInfoDictionaryKey: "CarnivorePushEnvironment") as? String) == "sandbox"
            ? "sandbox" : "production"
    }

    func registerNative(computer: Computer, api: CarnivoreAPI) async -> Bool {
        guard computer.kind == .relay, computer.origin.isEncrypted else { return false }
        let originId = computer.origin.pushId
        let granted = (try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge])) ?? false
        guard granted else { return false }

        let tokenHex: String?
        if let cached = lastTokenHex {
            tokenHex = cached
        } else {
            tokenHex = await requestDeviceToken()
        }
        guard let tokenHex, let key = PushKeyStore.keyForRegistration(origin: originId) else { return false }
        let info = Bundle.main.infoDictionary
        let body = NativeDeviceRegisterBody(
            platform: "ios",
            token: tokenHex,
            environment: Self.environment,
            bundle_id: Bundle.main.bundleIdentifier ?? "ai.carnivore.ios",
            app_version: (info?["CFBundleShortVersionString"] as? String) ?? "1.0",
            payload_key: PushKeyStore.base64url(key)
        )
        do {
            let rowId = try await api.registerNativeDevice(body)
            PushKeyStore.setRowId(rowId, origin: originId)
            isRegisteredForActiveOrigin = true
            return true
        } catch {
            return false
        }
    }

    private func requestDeviceToken() async -> String? {
        await withCheckedContinuation { cont in
            pendingNativeContinuations.append(cont)
            UIApplication.shared.registerForRemoteNotifications()
        }
    }

    func start(origin: String) {
        waiting = true
        pendingBridgeOrigin = origin
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge]) { granted, _ in
            Task { @MainActor in
                if granted { UIApplication.shared.registerForRemoteNotifications() }
                else { self.fail("denied") }
            }
        }
    }

    func didRegister(token: Data) {
        let hex = token.map { String(format: "%02x", $0) }.joined()
        lastTokenHex = hex
        let waiters = pendingNativeContinuations
        pendingNativeContinuations.removeAll()
        waiters.forEach { $0.resume(returning: hex) }

        guard waiting else { return }
        waiting = false
        let expectedOrigin = pendingBridgeOrigin
        pendingBridgeOrigin = nil
        guard let origin = expectedOrigin,
              let bridge, bridge.canPush, bridge.originPushId == origin,
              let key = PushKeyStore.keyForRegistration(origin: origin) else {
            return fail("key")
        }
        let info = Bundle.main.infoDictionary
        bridge.send([
            "type": "pushToken",
            "token": hex,
            "environment": Self.environment,
            "payload_key": PushKeyStore.base64url(key),
            "bundle_id": Bundle.main.bundleIdentifier ?? "ai.carnivore.ios",
            "app_version": (info?["CFBundleShortVersionString"] as? String) ?? "1.0",
        ])
    }

    func didFail() {
        let waiters = pendingNativeContinuations
        pendingNativeContinuations.removeAll()
        waiters.forEach { $0.resume(returning: nil) }
        if waiting { fail("unavailable") }
    }

    private func fail(_ reason: String) {
        waiting = false
        pendingBridgeOrigin = nil
        bridge?.send(["type": "pushFailed", "reason": reason])
    }
}
