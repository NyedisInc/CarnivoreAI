import CoreGraphics
import UIKit

enum CardThumbCG {
    private static func hueColor(for kind: NotifyKind) -> UIColor {
        switch kind {
        case .yesno, .choice, .permission, .swarm: return CardThumbTones.caution
        case .finished: return CardThumbTones.good
        case .died, .signin: return CardThumbTones.accent
        case .notice: return CardThumbTones.textMuted
        default: return CardThumbTones.info
        }
    }

    private static func symbolText(for kind: NotifyKind) -> String {
        switch kind {
        case .permission: return "$_"
        case .yesno, .choice: return "?"
        case .finished: return "✓"
        case .died: return "×"
        case .signin: return "!"
        case .swarm: return "◈"
        case .crosstalk: return "⇄"
        case .file: return "▤"
        case .link: return "↗"
        case .image: return "▣"
        case .video: return "▶"
        case .update, .appupdate: return "↑"
        case .notice: return "•"
        }
    }

    static func png(kind: NotifyKind, side: CGFloat = 44) -> Data? {
        let format = UIGraphicsImageRendererFormat()
        format.scale = 3
        format.opaque = false
        let size = CGSize(width: side, height: side)
        let renderer = UIGraphicsImageRenderer(size: size, format: format)
        let hue = hueColor(for: kind)
        let u = side / 44.0

        return renderer.pngData { ctx in
            let cg = ctx.cgContext
            let rect = CGRect(origin: .zero, size: size)
            let clip = UIBezierPath(roundedRect: rect, cornerRadius: 8 * u)
            clip.addClip()

            CardThumbTones.page.setFill()
            cg.fill(rect)

            hue.setFill()
            cg.fill(CGRect(x: 0, y: 0, width: side, height: 4 * u))

            let padX = 5 * u
            let contentW = side - 10 * u

            if kind == .died {
                let widths: [CGFloat] = [1.0, 0.55, 1.0, 0.7]
                for (i, frac) in widths.enumerated() {
                    let y = 11 * u + CGFloat(i) * 6 * u
                    (i == 3 ? CardThumbTones.accent : CardThumbTones.textDim).setFill()
                    cg.fill(CGRect(x: padX, y: y, width: contentW * frac, height: 2 * u))
                }
            } else {
                let text = symbolText(for: kind) as NSString
                let fontSize: CGFloat = kind == .permission ? 14 * u : 18 * u
                let font = UIFont.monospacedSystemFont(ofSize: fontSize, weight: .bold)
                let attrs: [NSAttributedString.Key: Any] = [.font: font, .foregroundColor: hue]
                let textSize = text.size(withAttributes: attrs)
                let drawOrigin = CGPoint(
                    x: (side - textSize.width) / 2.0,
                    y: 7 * u + (22 * u - textSize.height) / 2.0
                )
                text.draw(at: drawOrigin, withAttributes: attrs)

                hue.setFill()
                cg.fill(CGRect(x: padX, y: side - 10 * u, width: contentW * 0.7, height: 2 * u))

                (kind == .permission ? CardThumbTones.good : CardThumbTones.lineFrame).setFill()
                cg.fill(CGRect(x: padX, y: side - 6 * u, width: contentW, height: 2 * u))
            }

            CardThumbTones.textBright.withAlphaComponent(0.14).setStroke()
            let strokePath = UIBezierPath(roundedRect: rect.insetBy(dx: 0.5, dy: 0.5), cornerRadius: 8 * u)
            strokePath.lineWidth = 1
            strokePath.stroke()
        }
    }
}
