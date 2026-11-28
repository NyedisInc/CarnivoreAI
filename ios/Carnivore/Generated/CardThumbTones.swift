import UIKit

enum CardThumbTones {
    static let page = rgb(0x02161E)
    static let titlerow = rgb(0x02161E)
    static let field = rgb(0x030C0D)
    static let raised = rgb(0x061214)
    static let linePanel = rgb(0x1F2E30)
    static let lineFaint = rgb(0x1F2E30)
    static let lineFrame = rgb(0x3F4649)
    static let textBright = rgb(0xFFFFFF)
    static let textPrimary = rgb(0xCBD6D9)
    static let textSecondary = rgb(0xA3B4BB)
    static let textMuted = rgb(0x82898F)
    static let textDim = rgb(0x6B7378)
    static let accent = rgb(0xFF4652)
    static let good = rgb(0x4ACF93)
    static let info = rgb(0x6CB0E0)
    static let caution = rgb(0xDBCA76)
    static let paper = rgb(0xFFFFFF)
    static let ink = rgb(0x000000)

    private static func rgb(_ hex: UInt32) -> UIColor {
        UIColor(red: CGFloat((hex >> 16) & 255) / 255, green: CGFloat((hex >> 8) & 255) / 255, blue: CGFloat(hex & 255) / 255, alpha: 1)
    }
}
