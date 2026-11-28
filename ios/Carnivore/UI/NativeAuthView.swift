import SwiftUI
import WebKit

struct NativeAuthView: View {
    @ObservedObject var computerStore: ComputerStore
    @ObservedObject var sessionStore: AppSessionStore
    var isModal: Bool = false
    var onDismiss: (() -> Void)? = nil

    @EnvironmentObject private var theme: ThemeStore

    private enum AuthPhase: Equatable {
        case noComputer
        case checking
        case pairRequired
        case totpDirect
        case totpPairVerify
    }

    @State private var phase: AuthPhase = .checking
    @State private var showScanner = false
    @State private var showAddManual = false
    @State private var showCodeEntry = false
    @State private var pairCode = ""
    @State private var totpCode = ""
    @State private var busy = false
    @State private var errorMessage: String?
    @FocusState private var otpFocused: Bool

    private var activeComputer: Computer? { computerStore.activeComputer }

    private var isPairingPhase: Bool {
        phase == .noComputer || phase == .pairRequired
    }

    private var headerLabel: String {
        switch phase {
        case .noComputer: return "CONNECT"
        case .checking: return "CHECKING"
        case .pairRequired: return "PAIR DEVICE"
        case .totpPairVerify: return "VERIFY PAIRING"
        case .totpDirect: return "AUTHENTICATE"
        }
    }

    var body: some View {
        let p = theme.palette
        VStack(spacing: 0) {
            if isModal || computerStore.computers.count > 1 {
                HStack {
                    if computerStore.computers.count > 1 {
                        Menu {
                            ForEach(computerStore.computers) { comp in
                                Button {
                                    Haptics.selection()
                                    computerStore.activeComputerId = comp.id
                                } label: {
                                    Label(comp.displayName, systemImage: comp.id == activeComputer?.id ? "checkmark" : "desktopcomputer")
                                }
                            }
                        } label: {
                            HStack(spacing: 6) {
                                Text(Strings.appComputerLabel.uppercased())
                                    .foregroundStyle(p.textFaint)
                                Text(activeComputer?.displayName ?? "NONE")
                                    .foregroundStyle(p.text)
                                Image(systemName: "chevron.down")
                                    .font(.system(size: 9, weight: .bold))
                                    .foregroundStyle(p.textMuted)
                            }
                            .font(.system(size: 11, design: .monospaced))
                        }
                    }
                    Spacer()
                    if isModal, let onDismiss {
                        Button(Strings.appClose.uppercased()) { onDismiss() }
                            .font(.system(size: 11, weight: .semibold, design: .monospaced))
                            .tracking(1.2)
                            .foregroundStyle(p.textMuted)
                    }
                }
                .padding(.horizontal, 16)
                .frame(height: 40)
                .background(p.ground)
                hairline(p)
            }

            if isPairingPhase {
                pairingLayout(p)
            } else {
                centeredAuthLayout(p)
            }
        }
        .background(p.page.ignoresSafeArea())
        .task(id: activeComputer?.id) {
            await probeActiveComputer()
        }
        .sheet(isPresented: $showScanner) {
            NativeQRPairSheet(store: computerStore) { computer, secret in
                showScanner = false
                Task { await claimScannedQR(computer: computer, secret: secret) }
            }
        }
        .sheet(isPresented: $showAddManual) {
            AddComputerView(store: computerStore)
        }
    }


    private func pairingLayout(_ p: Palette) -> some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(spacing: 0) {
                    VStack(spacing: 0) {
                        authPanelHeader(p)
                        activeComputerStrip(p)
                        PairingGuideView()
                            .padding(14)
                    }
                    .frame(maxWidth: 420)
                    .background(p.card)
                    .overlay(RoundedRectangle(cornerRadius: 2).stroke(p.line, lineWidth: 1))
                    .padding(.horizontal, 16)
                    .padding(.top, 16)
                    .padding(.bottom, 16)
                }
                .frame(maxWidth: .infinity)
            }
            .scrollBounceBehavior(.basedOnSize)

            Spacer(minLength: 20)

            VStack(spacing: 0) {
                hairline(p)

                VStack(alignment: .leading, spacing: 12) {
                    if let errorMessage {
                        Text(errorMessage)
                            .font(.system(size: 13, design: .monospaced))
                            .foregroundStyle(p.danger)
                            .fixedSize(horizontal: false, vertical: true)
                            .padding(10)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .overlay(RoundedRectangle(cornerRadius: 2).stroke(p.danger, lineWidth: 1))
                    }

                    if phase == .noComputer {
                        confirmButton("Scan Pairing QR Code", systemImage: "qrcode.viewfinder", palette: p, disabled: busy) {
                            Haptics.action()
                            errorMessage = nil
                            showScanner = true
                        }
                        secondaryButton("Add Computer Manually (LAN / HTTPS)", palette: p) {
                            Haptics.tap()
                            showAddManual = true
                        }
                    } else if !showCodeEntry {
                        confirmButton("Scan Pairing QR Code", systemImage: "qrcode.viewfinder", palette: p, disabled: busy) {
                            Haptics.action()
                            errorMessage = nil
                            showScanner = true
                        }
                        secondaryButton("Enter 8-Character Code Instead", palette: p) {
                            Haptics.tap()
                            showCodeEntry = true
                        }
                        HStack {
                            Spacer()
                            Button(Strings.appAddAnotherComputer) {
                                errorMessage = nil
                                showAddManual = true
                            }
                            .font(.system(size: 12, design: .monospaced))
                            .foregroundStyle(p.textMuted)
                            Spacer()
                        }
                        .padding(.top, 2)
                    } else {
                        HStack {
                            Text(Strings.appPairingCodeLongLabel.uppercased())
                                .font(.system(size: 11, weight: .semibold, design: .monospaced))
                                .tracking(0.8)
                                .foregroundStyle(p.textMuted)
                            Spacer()
                            Button(Strings.appUseQrScanner) {
                                Haptics.tap()
                                showCodeEntry = false
                            }
                            .font(.system(size: 11, weight: .semibold, design: .monospaced))
                            .foregroundStyle(p.accent)
                        }

                        TextField(Strings.appPairingCodePlaceholder.uppercased(), text: $pairCode)
                            .font(.system(size: 22, weight: .semibold, design: .monospaced))
                            .tracking(4)
                            .multilineTextAlignment(.center)
                            .textInputAutocapitalization(.characters)
                            .autocorrectionDisabled()
                            .foregroundStyle(p.text)
                            .padding(.vertical, 12)
                            .padding(.horizontal, 10)
                            .background(p.page)
                            .overlay(RoundedRectangle(cornerRadius: 2).stroke(p.line, lineWidth: 1))

                        confirmButton(busy ? "Claiming…" : "Claim Pairing Code", palette: p, disabled: busy || pairCode.trimmingCharacters(in: .whitespaces).count < 6) {
                            if let comp = activeComputer {
                                Task { await claimManualCode(comp) }
                            }
                        }
                    }
                }
                .frame(maxWidth: 420)
                .padding(.horizontal, 16)
                .padding(.top, 16)
                .padding(.bottom, 18)
                .frame(maxWidth: .infinity)
                .background(p.ground)
            }
        }
    }


    private func centeredAuthLayout(_ p: Palette) -> some View {
        ScrollView {
            VStack(spacing: 0) {
                Spacer(minLength: 28)

                VStack(spacing: 0) {
                    authPanelHeader(p)
                    activeComputerStrip(p)

                    VStack(alignment: .leading, spacing: 14) {
                        switch phase {
                        case .checking:
                            checkingBody(p)
                        case .totpDirect, .totpPairVerify:
                            totpBody(p)
                        case .noComputer, .pairRequired:
                            EmptyView()
                        }

                        if let errorMessage {
                            Text(errorMessage)
                                .font(.system(size: 13, design: .monospaced))
                                .foregroundStyle(p.danger)
                                .fixedSize(horizontal: false, vertical: true)
                                .padding(10)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .overlay(RoundedRectangle(cornerRadius: 2).stroke(p.danger, lineWidth: 1))
                        }
                    }
                    .padding(16)
                }
                .frame(maxWidth: 380)
                .background(p.card)
                .overlay(RoundedRectangle(cornerRadius: 2).stroke(p.line, lineWidth: 1))
                .padding(.horizontal, 20)

                if activeComputer != nil {
                    HStack(spacing: 16) {
                        Button(Strings.appPairQr) {
                            errorMessage = nil
                            showScanner = true
                        }
                        Text(Strings.appSeparatorDot).foregroundStyle(p.line)
                        Button(Strings.appAddComputer) {
                            errorMessage = nil
                            showAddManual = true
                        }
                    }
                    .font(.system(size: 12, design: .monospaced))
                    .foregroundStyle(p.textMuted)
                    .padding(.top, 18)
                }

                Spacer(minLength: 24)
            }
            .frame(maxWidth: .infinity)
        }
    }


    private func authPanelHeader(_ p: Palette) -> some View {
        VStack(spacing: 0) {
            HStack(spacing: 12) {
                Image("CarnivoreWordmark")
                    .resizable()
                    .interpolation(.high)
                    .scaledToFit()
                    .frame(height: 20)
                Spacer()
                Text(headerLabel)
                    .font(.system(size: 11, weight: .semibold, design: .monospaced))
                    .tracking(1.2)
                    .foregroundStyle(p.accent)
            }
            .padding(.horizontal, 14)
            .frame(minHeight: 42)
            .background(p.ground)

            hairline(p)
        }
    }

    @ViewBuilder
    private func activeComputerStrip(_ p: Palette) -> some View {
        if let comp = activeComputer {
            HStack(spacing: 8) {
                Image("CarnivoreMark")
                    .resizable()
                    .interpolation(.high)
                    .scaledToFit()
                    .frame(width: 14, height: 14)
                Text(comp.displayName)
                    .font(.system(size: 13, weight: .semibold, design: .monospaced))
                    .foregroundStyle(p.text)
                    .lineLimit(1)
                Spacer()
                Text(comp.shortAddress)
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(comp.isUnencrypted ? p.warning : p.textFaint)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 9)
            .background(p.page.opacity(0.6))
            hairline(p)
        }
    }

    @ViewBuilder
    private func checkingBody(_ p: Palette) -> some View {
        HStack(spacing: 10) {
            ProgressView().tint(p.accent)
            Text(Strings.appCheckingPairing)
                .font(.system(size: 13, design: .monospaced))
                .foregroundStyle(p.textMuted)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.vertical, 8)
    }

    @ViewBuilder
    private func totpBody(_ p: Palette) -> some View {
        Text(phase == .totpPairVerify
             ? "Pairing claimed. Enter the 6-digit authenticator code to finish pairing and sign in."
             : "Enter the 6-digit code from your authenticator app.")
            .font(.system(size: 13, design: .monospaced))
            .foregroundStyle(p.textMuted)
            .fixedSize(horizontal: false, vertical: true)

        VStack(alignment: .leading, spacing: 6) {
            Text(Strings.appAuthenticatorCodeLabel.uppercased())
                .font(.system(size: 11, design: .monospaced))
                .tracking(0.8)
                .foregroundStyle(p.textMuted)

            TextField(Strings.appAuthenticatorCodePlaceholder, text: $totpCode)
                .focused($otpFocused)
                .font(.system(size: 24, weight: .semibold, design: .monospaced))
                .tracking(6)
                .multilineTextAlignment(.center)
                .keyboardType(.numberPad)
                .textContentType(.oneTimeCode)
                .foregroundStyle(p.text)
                .padding(.vertical, 12)
                .padding(.horizontal, 10)
                .background(p.ground)
                .overlay(RoundedRectangle(cornerRadius: 2).stroke(otpFocused ? p.accent : p.line, lineWidth: 1))
                .onChange(of: totpCode) { _, newValue in
                    let digits = String(newValue.filter(\.isNumber).prefix(6))
                    if digits != newValue { totpCode = digits }
                    if digits.count == 6 && !busy, let comp = activeComputer {
                        Task { await submitTOTP(comp, code: digits) }
                    }
                }
        }

        confirmButton(busy ? "Verifying…" : (phase == .totpPairVerify ? "Verify & Pair" : "Sign In"),
                      palette: p,
                      disabled: busy || totpCode.count != 6) {
            if let comp = activeComputer {
                Task { await submitTOTP(comp, code: totpCode) }
            }
        }

        if activeComputer?.kind == .relay && phase == .totpDirect {
            secondaryButton("Re-Pair This Phone", palette: p) {
                errorMessage = nil
                phase = .pairRequired
            }
        }
    }


    private func hairline(_ p: Palette) -> some View {
        Rectangle().fill(p.line).frame(height: 1)
    }

    private func confirmButton(_ title: String, systemImage: String? = nil, palette p: Palette, disabled: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 8) {
                if busy {
                    ProgressView().tint(p.success).scaleEffect(0.85)
                } else if let systemImage {
                    Image(systemName: systemImage)
                        .font(.system(size: 16, weight: .semibold))
                }
                Text(title)
                    .font(.system(size: 15, weight: .bold, design: .monospaced))
            }
            .foregroundStyle(p.success)
            .frame(maxWidth: .infinity)
            .frame(minHeight: 50)
            .background(p.success.opacity(0.14))
            .overlay(RoundedRectangle(cornerRadius: 2).stroke(p.success, lineWidth: 1.5))
        }
        .buttonStyle(.plain)
        .disabled(disabled)
        .opacity(disabled ? 0.45 : 1.0)
    }

    private func secondaryButton(_ title: String, palette p: Palette, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: 13, weight: .medium, design: .monospaced))
                .foregroundStyle(p.textMuted)
                .frame(maxWidth: .infinity)
                .frame(minHeight: 44)
                .background(p.card)
                .overlay(RoundedRectangle(cornerRadius: 2).stroke(p.line, lineWidth: 1))
        }
        .buttonStyle(.plain)
    }


    private func probeActiveComputer() async {
        guard !busy else { return }
        errorMessage = nil
        totpCode = ""
        guard let comp = activeComputer else {
            phase = .noComputer
            return
        }
        if comp.kind != .relay {
            phase = .totpDirect
            otpFocused = true
            return
        }
        phase = .checking
        let api = sessionStore.api ?? CarnivoreAPI(computer: comp)

        if await !api.hasLinkCookie() {
            if let migrated = await findLegacyLinkCookie(forHost: comp.origin.host, computerId: comp.id) {
                await api.adoptLinkCookie(migrated)
            }
        }

        let status = await api.checkPairStatus()
        if status.paired {
            phase = .totpDirect
            otpFocused = true
        } else if status.pending {
            phase = .totpPairVerify
            otpFocused = true
        } else {
            phase = .pairRequired
        }
    }

    private func findLegacyLinkCookie(forHost host: String, computerId: UUID) async -> String? {
        let lowerHost = host.lowercased()
        let stores = [WKWebsiteDataStore.default(), WKWebsiteDataStore(forIdentifier: computerId)]
        for store in stores {
            let cookies = await store.httpCookieStore.allCookies()
            if let hit = cookies.first(where: {
                $0.name == "__Host-cc_link" && $0.domain.trimmingCharacters(in: CharacterSet(charactersIn: ".")).lowercased() == lowerHost
            }) {
                return "\(hit.name)=\(hit.value)"
            }
        }
        return nil
    }

    private func claimScannedQR(computer: Computer, secret: String?) async {
        guard !busy else { return }
        busy = true
        errorMessage = nil
        defer { busy = false }
        computerStore.activeComputerId = computer.id
        sessionStore.select(computer: computer)
        guard let secret, !secret.isEmpty else {
            busy = false
            await probeActiveComputer()
            return
        }
        let api = sessionStore.api ?? CarnivoreAPI(computer: computer)
        do {
            let outcome = try await api.pairClaim(secret: secret, deviceLabel: UIDevice.current.name)
            Haptics.success()
            totpCode = ""
            phase = outcome == .alreadyPaired ? .totpDirect : .totpPairVerify
            otpFocused = true
        } catch {
            Haptics.error()
            errorMessage = error.localizedDescription
            phase = .pairRequired
        }
    }

    private func claimManualCode(_ comp: Computer) async {
        let cleaned = pairCode.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        guard !cleaned.isEmpty else { return }
        busy = true
        errorMessage = nil
        defer { busy = false }
        let api = sessionStore.api ?? CarnivoreAPI(computer: comp)
        do {
            let outcome = try await api.pairCode(code: cleaned, deviceLabel: UIDevice.current.name)
            Haptics.success()
            pairCode = ""
            totpCode = ""
            phase = outcome == .alreadyPaired ? .totpDirect : .totpPairVerify
            otpFocused = true
        } catch {
            Haptics.error()
            errorMessage = error.localizedDescription
        }
    }

    private func submitTOTP(_ comp: Computer, code: String) async {
        let clean = String(code.filter(\.isNumber).prefix(6))
        guard clean.count == 6 else { return }
        busy = true
        errorMessage = nil
        defer { busy = false }
        let api = sessionStore.api ?? CarnivoreAPI(computer: comp)
        do {
            if phase == .totpPairVerify {
                _ = try await api.pairVerify(totpCode: clean)
            } else {
                _ = try await api.verifyTOTP(code: clean)
            }
            Haptics.success()
            totpCode = ""
            await sessionStore.didAuthenticate()
            onDismiss?()
        } catch APIError.linkPairingRequired {
            Haptics.warning()
            totpCode = ""
            phase = .pairRequired
            errorMessage = "This iPhone needs to pair with \(comp.name) first."
        } catch {
            Haptics.error()
            totpCode = ""
            errorMessage = error.localizedDescription
            if error.localizedDescription.contains("expired") || error.localizedDescription.contains("open a new pairing window") {
                phase = .pairRequired
            }
        }
    }
}

struct NativeQRPairSheet: View {
    @ObservedObject var store: ComputerStore
    let onPaired: (Computer, String?) -> Void

    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var theme: ThemeStore
    @State private var scanError: String?
    @State private var pending: PairTarget?
    @State private var pendingCode: String?
    @State private var declined: String?
    @State private var didAccept = false

    var body: some View {
        let p = theme.palette
        NavigationStack {
            VStack(spacing: 0) {
                ScannerView(onEvent: handle)
                    .overlay(alignment: .bottom) {
                        Text(Strings.scanHint)
                            .font(.system(size: 12, design: .monospaced))
                            .padding(10)
                            .background(p.page.opacity(0.88))
                            .foregroundStyle(p.text)
                            .overlay(RoundedRectangle(cornerRadius: 2).stroke(p.line, lineWidth: 1))
                            .padding()
                    }
                if let scanError {
                    Text(scanError)
                        .font(.system(size: 12, design: .monospaced))
                        .foregroundStyle(p.danger)
                        .padding(12)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(p.ground)
                }
            }
            .background(p.page.ignoresSafeArea())
            .navigationTitle(Strings.scanTitle)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(Strings.actionCancel) { dismiss() }
                }
            }
            .alert(Strings.scanConfirmTitle, isPresented: Binding(
                get: { pending != nil },
                set: { if !$0 { declined = pendingCode; pending = nil; pendingCode = nil } }
            ), presenting: pending) { target in
                Button(Strings.scanConfirmAdd) { accept(target) }
                Button(Strings.actionCancel, role: .cancel) {}
            } message: { target in
                Text(Strings.scanConfirmBody + "\n\n" + target.origin.host)
            }
        }
    }

    private func handle(_ event: ScanEvent) {
        switch event {
        case .cameraDenied: scanError = Strings.scanCameraDenied
        case .cameraUnavailable: scanError = Strings.scanCameraUnavailable
        case .code(let text):
            guard !didAccept, pending == nil, text != declined else { return }
            declined = nil
            switch PairURL.parse(text, known: store.computers.map(\.origin)) {
            case .failure(let err):
                switch err {
                case .notAPairingCode: scanError = Strings.scanRefusedNotPair
                case .unknownHost: scanError = Strings.scanRefusedHost
                case .badSecret: scanError = Strings.scanRefusedSecret
                }
            case .success(let target):
                scanError = nil
                if target.needsConfirm {
                    pendingCode = text
                    pending = target
                } else {
                    accept(target)
                }
            }
        }
    }

    private func accept(_ target: PairTarget) {
        guard !didAccept else { return }
        didAccept = true
        let computer = store.computers.first(where: { $0.origin == target.origin })
            ?? store.add(Computer(name: target.origin.host, kind: target.kind, origin: target.origin))
        Haptics.success()
        onPaired(computer, target.secret)
    }
}
