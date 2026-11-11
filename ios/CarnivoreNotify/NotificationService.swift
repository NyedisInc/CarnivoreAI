import UniformTypeIdentifiers
import UserNotifications

final class NotificationService: UNNotificationServiceExtension {
    static let budget: TimeInterval = 22
    static let videoAttachLimit = 15 * 1_048_576

    private let lock = NSLock()
    private var handler: ((UNNotificationContent) -> Void)?
    private var content: UNMutableNotificationContent?
    private var attachments: [UNNotificationAttachment] = []
    private var fullCard: Data?
    private var envelope: NotifyEnvelope?
    private var origin: String?
    private var workDir: URL?

    override func didReceive(
        _ request: UNNotificationRequest,
        withContentHandler contentHandler: @escaping (UNNotificationContent) -> Void
    ) {
        lock.lock()
        attachments = []
        fullCard = nil
        envelope = nil
        origin = nil
        workDir = nil
        lock.unlock()
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
        guard let env = result.envelope, let origin = result.origin else { return deliver() }
        envelope = env
        self.origin = origin
        applyV2(env, origin: origin, to: mutable)
        if let settle = env.settle {
            mutable.title = settle.agent
            mutable.body = settle.line
            return deliver()
        }
        DispatchQueue.global().asyncAfter(deadline: .now() + Self.budget) { [weak self] in self?.deliver() }
        Task { [weak self] in
            await self?.fetchAndAttach(env, origin: origin)
            self?.deliver()
        }
    }

    override func serviceExtensionTimeWillExpire() {
        if envelope != nil { return deliver() }
        lock.lock()
        let pending = handler
        let mutable = content ?? UNMutableNotificationContent()
        handler = nil
        lock.unlock()
        mutable.title = PushRewrite.generic.title
        mutable.body = PushRewrite.generic.body
        mutable.userInfo = [:]
        pending?(mutable)
    }

    private func applyV2(_ env: NotifyEnvelope, origin: String, to mutable: UNMutableNotificationContent) {
        mutable.subtitle = env.sub ?? ""
        mutable.categoryIdentifier = env.settle == nil ? NotifyContract.categoryId(env.kind) : ""
        let level = env.settle != nil ? "p" : (env.level ?? NotifyContract.kindStyle[env.kind]?.level ?? "a")
        switch level {
        case "p": mutable.interruptionLevel = .passive
        case "t": mutable.interruptionLevel = .timeSensitive
        default: mutable.interruptionLevel = .active
        }
        mutable.relevanceScore = level == "t" ? 1.0 : 0.5
        let sound = env.settle != nil ? "none" : (env.sound ?? NotifyContract.kindStyle[env.kind]?.sound ?? "default")
        switch sound {
        case "none": mutable.sound = nil
        case "default": mutable.sound = .default
        default: mutable.sound = UNNotificationSound(named: UNNotificationSoundName("carnivore-\(sound).caf"))
        }
        var info = mutable.userInfo as? [String: String] ?? [:]
        info.merge(NotifyUserInfo.encode(env, origin: origin)) { _, new in new }
        mutable.userInfo = info
    }

    private func fetchAndAttach(_ env: NotifyEnvelope, origin: String) async {
        let base = URL(string: origin)
        let cap = env.cap
        async let card: NotifyCard? = {
            guard env.more, let base, let cap else { return nil }
            return await AnswerClient.fetchCard(base: base, cap: cap)
        }()
        async let media: [(String, Data, String)] = fetchMedia(env, base: base, cap: cap)
        let (fetchedCard, files) = await (card, media)
        if let fetchedCard, let data = try? JSONSerialization.data(withJSONObject: fetchedCard.raw) { setFullCard(data) }
        var made: [UNNotificationAttachment] = []
        for (name, data, type) in files {
            if let attachment = makeAttachment(name: name, data: data, type: type) { made.append(attachment) }
        }
        if made.isEmpty, let png = await MainActor.run(body: { CardThumb.png(kind: env.kind) }), let attachment = makeAttachment(name: "thumb.png", data: png, type: UTType.png.identifier) {
            made.append(attachment)
        }
        lock.withLock { attachments = made }
    }

    private func setFullCard(_ data: Data) { lock.lock(); fullCard = data; lock.unlock() }

    private func fetchMedia(_ env: NotifyEnvelope, base: URL?, cap: String?) async -> [(String, Data, String)] {
        guard let base, let cap, let m = env.media else { return [] }
        var out: [(String, Data, String)] = []
        switch env.kind {
        case .image:
            if let data = await AnswerClient.fetchMedia(base: base, cap: cap, id: m.id, poster: false, timeout: Self.budget - 2) {
                out.append(m.mime == "image/jpeg" ? ("image.jpg", data, UTType.jpeg.identifier) : ("image.png", data, UTType.png.identifier))
            }
        case .file, .video:
            if let poster = await AnswerClient.fetchMedia(base: base, cap: cap, id: m.id, poster: true, timeout: Self.budget - 2) {
                out.append(("poster.png", poster, UTType.png.identifier))
            }
            if env.kind == .video, m.bytes <= Self.videoAttachLimit,
               let data = await AnswerClient.fetchMedia(base: base, cap: cap, id: m.id, poster: false, timeout: Self.budget - 2) {
                out.append(("video.mp4", data, UTType.mpeg4Movie.identifier))
            }
        default: break
        }
        return out
    }

    private func makeAttachment(name: String, data: Data, type: String) -> UNNotificationAttachment? {
        lock.lock(); defer { lock.unlock() }
        if workDir == nil {
            let dir = FileManager.default.temporaryDirectory.appendingPathComponent("notify-\(UUID().uuidString)", isDirectory: true)
            guard (try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])) != nil else { return nil }
            workDir = dir
        }
        guard let dir = workDir else { return nil }
        let url = dir.appendingPathComponent(name)
        guard FileManager.default.createFile(atPath: url.path, contents: data, attributes: [.posixPermissions: 0o600]) else { return nil }
        return try? UNNotificationAttachment(identifier: name, url: url, options: [UNNotificationAttachmentOptionsTypeHintKey: type])
    }

    private func deliver() {
        lock.lock()
        guard let pending = handler, let mutable = content else { lock.unlock(); return }
        handler = nil
        if !attachments.isEmpty { mutable.attachments = attachments }
        if let fullCard, let env = envelope, let origin {
            var info = mutable.userInfo as? [String: String] ?? [:]
            info.merge(NotifyUserInfo.encode(env, origin: origin, fullCard: fullCard)) { _, new in new }
            mutable.userInfo = info
        }
        lock.unlock()
        pending(mutable)
    }
}
