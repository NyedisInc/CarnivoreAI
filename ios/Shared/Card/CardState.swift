import AVFoundation
import SwiftUI
import UIKit
import UniformTypeIdentifiers
import UserNotifications

@MainActor final class CardState: ObservableObject {
    @Published var model: CardModel = .empty
    @Published var media = CardMedia()
    @Published var phase: CardPhase = .normal
    private(set) var info: NotifyUserInfo?
    private(set) var card = NotifyCard(raw: [:])
    private var agent = ""

    func load(content: UNNotificationContent) {
        let userInfo = NotifyUserInfo(userInfo: content.userInfo)
        info = userInfo
        guard let userInfo else { model = .empty; return }
        card = NotifyCard(json: userInfo.cardJSON)
        agent = card.string("agent") ?? ""
        var over: String? = nil
        if let m = userInfo.media, userInfo.kind == .video {
            if m.bytes > 50 * 1_048_576 { over = Strings.fill(Strings.cardStateOverBudget, ["size": CardModel.sizeText(m.bytes), "limit": "50 MB"]) }
            else if m.bytes > NotifyUserInfoLimits.videoPlayBytes { over = Strings.cardStatePlayOnComputer }
        }
        model = CardModel.make(kind: userInfo.kind, card: card, body: content.body, videoOverBudget: over)
        media = Self.media(from: content.attachments, kind: userInfo.kind)
        if let settle = userInfo.settle { phase = .settled(settle.line); agent = settle.agent }
        else if userInfo.isExpired() { phase = .failed(Strings.cardStateExpired) }
    }

    static func media(from attachments: [UNNotificationAttachment], kind: NotifyKind) -> CardMedia {
        var out = CardMedia()
        for a in attachments {
            let scoped = a.url.startAccessingSecurityScopedResource()
            defer { if scoped { a.url.stopAccessingSecurityScopedResource() } }
            if UTType(a.type)?.conforms(to: .movie) == true { out.player = copyToTemp(a.url).map { AVPlayer(url: $0) }; continue }
            guard let data = try? Data(contentsOf: a.url), let image = UIImage(data: data) else { continue }
            if kind == .image { out.image = image } else if out.poster == nil { out.poster = image }
        }
        return out
    }

    private static func copyToTemp(_ url: URL) -> URL? {
        let dest = FileManager.default.temporaryDirectory.appendingPathComponent("card-\(UUID().uuidString).mp4")
        return (try? FileManager.default.copyItem(at: url, to: dest)) == nil ? nil : dest
    }

    func press(action: String, text: String?, session: URLSession = .shared) async -> Bool {
        guard let info else { return true }
        switch action {
        case "play":
            media.player?.play()
            return false
        case "later":
            phase = .answered(line: Strings.cardAnswerLater, detail: closes())
            return true
        case "copy_link":
            let url = card.string("url") ?? ""
            UIPasteboard.general.string = url
            phase = .answered(line: Strings.fill(Strings.cardAnswerCopied, ["url": url]), detail: closes())
            return true
        default: break
        }
        guard let base = info.base, let cap = info.cap else { phase = .failed(Strings.cardStateNotSent); return false }
        let outcome = await AnswerClient.act(base: base, cap: cap, action: action, text: text, session: session)
        return apply(outcome, action: action, text: text)
    }

    func apply(_ outcome: AnswerOutcome, action: String, text: String?) -> Bool {
        switch outcome {
        case let .sent(who, working, _):
            let name = who ?? agent
            phase = .answered(line: line(action: action, text: text, agent: name, working: working), detail: closes())
            return true
        case .alreadyAnswered: phase = .failed(Strings.cardStateAlreadyAnswered)
        case .alreadyUsed: phase = .failed(Strings.cardStateAlreadyUsed)
        case .expired: phase = .failed(Strings.cardStateExpired)
        case .notSent: phase = .failed(Strings.cardStateNotSent)
        }
        return false
    }

    private func line(action: String, text: String?, agent: String, working: Bool) -> String {
        if let text, !text.isEmpty { return Strings.fill(Strings.cardAnswerSentReply, ["agent": agent]) }
        switch action {
        case "reopen": return Strings.fill(Strings.cardAnswerReopening, ["agent": agent])
        case "restart_agents":
            return Strings.fill(Strings.cardAnswerRestarting, ["count": String(card.strings("sessions").count), "agent": agent, "version": card.string("to") ?? ""])
        case "install": return Strings.fill(Strings.cardAnswerInstalling, ["version": card.string("to") ?? ""])
        default: return working ? Strings.fill(Strings.cardStateSentWorking, ["agent": agent]) : Strings.cardStateSent
        }
    }

    private func closes() -> String {
        let f = DateFormatter()
        f.dateFormat = "H:mm"
        return Strings.fill(Strings.cardStateCloses, ["time": f.string(from: Date()), "where": Strings.cardWhereIphone])
    }
}

enum NotifyUserInfoLimits {
    static let videoPlayBytes = 15 * 1_048_576
}
