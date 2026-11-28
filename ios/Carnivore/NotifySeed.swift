import Foundation
import UserNotifications

#if DEBUG && targetEnvironment(simulator)
enum NotifySeed {
    static let rowId = "d_0123456789ab"

    @discardableResult
    static func run(arguments: [String] = ProcessInfo.processInfo.arguments) -> Bool {
        guard let i = arguments.firstIndex(of: "-carnivoreNotifySeed"), i + 1 < arguments.count,
              let url = URL(string: arguments[i + 1]), let origin = Origin(url: url) else { return false }
        let key = Data((0..<32).map { UInt8($0) })
        PushKeyStore.seedTestVector(origin: origin.pushId, key: key, rowId: rowId)
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge]) { _, _ in }
        if let d = arguments.firstIndex(of: "-carnivoreNotifyDir"), d + 1 < arguments.count { play(dir: arguments[d + 1]) }
        return true
    }

    private static func play(dir: String) {
        let service = NotificationService()
        Timer.scheduledTimer(withTimeInterval: 0.4, repeats: true) { _ in
            let names = (try? FileManager.default.contentsOfDirectory(atPath: dir)) ?? []
            for name in names where name.hasPrefix("play-") && name.hasSuffix(".json") {
                let path = dir + "/" + name
                guard let data = FileManager.default.contents(atPath: path),
                      let obj = try? JSONSerialization.jsonObject(with: data) as? [String: String] else { continue }
                try? FileManager.default.removeItem(atPath: path)
                let content = UNMutableNotificationContent()
                content.title = "carnivore"
                content.body = "open to read"
                content.userInfo = ["p": obj["p"] ?? ""]
                let request = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
                service.didReceive(request) { delivered in
                    let final = (delivered.mutableCopy() as? UNMutableNotificationContent) ?? UNMutableNotificationContent()
                    var info = (final.userInfo as? [String: String]) ?? [:]
                    if info["ttl"] != nil { info["ttl"] = String(Date().addingTimeInterval(3600).timeIntervalSince1970) }
                    final.userInfo = NotificationMAC.sign(info)
                    if final.interruptionLevel == .passive { final.interruptionLevel = .active }
                    let out = UNNotificationRequest(identifier: UUID().uuidString, content: final, trigger: UNTimeIntervalNotificationTrigger(timeInterval: 0.5, repeats: false))
                    UNUserNotificationCenter.current().add(out)
                    try? Data().write(to: URL(fileURLWithPath: dir + "/delivered-" + name.dropFirst(5).dropLast(5)))
                }
            }
        }
    }
}
#endif
