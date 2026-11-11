import SwiftUI

enum GlyphPart {
    case path(String, filled: Bool = false)
    case circle(cx: Double, cy: Double, r: Double, filled: Bool = false)
    case rect(x: Double, y: Double, w: Double, h: Double, rx: Double)
}

enum CardGlyphs {
    static func parts(_ name: String) -> [GlyphPart] { table[name] ?? table["idle"]! }

    static func name(for kind: NotifyKind) -> String {
        switch kind {
        case .crosstalk: return "message"
        case .notice: return "idle"
        default: return kind.rawValue
        }
    }

    private static let table: [String: [GlyphPart]] = [
        "question": [.path("M9 9a3 3 0 1 1 4.5 2.6c-1 .6-1.5 1.1-1.5 2.4"), .circle(cx: 12, cy: 17.5, r: 0.8, filled: true), .circle(cx: 12, cy: 12, r: 9)],
        "choice": [.path("M8 6h12M8 12h12M8 18h12"), .circle(cx: 4, cy: 6, r: 1, filled: true), .circle(cx: 4, cy: 12, r: 1, filled: true), .circle(cx: 4, cy: 18, r: 1, filled: true)],
        "permission": [.path("M12 3l7 3v5c0 5-3 8-7 10-4-2-7-5-7-10V6z"), .path("M9.5 12l2 2 3.5-4")],
        "file": [.path("M6 3h8l4 4v14H6z"), .path("M14 3v4h4M9 13h6M9 17h6")],
        "link": [.path("M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"), .path("M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1")],
        "image": [.rect(x: 3, y: 5, w: 18, h: 14, rx: 1.5), .circle(cx: 9, cy: 10, r: 1.6), .path("M4 18l5-5 4 4 3-3 4 4")],
        "video": [.rect(x: 3, y: 5, w: 18, h: 14, rx: 1.5), .path("M10 9l5 3-5 3z", filled: true)],
        "finished": [.circle(cx: 12, cy: 12, r: 9), .path("M8 12.5l3 3 5-6")],
        "died": [.circle(cx: 12, cy: 12, r: 9), .path("M9 9l6 6M15 9l-6 6")],
        "update": [.path("M12 20V6M6 12l6-6 6 6"), .path("M5 20h14")],
        "appupdate": [.rect(x: 5, y: 3, w: 14, h: 18, rx: 2), .path("M12 16V8M9 11l3-3 3 3")],
        "swarm": [.circle(cx: 6, cy: 7, r: 2), .circle(cx: 18, cy: 7, r: 2), .circle(cx: 12, cy: 18, r: 2), .path("M8 7h8M7 9l4 7M17 9l-4 7")],
        "message": [.path("M4 5h16v11H10l-5 4v-4H4z"), .path("M8 9h8M8 12h5")],
        "signin": [.circle(cx: 8, cy: 14, r: 4), .path("M11 12l9-8M17 7l2 2M14 10l2 2")],
        "idle": [.circle(cx: 12, cy: 12, r: 8), .path("M8 12h8")],
        "lock": [.rect(x: 5, y: 11, w: 14, h: 9, rx: 1.5), .path("M8 11V8a4 4 0 0 1 8 0v3")],
        "play": [.path("M7 5l12 7-12 7z", filled: true)],
    ]
}

enum SVGPath {
    static func path(_ d: String) -> Path {
        var scanner = Scanner2(Array(d))
        var path = Path()
        var cur = CGPoint.zero, start = CGPoint.zero, lastCtrl: CGPoint?
        var cmd: Character = "M"
        while true {
            scanner.skipSeparators()
            if scanner.atEnd { break }
            if let c = scanner.peek, c.isLetter { cmd = c; scanner.advance() }
            let rel = cmd.isLowercase
            let base = rel ? cur : .zero
            switch cmd.uppercased() {
            case "M":
                guard let x = scanner.number(), let y = scanner.number() else { return path }
                cur = CGPoint(x: base.x + x, y: base.y + y); start = cur; path.move(to: cur); lastCtrl = nil
                cmd = rel ? "l" : "L"
            case "L":
                guard let x = scanner.number(), let y = scanner.number() else { return path }
                cur = CGPoint(x: base.x + x, y: base.y + y); path.addLine(to: cur); lastCtrl = nil
            case "H":
                guard let x = scanner.number() else { return path }
                cur = CGPoint(x: (rel ? cur.x : 0) + x, y: cur.y); path.addLine(to: cur); lastCtrl = nil
            case "V":
                guard let y = scanner.number() else { return path }
                cur = CGPoint(x: cur.x, y: (rel ? cur.y : 0) + y); path.addLine(to: cur); lastCtrl = nil
            case "C", "S":
                var c1 = cur
                if cmd.uppercased() == "C" {
                    guard let a = scanner.number(), let b = scanner.number() else { return path }
                    c1 = CGPoint(x: base.x + a, y: base.y + b)
                } else if let l = lastCtrl {
                    c1 = CGPoint(x: 2 * cur.x - l.x, y: 2 * cur.y - l.y)
                }
                guard let x2 = scanner.number(), let y2 = scanner.number(), let x = scanner.number(), let y = scanner.number() else { return path }
                let c2 = CGPoint(x: base.x + x2, y: base.y + y2), end = CGPoint(x: base.x + x, y: base.y + y)
                path.addCurve(to: end, control1: c1, control2: c2); lastCtrl = c2; cur = end
            case "A":
                guard let rx = scanner.number(), scanner.number() != nil, scanner.number() != nil,
                      let large = scanner.flag(), let sweep = scanner.flag(),
                      let x = scanner.number(), let y = scanner.number() else { return path }
                let end = CGPoint(x: base.x + x, y: base.y + y)
                addArc(&path, from: cur, to: end, r: abs(rx), large: large, sweep: sweep)
                cur = end; lastCtrl = nil
            case "Z":
                path.closeSubpath(); cur = start; lastCtrl = nil
            default:
                return path
            }
        }
        return path
    }

    private static func addArc(_ path: inout Path, from p0: CGPoint, to p1: CGPoint, r radius: Double, large: Bool, sweep: Bool) {
        let dx = (p0.x - p1.x) / 2, dy = (p0.y - p1.y) / 2
        let d2 = dx * dx + dy * dy
        guard d2 > 0, radius > 0 else { path.addLine(to: p1); return }
        var r = radius
        if r * r < d2 { r = d2.squareRoot() }
        let coef = (large == sweep ? -1.0 : 1.0) * max(0, (r * r - d2) / d2).squareRoot()
        let cxp = coef * dy, cyp = -coef * dx
        let c = CGPoint(x: cxp + (p0.x + p1.x) / 2, y: cyp + (p0.y + p1.y) / 2)
        let a0 = atan2((dy - cyp) / r, (dx - cxp) / r), a1 = atan2((-dy - cyp) / r, (-dx - cxp) / r)
        var delta = a1 - a0
        if !sweep && delta > 0 { delta -= 2 * .pi }
        if sweep && delta < 0 { delta += 2 * .pi }
        let n = max(1, Int((abs(delta) / (.pi / 2)).rounded(.up)))
        let step = delta / Double(n), t = 4.0 / 3.0 * tan(step / 4)
        var a = a0
        for _ in 0..<n {
            let b = a + step
            let s = CGPoint(x: c.x + r * cos(a), y: c.y + r * sin(a)), e = CGPoint(x: c.x + r * cos(b), y: c.y + r * sin(b))
            path.addCurve(to: e,
                          control1: CGPoint(x: s.x - t * r * sin(a), y: s.y + t * r * cos(a)),
                          control2: CGPoint(x: e.x + t * r * sin(b), y: e.y - t * r * cos(b)))
            a = b
        }
    }

    private struct Scanner2 {
        let chars: [Character]
        var i = 0
        init(_ chars: [Character]) { self.chars = chars }
        var atEnd: Bool { i >= chars.count }
        var peek: Character? { i < chars.count ? chars[i] : nil }
        mutating func advance() { i += 1 }
        mutating func skipSeparators() { while let c = peek, c == " " || c == "," || c == "\n" { i += 1 } }
        mutating func flag() -> Bool? {
            skipSeparators()
            guard let c = peek, c == "0" || c == "1" else { return nil }
            i += 1
            return c == "1"
        }
        mutating func number() -> Double? {
            skipSeparators()
            var s = ""
            if let c = peek, c == "-" || c == "+" { s.append(c); i += 1 }
            var dot = false
            while let c = peek, c.isNumber || (c == "." && !dot) {
                if c == "." { dot = true }
                s.append(c); i += 1
            }
            return Double(s)
        }
    }
}

struct CardGlyph: View {
    let name: String
    var size: CGFloat = 20
    let color: Color

    var body: some View {
        let scale = size / 24
        Canvas { ctx, _ in
            let transform = CGAffineTransform(scaleX: scale, y: scale)
            let style = StrokeStyle(lineWidth: 1.7 * scale, lineCap: .round, lineJoin: .round)
            for part in CardGlyphs.parts(name) {
                var filled = false
                var path: Path
                switch part {
                case let .path(d, f): path = SVGPath.path(d); filled = f
                case let .circle(cx, cy, r, f): path = Path(ellipseIn: CGRect(x: cx - r, y: cy - r, width: 2 * r, height: 2 * r)); filled = f
                case let .rect(x, y, w, h, rx): path = Path(roundedRect: CGRect(x: x, y: y, width: w, height: h), cornerRadius: rx)
                }
                path = path.applying(transform)
                if filled { ctx.fill(path, with: .color(color)) }
                ctx.stroke(path, with: .color(color), style: style)
            }
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }
}
