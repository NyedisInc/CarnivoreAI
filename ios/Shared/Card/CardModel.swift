import Foundation

enum CardHue: Equatable { case caution, good, info, danger, quiet }

struct CardRow: Equatable {
    let key: String
    let value: String
}

struct CardOption: Equatable {
    let letter: String
    let label: String
    let desc: String
}

enum CardBlock: Equatable {
    case question(String, large: Bool, clipped: Bool)
    case secondary(String)
    case rows([CardRow])
    case command(lines: [String], clipped: Bool)
    case options([CardOption])
    case fileHead(name: String, type: String, meta: String, from: String)
    case domain(host: String, path: String)
    case warning(String)
    case image(caption: String)
    case video(caption: String, overBudget: String?)
    case version(to: String, current: String)
    case changes([String])
    case fileList([[String]])
    case tail([String])
    case exitCode(String)
    case positions([[String]])
    case thread([[String]])
    case more(String)
}

struct CardModel: Equatable {
    var kind: NotifyKind
    var word: String
    var whereText: String
    var hue: CardHue
    var blocks: [CardBlock]
    var isEmpty = false

    static let clipLines = NotifyContract.limitCardClipLines
    static let clipChars = 12 * 34

    static var empty: CardModel {
        CardModel(kind: .notice, word: Strings.cardStateNothing, whereText: Strings.cardStateNoOpen, hue: .quiet,
                  blocks: [.question(Strings.cardStateEmpty, large: false, clipped: false)], isEmpty: true)
    }

    static func hue(for kind: NotifyKind) -> CardHue {
        switch kind {
        case .yesno, .choice, .permission, .swarm: return .caution
        case .finished: return .good
        case .died, .signin: return .danger
        case .notice: return .quiet
        default: return .info
        }
    }

    static func word(for kind: NotifyKind) -> String {
        switch kind {
        case .yesno: return Strings.cardWordYesno
        case .choice: return Strings.cardWordChoice
        case .permission: return Strings.cardWordPermission
        case .file: return Strings.cardWordFile
        case .link: return Strings.cardWordLink
        case .image: return Strings.cardWordImage
        case .video: return Strings.cardWordVideo
        case .finished: return Strings.cardWordFinished
        case .died: return Strings.cardWordDied
        case .update: return Strings.cardWordUpdate
        case .appupdate: return Strings.cardWordAppupdate
        case .swarm: return Strings.cardWordSwarm
        case .crosstalk: return Strings.cardWordCrosstalk
        case .signin: return Strings.cardWordSignin
        case .notice: return Strings.cardWordNotice
        }
    }

    static func make(kind: NotifyKind, card: NotifyCard, body: String?, videoOverBudget: String? = nil) -> CardModel {
        let strip = card.strings("strip")
        let agent = card.string("agent") ?? ""
        let computer = card.string("computer") ?? ""
        let word = strip.first ?? Self.word(for: kind)
        let whereText = [strip.count > 1 ? strip[1] : agent, strip.count > 2 ? strip[2] : computer].filter { !$0.isEmpty }.joined(separator: " . ")
        var model = CardModel(kind: kind, word: word, whereText: whereText, hue: hue(for: kind), blocks: [])
        if card.isEmpty {
            guard let body, !body.isEmpty else { return .empty }
            model.blocks = [question(body, large: false)]
            return model
        }
        model.blocks = blocks(kind: kind, card: card, body: body ?? "", agent: agent, computer: computer, videoOverBudget: videoOverBudget)
        return model
    }

    private static func rows(_ list: [CardRow]) -> [CardBlock] {
        let shown = list.filter { !$0.value.isEmpty }
        return shown.isEmpty ? [] : [.rows(shown)]
    }

    private static func question(_ text: String, large: Bool) -> CardBlock {
        .question(text, large: large, clipped: text.count > clipChars)
    }

    private static func withMore(_ block: CardBlock) -> [CardBlock] {
        if case let .question(_, _, clipped) = block, clipped { return [block, .more(Strings.cardStateMore)] }
        return [block]
    }

    private static func blocks(kind: NotifyKind, card: NotifyCard, body: String, agent: String, computer: String, videoOverBudget: String?) -> [CardBlock] {
        let ask = card.string("ask") ?? body
        let from = Strings.fill(Strings.cardSubDefault, ["word": agent, "computer": computer])
        switch kind {
        case .yesno:
            return withMore(question(ask, large: true)) + rows([
                CardRow(key: Strings.cardRowFrom, value: from), CardRow(key: Strings.cardRowAsked, value: card.string("ts") ?? ""),
                CardRow(key: Strings.cardRowWaiting, value: Strings.cardValueWaitingOnAnswer)])
        case .choice:
            var out = withMore(question(ask, large: false))
            out.append(.options(card.rows("opts").filter { $0.count >= 2 }.map { CardOption(letter: $0[0].uppercased(), label: $0[1], desc: $0.count > 2 ? $0[2] : "") }))
            if card.bool("multi") || (card.int("qcount") ?? 1) > 1 { out.append(.secondary(Strings.cardStateOpenToAnswer)) }
            return out
        case .permission:
            let cmd = card.strings("cmd")
            let clipped = cmd.count > clipLines
            var out: [CardBlock] = [question(Strings.fill(Strings.cardQPermission, ["body": body]), large: false),
                                    .command(lines: Array(cmd.prefix(clipLines)), clipped: clipped)]
            if clipped { out.append(.more(Strings.fill(Strings.cardStateMoreCount, ["count": String(cmd.count), "unit": Strings.cardUnitLines]))) }
            out += rows([CardRow(key: Strings.cardRowTool, value: card.string("tool") ?? ""), CardRow(key: Strings.cardRowFolder, value: card.string("dir") ?? ""),
                         CardRow(key: Strings.cardRowComputer, value: computer), CardRow(key: Strings.cardRowAllow, value: Strings.cardValueNeedsFaceId)])
            return out
        case .file:
            let name = card.string("name") ?? ""
            let type = (name.split(separator: ".").last.map(String.init) ?? (card.string("mime") ?? "").split(separator: "/").last.map(String.init) ?? "").lowercased()
            let size = sizeText(card.int("bytes") ?? 0)
            let meta = (card.int("pages") ?? 0) > 0 ? Strings.fill(Strings.cardValueFilePages, ["size": size, "pages": String(card.int("pages") ?? 0)]) : size
            return [.fileHead(name: name, type: type, meta: meta, from: Strings.cardRowFrom + " " + (card.string("from") ?? agent))]
                + rows([CardRow(key: Strings.cardRowFirstPage, value: card.strings("head").joined(separator: "\n"))])
        case .link:
            let url = card.string("url") ?? ""
            var rows: [CardRow] = []
            if let title = card.string("title"), !title.isEmpty {
                rows.append(CardRow(key: Strings.cardRowPage, value: title))
            }
            rows += [CardRow(key: Strings.cardRowAddress, value: url), CardRow(key: Strings.cardRowOpensIn, value: Strings.cardValueSafari)]
            var out: [CardBlock] = [.domain(host: card.string("host") ?? "", path: URL(string: url)?.path ?? "")]
            if card.bool("mixed_script") { out.append(.warning(Strings.cardValueMixedScript)) }
            return out + [.rows(rows)]
        case .image:
            let caption = card.string("caption") ?? ""
            return [.image(caption: Strings.fill(Strings.cardValueImageSize, ["name": caption, "w": String(card.int("w") ?? 0), "h": String(card.int("h") ?? 0)]))]
        case .video:
            let caption = [card.string("caption") ?? "", durationText(card.int("dur") ?? 0)].filter { !$0.isEmpty }.joined(separator: ", ")
            return [.video(caption: caption, overBudget: videoOverBudget)]
        case .finished:
            var out: [CardBlock] = [.question(Strings.fill(Strings.cardValueDoneIn, ["mins": String(card.int("mins") ?? 0)]), large: false, clipped: false)]
            let files = card.strings("files")
            let stats = card.intRows("stats")
            if !files.isEmpty { out.append(.fileList(files.enumerated().map { i, path in i < stats.count && stats[i].count == 2 ? [path, "+\(stats[i][0]) -\(stats[i][1])"] : [path] })) }
            return out
        case .died:
            let tail = card.strings("tail")
            var out: [CardBlock] = tail.isEmpty ? [] : [.tail(Array(tail.suffix(clipLines)))]
            if tail.count > clipLines { out.append(.more(Strings.fill(Strings.cardStateMoreCount, ["count": String(tail.count), "unit": Strings.cardUnitLines]))) }
            if let code = card.int("exit") { out.append(.exitCode(Strings.fill(Strings.cardValueExitCode, ["code": String(code)]))) }
            return out
        case .update:
            let from = card.string("from") ?? "", to = card.string("to") ?? ""
            let version = from.isEmpty ? to : to.isEmpty ? from : Strings.fill(Strings.cardValueFromTo, ["from": from, "to": to])
            return withMore(question(body, large: false)) + rows([
                CardRow(key: Strings.cardRowAgent, value: agent), CardRow(key: Strings.cardRowVersion, value: version),
                CardRow(key: Strings.cardRowSessions, value: card.strings("sessions").joined(separator: ", "))])
        case .appupdate:
            let have = card.string("from").map { Strings.fill(Strings.cardValueYouHave, ["version": $0]) } ?? ""
            let notes = card.strings("notes")
            return [.version(to: card.string("to") ?? "", current: have)] + (notes.isEmpty ? [] : [.changes(notes)])
        case .swarm:
            return withMore(question(ask, large: false)) + [.positions(card.rows("positions"))]
        case .crosstalk:
            let thread = card.rows("thread")
            return [.thread(thread.isEmpty ? [[agent, card.string("text") ?? body]] : thread)]
        case .signin:
            let account = card.string("account") ?? agent
            let named = card.string("provider").map { "\(account) (\($0))" } ?? account
            return withMore(question(body, large: false)) + rows([
                CardRow(key: Strings.cardRowAccount, value: named), CardRow(key: Strings.cardRowReason, value: card.string("reason") ?? ""),
                CardRow(key: Strings.cardRowWaiting, value: card.strings("sessions").joined(separator: ", "))])
        case .notice:
            return [question(card.string("title") ?? "", large: false), .secondary(card.string("body") ?? body)]
        }
    }

    static func sizeText(_ bytes: Int) -> String {
        if bytes >= 1_048_576 {
            let mb = Double(bytes) / 1_048_576
            return mb < 10 ? String(format: "%.1f MB", mb) : "\(Int(mb.rounded())) MB"
        }
        return bytes >= 1024 ? "\(Int((Double(bytes) / 1024).rounded())) KB" : "\(bytes) B"
    }

    static func durationText(_ seconds: Int) -> String {
        seconds <= 0 ? "" : "\(seconds / 60):" + String(format: "%02d", seconds % 60)
    }
}
