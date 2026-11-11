import SwiftUI

struct CardTone {
    let page: Color
    let titlerow: Color
    let field: Color
    let raised: Color
    let linePanel: Color
    let lineFaint: Color
    let lineFrame: Color
    let textBright: Color
    let textPrimary: Color
    let textSecondary: Color
    let textMuted: Color
    let textDim: Color
    let accent: Color
    let good: Color
    let info: Color
    let caution: Color
    let paper: Color
    let ink: Color

    init(page: UInt32, titlerow: UInt32, field: UInt32, raised: UInt32, linePanel: UInt32, lineFaint: UInt32, lineFrame: UInt32, textBright: UInt32, textPrimary: UInt32, textSecondary: UInt32, textMuted: UInt32, textDim: UInt32, accent: UInt32, good: UInt32, info: UInt32, caution: UInt32, paper: UInt32, ink: UInt32) {
        self.page = CardTone.color(page)
        self.titlerow = CardTone.color(titlerow)
        self.field = CardTone.color(field)
        self.raised = CardTone.color(raised)
        self.linePanel = CardTone.color(linePanel)
        self.lineFaint = CardTone.color(lineFaint)
        self.lineFrame = CardTone.color(lineFrame)
        self.textBright = CardTone.color(textBright)
        self.textPrimary = CardTone.color(textPrimary)
        self.textSecondary = CardTone.color(textSecondary)
        self.textMuted = CardTone.color(textMuted)
        self.textDim = CardTone.color(textDim)
        self.accent = CardTone.color(accent)
        self.good = CardTone.color(good)
        self.info = CardTone.color(info)
        self.caution = CardTone.color(caution)
        self.paper = CardTone.color(paper)
        self.ink = CardTone.color(ink)
    }

    private static func color(_ hex: UInt32) -> Color {
        Color(red: Double((hex >> 16) & 255) / 255, green: Double((hex >> 8) & 255) / 255, blue: Double(hex & 255) / 255)
    }
}

enum CardTones {
    static let dark: CardTone = CardTone(page: 0x02161E, titlerow: 0x02161E, field: 0x030C0D, raised: 0x061214, linePanel: 0x1F2E30, lineFaint: 0x1F2E30, lineFrame: 0x3F4649, textBright: 0xFFFFFF, textPrimary: 0xCBD6D9, textSecondary: 0xA3B4BB, textMuted: 0x82898F, textDim: 0x6B7378, accent: 0xFF4652, good: 0x4ACF93, info: 0x6CB0E0, caution: 0xDBCA76, paper: 0xFFFFFF, ink: 0x000000)
    static let light: CardTone = CardTone(page: 0xF2F6F6, titlerow: 0xE6EDED, field: 0xFFFFFF, raised: 0xFFFFFF, linePanel: 0xC3D0D1, lineFaint: 0xD7E1E1, lineFrame: 0x8D9C9E, textBright: 0x000000, textPrimary: 0x14262B, textSecondary: 0x35494E, textMuted: 0x55696E, textDim: 0x5D7176, accent: 0xC4202E, good: 0x12724A, info: 0x1D6FA5, caution: 0x8A6D00, paper: 0xFFFFFF, ink: 0x000000)
}
