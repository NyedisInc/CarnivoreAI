import UserNotifications

final class NotificationService: UNNotificationServiceExtension {
    private var handler: ((UNNotificationContent) -> Void)?
    private var content: UNMutableNotificationContent?

    override func didReceive(
        _ request: UNNotificationRequest,
        withContentHandler contentHandler: @escaping (UNNotificationContent) -> Void
    ) {
        handler = contentHandler
        let mutable = (request.content.mutableCopy() as? UNMutableNotificationContent) ?? UNMutableNotificationContent()
        content = mutable
        let result = PushRewrite.rewrite(userInfo: request.content.userInfo, candidates: PushKeyStore.candidates())
        mutable.title = result.title
        mutable.body = result.body
        if let path = result.path, let origin = result.origin { mutable.userInfo = ["path": path, "origin": origin] }
        else { mutable.userInfo = [:] }
        contentHandler(mutable)
    }

    override func serviceExtensionTimeWillExpire() {
        guard let handler else { return }
        let mutable = content ?? UNMutableNotificationContent()
        mutable.title = PushRewrite.generic.title
        mutable.body = PushRewrite.generic.body
        mutable.userInfo = [:]
        handler(mutable)
    }
}
