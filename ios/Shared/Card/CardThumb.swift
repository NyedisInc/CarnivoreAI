import SwiftUI
import UIKit

struct CardThumb: View {
    let kind: NotifyKind
    var side: CGFloat = 44

    private var tone: CardTone { CardTones.dark }
    private var hue: Color {
        switch CardModel.hue(for: kind) {
        case .caution: return tone.caution
        case .good: return tone.good
        case .info: return tone.info
        case .danger: return tone.accent
        case .quiet: return tone.textMuted
        }
    }

    var body: some View {
        let u = side / 44
        VStack(spacing: 3 * u) {
            if kind == .died {
                VStack(spacing: 3 * u) {
                    ForEach(0..<4, id: \.self) { i in
                        Rectangle().fill(i == 3 ? tone.accent : tone.textDim).frame(width: i == 1 ? 0.55 * (side - 10 * u) : (i == 3 ? 0.7 : 1) * (side - 10 * u), height: 2 * u)
                    }
                }
                .frame(maxHeight: .infinity)
            } else {
                Group {
                    if kind == .permission {
                        Text(verbatim: "$_").font(CardFont.mono(15 * u, bold: true)).foregroundColor(hue)
                    } else {
                        CardGlyph(name: CardGlyphs.name(for: kind), size: 22 * u, color: hue)
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity).padding(.top, 3 * u)
                Rectangle().fill(hue).frame(width: 0.7 * (side - 10 * u), height: 2 * u).frame(maxWidth: .infinity, alignment: .leading)
                Rectangle().fill(kind == .permission ? tone.good : tone.lineFrame).frame(height: 2 * u)
            }
        }
        .padding(EdgeInsets(top: 5 * u, leading: 5 * u, bottom: 4 * u, trailing: 5 * u))
        .frame(width: side, height: side)
        .background(tone.page)
        .overlay(alignment: .top) { Rectangle().fill(hue).frame(height: 4 * u) }
        .clipShape(RoundedRectangle(cornerRadius: 8 * u))
        .overlay(RoundedRectangle(cornerRadius: 8 * u).stroke(tone.textBright.opacity(0.14), lineWidth: 1))
    }

    @MainActor static func png(kind: NotifyKind, side: CGFloat = 44) -> Data? {
        let renderer = ImageRenderer(content: CardThumb(kind: kind, side: side))
        renderer.scale = 3
        return renderer.uiImage?.pngData()
    }
}
