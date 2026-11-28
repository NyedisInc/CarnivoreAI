import SwiftUI

struct PairingGuideView: View {
    @EnvironmentObject private var theme: ThemeStore
    @State private var step = 0
    @State private var scanProgress: CGFloat = 0
    @State private var pulse = false
    @State private var autoPlaying = true

    private let steps: [(title: String, detail: String)] = [
        ("Open Settings", "Open Carnivore on your computer and click the ⚙ Settings icon."),
        ("Mobile Sync Tab", "Click Remote & Security, then select the Mobile Sync tab."),
        ("Pair a Mobile Device", "Turn \"mobile sync on\", then click \"pair a mobile device\"."),
        ("Scan QR or Show Code", "Scan the QR code — or click \"no camera? show a code\" for the 8-character code."),
    ]

    var body: some View {
        let p = theme.palette
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 8) {
                Text(Strings.appGuideWhereToFindCode.uppercased())
                    .font(.system(size: 11, weight: .semibold, design: .monospaced))
                    .tracking(1.1)
                    .foregroundStyle(p.accent)
                Spacer()
                if !autoPlaying {
                    Button {
                        Haptics.selection()
                        autoPlaying = true
                    } label: {
                        HStack(spacing: 3) {
                            Image(systemName: "play.fill")
                                .font(.system(size: 8))
                            Text(Strings.appGuideAuto.uppercased())
                                .font(.system(size: 10, weight: .semibold, design: .monospaced))
                        }
                        .foregroundStyle(p.accent)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .overlay(RoundedRectangle(cornerRadius: 2).stroke(p.accent.opacity(0.6), lineWidth: 1))
                    }
                    .buttonStyle(.plain)
                }
                Text(Strings.fill(Strings.appGuideStepOf, ["n": String(step + 1), "total": String(steps.count)]).uppercased())
                    .font(.system(size: 11, weight: .medium, design: .monospaced))
                    .foregroundStyle(p.textMuted)
            }
            .padding(.horizontal, 12)
            .frame(height: 32)
            .background(p.ground)

            Rectangle().fill(p.line).frame(height: 1)

            miniDesktopFrame(p)
                .frame(height: 142)
                .padding(10)
                .background(p.page)

            Rectangle().fill(p.line).frame(height: 1)

            VStack(alignment: .leading, spacing: 12) {
                HStack(spacing: 6) {
                    ForEach(0..<steps.count, id: \.self) { idx in
                        Button {
                            Haptics.selection()
                            autoPlaying = false
                            withAnimation(.easeInOut(duration: 0.18)) { step = idx }
                        } label: {
                            Text(String(idx + 1))
                                .font(.system(size: 15, weight: .bold, design: .monospaced))
                                .frame(maxWidth: .infinity)
                                .frame(height: 36)
                                .background(idx == step ? p.accent.opacity(0.22) : p.ground)
                                .foregroundStyle(idx == step ? p.accent : p.textMuted)
                                .overlay(
                                    RoundedRectangle(cornerRadius: 2)
                                        .stroke(idx == step ? p.accent : p.line, lineWidth: idx == step ? 1.5 : 1)
                                )
                        }
                        .buttonStyle(.plain)
                    }
                }

                VStack(alignment: .leading, spacing: 4) {
                    Text(Strings.fill(Strings.appGuideStepTitle, ["n": String(step + 1), "title": steps[step].title]).uppercased())
                        .font(.system(size: 13, weight: .bold, design: .monospaced))
                        .tracking(0.6)
                        .foregroundStyle(p.accent)
                    Text(steps[step].detail)
                        .font(.system(size: 15, weight: .medium, design: .monospaced))
                        .lineSpacing(4)
                        .foregroundStyle(p.text)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(14)
            .background(p.ground.opacity(0.8))
        }
        .overlay(RoundedRectangle(cornerRadius: 2).stroke(p.line, lineWidth: 1))
        .task {
            withAnimation(.easeInOut(duration: 0.85).repeatForever(autoreverses: true)) {
                pulse = true
            }
            withAnimation(.linear(duration: 1.5).repeatForever(autoreverses: true)) {
                scanProgress = 1
            }
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 2_800_000_000)
                if Task.isCancelled { break }
                guard autoPlaying else { continue }
                withAnimation(.easeInOut(duration: 0.25)) {
                    step = (step + 1) % steps.count
                }
            }
        }
    }


    private func miniDesktopFrame(_ p: Palette) -> some View {
        VStack(spacing: 0) {
            HStack(spacing: 5) {
                Circle().fill(p.danger.opacity(0.7)).frame(width: 5, height: 5)
                Circle().fill(p.warning.opacity(0.7)).frame(width: 5, height: 5)
                Circle().fill(p.success.opacity(0.7)).frame(width: 5, height: 5)
                Image("CarnivoreMark")
                    .resizable()
                    .scaledToFit()
                    .frame(width: 10, height: 10)
                    .padding(.leading, 4)
                Text(Strings.appGuideDesktopTitle.uppercased())
                    .font(.system(size: 8.5, weight: .semibold, design: .monospaced))
                    .foregroundStyle(p.textMuted)
                Spacer()
                ZStack {
                    if step == 0 {
                        RoundedRectangle(cornerRadius: 2)
                            .stroke(p.accent, lineWidth: 1.5)
                            .frame(width: 20, height: 16)
                            .scaleEffect(pulse ? 1.12 : 0.95)
                    }
                    Image(systemName: "gearshape.fill")
                        .font(.system(size: 9.5))
                        .foregroundStyle(step == 0 ? p.accent : p.textFaint)
                }
                .frame(width: 20, height: 16)
            }
            .padding(.horizontal, 8)
            .frame(height: 22)
            .background(p.ground)

            Rectangle().fill(p.line).frame(height: 1)

            HStack(spacing: 0) {
                miniSidebar(p)
                    .frame(width: 110)
                Rectangle().fill(p.line).frame(width: 1)
                miniDetailPane(p)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            .background(p.card)
        }
        .overlay(RoundedRectangle(cornerRadius: 2).stroke(p.line, lineWidth: 1))
    }

    private func miniSidebar(_ p: Palette) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            if step == 0 {
                sidebarItem("sessions", active: true, highlight: false, p: p)
                sidebarItem("  api-docs", active: false, highlight: false, p: p)
                sidebarItem("  frontend", active: false, highlight: false, p: p)
                Spacer()
                HStack(spacing: 4) {
                    Image(systemName: "gearshape.fill").font(.system(size: 8.5))
                    Text(Strings.appTabSettings)
                }
                .font(.system(size: 8.5, weight: .bold, design: .monospaced))
                .foregroundStyle(p.accent)
                .padding(.horizontal, 5).padding(.vertical, 3.5)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(p.accent.opacity(pulse ? 0.24 : 0.12))
                .overlay(RoundedRectangle(cornerRadius: 2).stroke(p.accent, lineWidth: 1))
            } else {
                sidebarItem("account", active: false, highlight: false, p: p)
                sidebarItem("general", active: false, highlight: false, p: p)
                sidebarItem("remote & security", active: true, highlight: step == 1, p: p)
                sidebarItem("notifications", active: false, highlight: false, p: p)
                Spacer()
            }
        }
        .padding(6)
        .background(p.ground.opacity(0.6))
    }

    private func sidebarItem(_ label: String, active: Bool, highlight: Bool, p: Palette) -> some View {
        Text(label)
            .font(.system(size: 8.5, weight: active ? .bold : .regular, design: .monospaced))
            .foregroundStyle(active ? (highlight ? p.accent : p.text) : p.textFaint)
            .lineLimit(1)
            .padding(.horizontal, 5)
            .padding(.vertical, 3)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(active ? (highlight ? p.accent.opacity(pulse ? 0.25 : 0.12) : p.page) : Palettes.clear)
            .overlay {
                if highlight {
                    RoundedRectangle(cornerRadius: 2).stroke(p.accent, lineWidth: 1)
                }
            }
    }

    @ViewBuilder
    private func miniDetailPane(_ p: Palette) -> some View {
        switch step {
        case 0:
            VStack(alignment: .leading, spacing: 6) {
                Text(Strings.appGuideTerminalPrompt)
                    .font(.system(size: 9.5, weight: .semibold, design: .monospaced))
                    .foregroundStyle(p.success)
                Text(Strings.appGuideGearHint)
                    .font(.system(size: 9, design: .monospaced))
                    .foregroundStyle(p.textMuted)
                Spacer()
            }
            .padding(8)
            .frame(maxWidth: .infinity, alignment: .leading)

        case 1, 2:
            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 4) {
                    miniTab("ACCESS", active: false, highlight: false, p: p)
                    miniTab("MOBILE SYNC", active: true, highlight: step == 1, p: p)
                    miniTab("API KEYS", active: false, highlight: false, p: p)
                }

                HStack(spacing: 6) {
                    ZStack {
                        RoundedRectangle(cornerRadius: 1)
                            .stroke(step >= 2 ? p.success : p.line, lineWidth: 1)
                            .frame(width: 10, height: 10)
                        if step >= 2 {
                            Rectangle()
                                .fill(p.success)
                                .frame(width: 5, height: 5)
                        }
                    }
                    Text(Strings.appGuideMobileSyncOn)
                        .font(.system(size: 8.5, weight: step >= 2 ? .semibold : .regular, design: .monospaced))
                        .foregroundStyle(step >= 2 ? p.text : p.textMuted)
                    Spacer()
                }
                .padding(.horizontal, 6).padding(.vertical, 4.5)
                .background(p.ground)
                .overlay(RoundedRectangle(cornerRadius: 2).stroke(step == 2 ? p.success.opacity(0.6) : p.line, lineWidth: 1))

                HStack(spacing: 4) {
                    Image(systemName: "qrcode").font(.system(size: 8.5))
                    Text(Strings.appGuidePairAMobileDevice)
                        .font(.system(size: 8.5, weight: .bold, design: .monospaced))
                }
                .foregroundStyle(step == 2 ? p.success : p.textMuted)
                .padding(.horizontal, 7).padding(.vertical, 5.5)
                .frame(maxWidth: .infinity)
                .background(step == 2 ? p.success.opacity(pulse ? 0.24 : 0.10) : p.ground)
                .overlay(
                    RoundedRectangle(cornerRadius: 2)
                        .stroke(step == 2 ? p.success : p.line, lineWidth: step == 2 ? 1.5 : 1)
                )
                Spacer(minLength: 0)
            }
            .padding(8)

        default:
            HStack(spacing: 10) {
                miniQRCode(p)
                    .frame(width: 66, height: 66)
                    .overlay {
                        GeometryReader { geo in
                            Rectangle()
                                .fill(p.accent)
                                .frame(height: 1.5)
                                .shadow(color: p.accent, radius: 3)
                                .offset(y: scanProgress * (geo.size.height - 2))
                        }
                    }

                VStack(alignment: .leading, spacing: 5) {
                    Text(Strings.appGuideScanQrCode.uppercased())
                        .font(.system(size: 8.5, weight: .bold, design: .monospaced))
                        .foregroundStyle(p.accent)
                    Text(Strings.appGuideOrCode.uppercased())
                        .font(.system(size: 8, design: .monospaced))
                        .foregroundStyle(p.textFaint)
                    Text(Strings.appGuideSampleCode.uppercased())
                        .font(.system(size: 10.5, weight: .bold, design: .monospaced))
                        .tracking(1.2)
                        .foregroundStyle(p.text)
                        .padding(.horizontal, 6).padding(.vertical, 3)
                        .background(p.ground)
                        .overlay(RoundedRectangle(cornerRadius: 2).stroke(p.success, lineWidth: 1))
                }
                Spacer(minLength: 0)
            }
            .padding(8)
        }
    }

    private func miniTab(_ label: String, active: Bool, highlight: Bool, p: Palette) -> some View {
        Text(label)
            .font(.system(size: 6.5, weight: active ? .bold : .regular, design: .monospaced))
            .foregroundStyle(active ? (highlight ? p.accent : p.text) : p.textFaint)
            .lineLimit(1)
            .padding(.horizontal, 4)
            .padding(.vertical, 2.5)
            .background(active ? (highlight ? p.accent.opacity(pulse ? 0.24 : 0.12) : p.ground) : Palettes.clear)
            .overlay(alignment: .top) {
                if active {
                    Rectangle().fill(p.accent).frame(height: 1.5)
                }
            }
            .overlay {
                if highlight {
                    RoundedRectangle(cornerRadius: 1).stroke(p.accent, lineWidth: 1)
                }
            }
    }

    private func miniQRCode(_ p: Palette) -> some View {
        let matrix: [[Int]] = [
            [1,1,1,0,1,0,1,1,1],
            [1,0,1,0,0,1,1,0,1],
            [1,1,1,0,1,0,1,1,1],
            [0,0,0,1,0,1,0,0,0],
            [1,0,1,1,1,0,1,0,1],
            [0,1,0,0,1,1,0,1,0],
            [1,1,1,0,1,0,1,0,1],
            [1,0,1,0,0,1,0,1,0],
            [1,1,1,0,1,1,1,0,1],
        ]
        return VStack(spacing: 1) {
            ForEach(0..<matrix.count, id: \.self) { r in
                HStack(spacing: 1) {
                    ForEach(0..<matrix[r].count, id: \.self) { c in
                        Rectangle()
                            .fill(matrix[r][c] == 1 ? p.text : p.page)
                    }
                }
            }
        }
        .padding(4)
        .background(p.page)
        .overlay(RoundedRectangle(cornerRadius: 2).stroke(p.line, lineWidth: 1))
    }
}
