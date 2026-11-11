import AVKit
import CoreText
import SwiftUI
import UIKit

enum CardFont {
    private static let registered: Void = {
        for url in Bundle.main.urls(forResourcesWithExtension: "ttf", subdirectory: nil) ?? [] {
            CTFontManagerRegisterFontsForURL(url as CFURL, .process, nil)
        }
    }()

    static func mono(_ size: CGFloat, bold: Bool = false) -> Font {
        _ = registered
        return Font.custom(bold ? "JetBrainsMono-Bold" : "JetBrainsMono-Regular", size: size, relativeTo: .body)
    }
}

struct CardMedia {
    var image: UIImage? = nil
    var poster: UIImage? = nil
    var player: AVPlayer? = nil
}

enum CardPhase: Equatable {
    case normal
    case answered(line: String, detail: String)
    case settled(String)
    case failed(String)
}

struct CardView: View {
    let model: CardModel
    var media = CardMedia()
    var phase: CardPhase = .normal
    @Environment(\.colorScheme) private var scheme

    private var tone: CardTone { scheme == .dark ? CardTones.dark : CardTones.light }

    private func hueColor(_ hue: CardHue) -> Color {
        switch hue {
        case .caution: return tone.caution
        case .good: return tone.good
        case .info: return tone.info
        case .danger: return tone.accent
        case .quiet: return tone.textMuted
        }
    }

    var body: some View {
        let answered: String? = { if case let .answered(line, _) = phase { return line }; if case let .settled(line) = phase { return line }; return nil }()
        VStack(spacing: 0) {
            strip(answered: answered != nil)
            VStack(alignment: .leading, spacing: 10) {
                if let line = answered { answeredBody(line) } else { blocks }
                if case let .failed(text) = phase { Text(text).font(CardFont.mono(12)).foregroundColor(tone.accent) }
            }
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background(tone.page)
        .foregroundColor(tone.textPrimary)
    }


    private func strip(answered: Bool) -> some View {
        let word = answered ? Strings.cardStateAnswered : model.word
        return HStack(alignment: .center, spacing: 8) {
            Rectangle().fill(answered ? tone.good : hueColor(model.hue)).frame(width: 9, height: 9)
            Text(word.uppercased()).font(CardFont.mono(11, bold: true)).tracking(0.8).foregroundColor(answered ? tone.good : tone.accent)
            Spacer(minLength: 8)
            if !answered {
                Text(model.whereText).font(CardFont.mono(11)).foregroundColor(tone.textDim).multilineTextAlignment(.trailing)
            }
        }
        .padding(.horizontal, 12).padding(.vertical, 4)
        .frame(maxWidth: .infinity, minHeight: 34, alignment: .leading)
        .background(tone.titlerow)
        .overlay(alignment: .bottom) { Rectangle().fill(tone.linePanel).frame(height: 1) }
    }

    private func answeredBody(_ line: String) -> some View {
        VStack(spacing: 10) {
            CardGlyph(name: "finished", size: 34, color: tone.good)
            Text(line).font(CardFont.mono(15)).foregroundColor(tone.textBright).multilineTextAlignment(.center)
            if case let .answered(_, detail) = phase { Text(detail).font(CardFont.mono(11)).foregroundColor(tone.textMuted).multilineTextAlignment(.center) }
        }
        .frame(maxWidth: .infinity).padding(.vertical, 18).padding(.horizontal, 8)
    }


    private var blocks: some View {
        ForEach(Array(model.blocks.enumerated()), id: \.offset) { _, block in blockView(block) }
    }

    @ViewBuilder private func blockView(_ block: CardBlock) -> some View {
        switch block {
        case let .question(text, large, clipped): question(text, large: large, clipped: clipped)
        case let .secondary(text): Text(text).font(CardFont.mono(13)).foregroundColor(tone.textSecondary).lineSpacing(2)
        case let .rows(rows): rowsView(rows)
        case let .command(lines, clipped): command(lines, clipped: clipped)
        case let .options(options): VStack(spacing: 6) { ForEach(Array(options.enumerated()), id: \.offset) { _, o in option(o) } }
        case let .fileHead(name, type, meta, from): fileHead(name: name, type: type, meta: meta, from: from)
        case let .domain(host, path):
            VStack(alignment: .leading, spacing: 2) {
                Text(host).font(CardFont.mono(24)).foregroundColor(tone.info)
                Text(path).font(CardFont.mono(13)).foregroundColor(tone.textSecondary)
            }
        case let .warning(text):
            Text(text).font(CardFont.mono(12)).foregroundColor(tone.caution).padding(8).frame(maxWidth: .infinity, alignment: .leading)
                .background(tone.raised).overlay(Rectangle().stroke(tone.caution, lineWidth: 1))
        case let .image(caption): mediaImage(caption: caption)
        case let .video(caption, over): mediaVideo(caption: caption, overBudget: over)
        case let .version(to, current):
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(to).font(CardFont.mono(28)).foregroundColor(tone.info)
                Text(current).font(CardFont.mono(12)).foregroundColor(tone.textMuted)
            }
        case let .changes(lines): lineList(lines.map { ("+ ", $0) })
        case let .fileList(files): fileList(files)
        case let .tail(lines): tail(lines)
        case let .exitCode(text): Text(text).font(CardFont.mono(13)).foregroundColor(tone.accent)
        case let .positions(pairs): positions(pairs)
        case let .thread(lines): thread(lines)
        case let .more(text):
            Text(text).font(CardFont.mono(12)).foregroundColor(tone.info).padding(.top, 6).frame(maxWidth: .infinity, alignment: .leading)
                .overlay(alignment: .top) { Rectangle().fill(tone.lineFaint).frame(height: 1) }
        }
    }

    private func question(_ text: String, large: Bool, clipped: Bool) -> some View {
        Text(text).font(CardFont.mono(large ? 17 : 15)).foregroundColor(tone.textBright).lineSpacing(large ? 4 : 3)
            .lineLimit(clipped ? CardModel.clipLines : nil).frame(maxWidth: .infinity, alignment: .leading)
            .modifier(FadeBottom(show: clipped, color: tone.page))
    }

    private func rowsView(_ rows: [CardRow]) -> some View {
        VStack(spacing: 0) {
            ForEach(Array(rows.enumerated()), id: \.offset) { i, row in
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    Text(row.key.uppercased()).font(CardFont.mono(10)).tracking(0.6).foregroundColor(tone.textDim)
                    Spacer(minLength: 10)
                    VStack(alignment: .trailing, spacing: 2) {
                        Text(row.value).font(CardFont.mono(12)).foregroundColor(tone.textPrimary).multilineTextAlignment(.trailing)
                    }
                }
                .padding(.vertical, 5)
                .overlay(alignment: .bottom) { Rectangle().fill(tone.lineFaint).frame(height: 1) }
                .overlay(alignment: .top) { if i == 0 { Rectangle().fill(tone.lineFaint).frame(height: 1) } }
            }
        }
    }

    private func command(_ lines: [String], clipped: Bool) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(lines.enumerated()), id: \.offset) { i, line in
                (Text(i == 0 ? "$ " : "").foregroundColor(tone.textDim) + Text(line).foregroundColor(tone.good)).font(CardFont.mono(13))
            }
        }
        .lineSpacing(3)
        .padding(.horizontal, 10).padding(.vertical, 9).frame(maxWidth: .infinity, alignment: .leading)
        .background(tone.field).overlay(Rectangle().stroke(tone.linePanel, lineWidth: 1))
        .modifier(FadeBottom(show: clipped, color: tone.page))
    }

    private func option(_ o: CardOption) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Text(o.letter).font(CardFont.mono(13, bold: true)).foregroundColor(tone.caution)
                .frame(width: 24, height: 24).overlay(Rectangle().stroke(tone.caution, lineWidth: 1))
            VStack(alignment: .leading, spacing: 4) {
                Text(o.label).font(CardFont.mono(13)).foregroundColor(tone.textBright)
                if !o.desc.isEmpty { Text(o.desc).font(CardFont.mono(12)).foregroundColor(tone.textSecondary) }
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 10).padding(.vertical, 8).frame(maxWidth: .infinity, alignment: .leading)
        .background(tone.raised).overlay(Rectangle().stroke(tone.linePanel, lineWidth: 1))
    }

    private func fileHead(name: String, type: String, meta: String, from: String) -> some View {
        HStack(spacing: 12) {
            filePreview.frame(width: 64, height: 82).clipped().overlay(Rectangle().stroke(tone.lineFrame, lineWidth: 1))
            VStack(alignment: .leading, spacing: 2) {
                Text(type).font(CardFont.mono(10)).tracking(0.6).foregroundColor(tone.info).padding(.horizontal, 5).padding(.vertical, 1)
                    .overlay(Rectangle().stroke(tone.info, lineWidth: 1)).padding(.bottom, 2)
                Text(name).font(CardFont.mono(14)).foregroundColor(tone.textBright)
                Text(meta).font(CardFont.mono(12)).foregroundColor(tone.textMuted)
                Text(from).font(CardFont.mono(12)).foregroundColor(tone.textMuted)
            }
            Spacer(minLength: 0)
        }
    }

    @ViewBuilder private var filePreview: some View {
        if let poster = media.poster {
            Image(uiImage: poster).resizable().scaledToFill()
        } else {
            VStack(alignment: .leading, spacing: 6) {
                ForEach(0..<7, id: \.self) { i in Rectangle().fill(tone.lineFrame).frame(width: i == 0 ? 30 : 46, height: 3) }
            }
            .padding(8).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading).background(tone.paper)
        }
    }

    private func mediaImage(caption: String) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            mediaWell { if let image = media.image { Image(uiImage: image).resizable().scaledToFill() } else { CardGlyph(name: "image", size: 34, color: tone.textMuted) } }
            Text(caption).font(CardFont.mono(15)).foregroundColor(tone.textBright).lineSpacing(3)
        }
    }

    private func mediaVideo(caption: String, overBudget: String?) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            mediaWell {
                if let player = media.player, overBudget == nil {
                    VideoPlayer(player: player)
                } else {
                    ZStack {
                        if let poster = media.poster { Image(uiImage: poster).resizable().scaledToFill().opacity(0.55) }
                        CardGlyph(name: "play", size: 26, color: tone.textBright)
                    }
                    .overlay(alignment: .bottom) {
                        if let text = overBudget {
                            Text(text).font(CardFont.mono(12)).foregroundColor(tone.textBright).padding(.horizontal, 10).padding(.vertical, 8)
                                .frame(maxWidth: .infinity, alignment: .leading).background(tone.ink.opacity(0.75))
                        }
                    }
                }
            }
            Text(caption).font(CardFont.mono(15)).foregroundColor(tone.textBright).lineSpacing(3)
        }
    }

    private func mediaWell<Content: View>(@ViewBuilder _ content: () -> Content) -> some View {
        tone.ink.aspectRatio(4.0 / 3.0, contentMode: .fit).frame(maxWidth: .infinity)
            .overlay(content()).clipped().overlay(Rectangle().stroke(tone.lineFrame, lineWidth: 1))
    }

    private func lineList(_ lines: [(String, String)]) -> some View {
        VStack(spacing: 0) {
            ForEach(Array(lines.enumerated()), id: \.offset) { _, line in
                (Text(line.0).foregroundColor(tone.good) + Text(line.1).foregroundColor(tone.textPrimary)).font(CardFont.mono(12))
                    .padding(.vertical, 4).frame(maxWidth: .infinity, alignment: .leading)
                    .overlay(alignment: .bottom) { Rectangle().fill(tone.lineFaint).frame(height: 1) }
            }
        }
    }

    private func fileList(_ files: [[String]]) -> some View {
        VStack(spacing: 0) {
            ForEach(Array(files.enumerated()), id: \.offset) { _, file in
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    Text(file.first ?? "").foregroundColor(tone.textPrimary).frame(maxWidth: .infinity, alignment: .leading)
                    if file.count > 1 { Text(file[1]).foregroundColor(tone.good) }
                }
                .font(CardFont.mono(12)).padding(.vertical, 5)
                .overlay(alignment: .bottom) { Rectangle().fill(tone.lineFaint).frame(height: 1) }
            }
        }
    }

    private func tail(_ lines: [String]) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(lines.enumerated()), id: \.offset) { i, line in
                Text(line).font(CardFont.mono(12)).foregroundColor(i == lines.count - 1 ? tone.textPrimary : tone.textMuted)
            }
        }
        .lineSpacing(3).padding(.horizontal, 10).padding(.vertical, 8).frame(maxWidth: .infinity, alignment: .leading)
        .background(tone.field).overlay(Rectangle().stroke(tone.linePanel, lineWidth: 1))
    }

    private func positions(_ pairs: [[String]]) -> some View {
        HStack(alignment: .top, spacing: 8) {
            ForEach(Array(pairs.prefix(2).enumerated()), id: \.offset) { _, pair in
                VStack(alignment: .leading, spacing: 4) {
                    Text(positionHead(pair)).font(CardFont.mono(12)).foregroundColor(tone.caution)
                    Text(pair.count > 1 ? pair[1] : "").font(CardFont.mono(12)).foregroundColor(tone.textPrimary)
                }
                .padding(.horizontal, 10).padding(.vertical, 8).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                .background(tone.raised).overlay(Rectangle().stroke(tone.linePanel, lineWidth: 1))
            }
        }
        .fixedSize(horizontal: false, vertical: true)
    }

    private func positionHead(_ pair: [String]) -> String {
        let who = pair.first?.lowercased() ?? ""
        return pair.count > 2 && !pair[2].isEmpty ? "\(who) on \(pair[2])" : who
    }

    private func thread(_ lines: [[String]]) -> some View {
        VStack(spacing: 0) {
            ForEach(Array(lines.enumerated()), id: \.offset) { i, line in
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(line.first ?? "").font(CardFont.mono(12)).foregroundColor(tone.textDim)
                    Text(line.count > 1 ? line[1] : "").font(CardFont.mono(12)).foregroundColor(i == lines.count - 1 ? tone.textBright : tone.textPrimary)
                    Spacer(minLength: 0)
                }
                .padding(.vertical, 4).frame(maxWidth: .infinity, alignment: .leading)
                .overlay(alignment: .bottom) { Rectangle().fill(tone.lineFaint).frame(height: 1) }
            }
        }
    }
}

private struct FadeBottom: ViewModifier {
    let show: Bool
    let color: Color

    func body(content: Content) -> some View {
        if show {
            content.overlay(alignment: .bottom) {
                LinearGradient(colors: [color.opacity(0), color], startPoint: .top, endPoint: .bottom).frame(height: 36).allowsHitTesting(false)
            }
        } else {
            content
        }
    }
}
