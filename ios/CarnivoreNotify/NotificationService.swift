import CryptoKit
import Foundation
import UniformTypeIdentifiers
import UserNotifications

private final class PushReplayGuard: @unchecked Sendable {
    private let lock = NSLock()
    private var seen: [Data] = []
    private let maxEntries = 256

    func isReplay(_ blobString: String) -> Bool {
        let digest = Data(SHA256.hash(data: Data(blobString.utf8)))
        return lock.withLock {
            if seen.contains(digest) { return true }
            seen.append(digest)
            if seen.count > maxEntries { seen.removeFirst(seen.count - maxEntries) }
            return false
        }
    }
}

final class NotificationService: UNNotificationServiceExtension, @unchecked Sendable {
    static let budget: TimeInterval = 22
    static let videoAttachLimit = 15 * 1_048_576
    static let imageAttachLimit = 12 * 1_048_576

    private static let replayGuard = PushReplayGuard()

    private final class RequestContext: @unchecked Sendable {
        let lock = NSLock()
        var handler: ((UNNotificationContent) -> Void)?
        let content: UNMutableNotificationContent
        var attachments: [UNNotificationAttachment] = []
        var fullCard: Data?
        var envelope: NotifyEnvelope?
        var origin: String?
        var workDir: URL?
        var fetchTask: Task<Void, Never>?
        var timer: DispatchWorkItem?

        init(content: UNMutableNotificationContent, handler: @escaping (UNNotificationContent) -> Void) {
            self.content = content
            self.handler = handler
        }

        func setEnvelope(_ env: NotifyEnvelope, origin: String) {
            lock.withLock {
                self.envelope = env
                self.origin = origin
            }
        }

        func setFullCard(_ data: Data) {
            lock.withLock { self.fullCard = data }
        }

        func setAttachments(_ made: [UNNotificationAttachment]) {
            lock.withLock { self.attachments = made }
        }

        func setTasks(timer: DispatchWorkItem, fetchTask: Task<Void, Never>) {
            lock.withLock {
                self.timer = timer
                self.fetchTask = fetchTask
            }
        }

        func makeAttachmentFromData(name: String, data: Data, type: String) -> UNNotificationAttachment? {
            guard let dir = ensureWorkDir() else { return nil }
            let url = dir.appendingPathComponent(name)
            guard (try? data.write(to: url, options: [.atomic, .completeFileProtection])) != nil else { return nil }
            try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
            return try? UNNotificationAttachment(identifier: name, url: url, options: [UNNotificationAttachmentOptionsTypeHintKey: type])
        }

        func makeAttachmentFromFile(name: String, tempURL: URL, type: String) -> UNNotificationAttachment? {
            guard let dir = ensureWorkDir() else {
                try? FileManager.default.removeItem(at: tempURL)
                return nil
            }
            let dest = dir.appendingPathComponent(name)
            try? FileManager.default.removeItem(at: dest)
            do {
                try FileManager.default.moveItem(at: tempURL, to: dest)
                try? FileManager.default.setAttributes([
                    .posixPermissions: 0o600,
                    .protectionKey: FileProtectionType.complete,
                ], ofItemAtPath: dest.path)
                return try UNNotificationAttachment(identifier: name, url: dest, options: [UNNotificationAttachmentOptionsTypeHintKey: type])
            } catch {
                try? FileManager.default.removeItem(at: tempURL)
                return nil
            }
        }

        private func ensureWorkDir() -> URL? {
            lock.withLock {
                if let existing = workDir { return existing }
                let dir = FileManager.default.temporaryDirectory
                    .appendingPathComponent("notify-\(UUID().uuidString)", isDirectory: true)
                guard (try? FileManager.default.createDirectory(
                    at: dir, withIntermediateDirectories: true,
                    attributes: [.posixPermissions: 0o700]
                )) != nil else { return nil }
                workDir = dir
                return dir
            }
        }

        func deliver(genericOnEmpty: Bool = false) {
            let snapshot: (
                handler: ((UNNotificationContent) -> Void)?,
                task: Task<Void, Never>?,
                timer: DispatchWorkItem?,
                attachments: [UNNotificationAttachment],
                fullCard: Data?,
                env: NotifyEnvelope?,
                origin: String?
            ) = lock.withLock {
                guard let pending = handler else { return (nil, nil, nil, [], nil, nil, nil) }
                handler = nil
                let t = fetchTask; let w = timer
                fetchTask = nil; timer = nil
                return (pending, t, w, attachments, fullCard, envelope, origin)
            }
            guard let pending = snapshot.handler else { return }
            snapshot.timer?.cancel()
            snapshot.task?.cancel()

            if genericOnEmpty && snapshot.env == nil {
                content.title = PushRewrite.generic.title
                content.body = PushRewrite.generic.body
                content.userInfo = [:]
                pending(content)
                return
            }

            if !snapshot.attachments.isEmpty { content.attachments = snapshot.attachments }
            var info = content.userInfo as? [String: String] ?? [:]
            if let readyCard = snapshot.fullCard, let readyEnv = snapshot.env, let readyOrigin = snapshot.origin {
                info.merge(NotifyUserInfo.encode(readyEnv, origin: readyOrigin, fullCard: readyCard)) { _, new in new }
            }
            content.userInfo = NotificationMAC.sign(info)
            pending(content)
        }
    }

    private let activeLock = NSLock()
    private var activeContext: RequestContext?

    override func didReceive(
        _ request: UNNotificationRequest,
        withContentHandler contentHandler: @escaping (UNNotificationContent) -> Void
    ) {
        let mutable = (request.content.mutableCopy() as? UNMutableNotificationContent) ?? UNMutableNotificationContent()
        let ctx = RequestContext(content: mutable, handler: contentHandler)
        activeLock.withLock { activeContext = ctx }

        if let rawP = request.content.userInfo["p"] as? String, !rawP.isEmpty, Self.replayGuard.isReplay(rawP) {
            ctx.deliver(genericOnEmpty: true)
            return
        }

        let result = PushRewrite.rewrite(userInfo: request.content.userInfo, candidates: PushKeyStore.candidates())
        mutable.title = result.title
        mutable.body = result.body

        var info: [String: String] = [:]
        if let path = result.path, let origin = result.origin {
            info["path"] = path
            info["origin"] = origin
        }
        if let thread = result.thread, let origin = result.origin {
            mutable.threadIdentifier = "\(origin)|\(thread)"
            info["thread"] = thread
            info["origin"] = origin
        }
        mutable.userInfo = info

        guard let env = result.envelope, let origin = result.origin else {
            ctx.deliver()
            return
        }
        ctx.setEnvelope(env, origin: origin)

        Self.applyV2(env, origin: origin, to: mutable)
        if let settle = env.settle {
            mutable.title = settle.agent
            mutable.body = settle.line
            ctx.deliver()
            return
        }

        let workItem = DispatchWorkItem { [weak ctx] in ctx?.deliver() }
        let fetchTask = Task.detached(priority: .userInitiated) { [weak ctx] in
            guard let ctx else { return }
            await Self.fetchAndAttach(env, origin: origin, ctx: ctx)
            ctx.deliver()
        }
        ctx.setTasks(timer: workItem, fetchTask: fetchTask)
        DispatchQueue.global(qos: .userInitiated).asyncAfter(deadline: .now() + Self.budget, execute: workItem)
    }

    override func serviceExtensionTimeWillExpire() {
        let ctx = activeLock.withLock { activeContext }
        ctx?.deliver(genericOnEmpty: true)
    }

    private static func applyV2(_ env: NotifyEnvelope, origin: String, to mutable: UNMutableNotificationContent) {
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

    private static func fetchAndAttach(_ env: NotifyEnvelope, origin: String, ctx: RequestContext) async {
        let base = URL(string: origin).flatMap { NotifyUserInfo.isAllowedBase($0) ? $0 : nil }
        let cap = env.cap
        async let card: NotifyCard? = {
            guard env.more, let base, let cap else { return nil }
            return await AnswerClient.fetchCard(base: base, cap: cap)
        }()
        async let mediaFiles: [(String, URL, String)] = fetchMediaFiles(env, base: base, cap: cap)
        let (fetchedCard, files) = await (card, mediaFiles)
        if Task.isCancelled {
            for (_, url, _) in files { try? FileManager.default.removeItem(at: url) }
            return
        }
        if let fetchedCard, let data = try? JSONSerialization.data(withJSONObject: fetchedCard.raw) {
            ctx.setFullCard(data)
        }
        var made: [UNNotificationAttachment] = []
        for (name, tempURL, type) in files {
            if let attachment = ctx.makeAttachmentFromFile(name: name, tempURL: tempURL, type: type) {
                made.append(attachment)
            }
        }
        if made.isEmpty,
           let png = CardThumbCG.png(kind: env.kind),
           let attachment = ctx.makeAttachmentFromData(name: "thumb.png", data: png, type: UTType.png.identifier) {
            made.append(attachment)
        }
        ctx.setAttachments(made)
    }

    private static func fetchMediaFiles(_ env: NotifyEnvelope, base: URL?, cap: String?) async -> [(String, URL, String)] {
        guard let base, let cap, let m = env.media, NotifyMedia.isValidId(m.id) else { return [] }
        var out: [(String, URL, String)] = []
        let timeout = Self.budget - 2
        switch env.kind {
        case .image:
            if let file = await AnswerClient.downloadMedia(base: base, cap: cap, id: m.id, poster: false, maxBytes: Self.imageAttachLimit, timeout: timeout) {
                let isJpeg = m.mime == "image/jpeg"
                out.append((isJpeg ? "image.jpg" : "image.png", file, isJpeg ? UTType.jpeg.identifier : UTType.png.identifier))
            }
        case .file, .video:
            if let poster = await AnswerClient.downloadMedia(base: base, cap: cap, id: m.id, poster: true, maxBytes: 4 * 1_048_576, timeout: timeout) {
                out.append(("poster.png", poster, UTType.png.identifier))
            }
            if env.kind == .video, m.bytes <= Self.videoAttachLimit,
               let video = await AnswerClient.downloadMedia(base: base, cap: cap, id: m.id, poster: false, maxBytes: Self.videoAttachLimit, timeout: timeout) {
                out.append(("video.mp4", video, UTType.mpeg4Movie.identifier))
            }
        default: break
        }
        return out
    }
}
