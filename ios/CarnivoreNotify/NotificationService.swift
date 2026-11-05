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
        var info: [String: String] = [:]
        if let path = result.path, let origin = result.origin { info["path"] = path; info["origin"] = origin }
        if let thread = result.thread, let origin = result.origin {
            mutable.threadIdentifier = "\(origin)|\(thread)"
            info["thread"] = thread
            info["origin"] = origin
        }
        mutable.userInfo = info
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
