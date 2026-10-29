import SwiftUI

struct PairScreen: View {
    let finish: (Computer, URL) -> Void
    @ObservedObject var store: ComputerStore
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var theme: ThemeStore
    @State private var message: String?
    @State private var typing = false
    @State private var address = ""
    @State private var pending: PairTarget?
    @State private var queued: PairTarget?
    @State private var pendingCode: String?
    @State private var declined: String?

    var body: some View {
        NavigationStack {
            VStack(spacing: 12) {
                ScannerView(onEvent: handle)
                    .overlay(alignment: .bottom) { hint }
                if let message {
                    Text(message).font(.system(.footnote, design: .monospaced)).foregroundStyle(theme.palette.danger)
                        .padding(.horizontal)
                }
                Button(Strings.scanTypeInstead) { typing = true }.padding(.bottom)
            }
            .navigationTitle(Strings.scanTitle)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button(Strings.actionCancel) { dismiss() } } }
            .sheet(isPresented: $typing, onDismiss: { if let q = queued { pending = q }; queued = nil }) { manualEntry }
            .alert(Strings.scanConfirmTitle, isPresented: confirming, presenting: pending) { target in
                Button(Strings.scanConfirmAdd) { open(target) }
                Button(Strings.actionCancel, role: .cancel) {}
            } message: { target in
                Text(Strings.scanConfirmBody + "\n\n" + target.origin.host)
            }
        }
    }

    private var confirming: Binding<Bool> {
        Binding(get: { pending != nil }, set: { if !$0 { declined = pendingCode; pending = nil; pendingCode = nil } })
    }

    private var hint: some View {
        Text(Strings.scanHint).font(.system(.footnote, design: .monospaced))
            .padding(8).background(theme.palette.page.opacity(0.8)).foregroundStyle(theme.palette.text).padding()
    }

    private var manualEntry: some View {
        NavigationStack {
            Form {
                Text(Strings.scanManualHint).font(.footnote)
                TextField(Strings.addPlaceholderRelay, text: $address)
                    .textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
                if let message { Text(message).foregroundStyle(theme.palette.danger).font(.footnote) }
                Button(Strings.scanManualOpen, action: openManual)
            }
            .navigationTitle(Strings.scanManualTitle)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button(Strings.actionCancel) { typing = false } } }
        }
    }

    private func handle(_ event: ScanEvent) {
        switch event {
        case .cameraDenied: message = Strings.scanCameraDenied
        case .cameraUnavailable: message = Strings.scanCameraUnavailable
        case .code(let text):
            guard pending == nil, !typing else { return }
            if text == declined { return }
            declined = nil
            decide(PairURL.parse(text, known: store.computers.map(\.origin)), code: text)
        }
    }

    private func decide(_ result: Result<PairTarget, PairError>, code: String?) {
        switch result {
        case .failure(let error): message = code == nil && error == .unknownHost ? Strings.scanRefusedTyped : Self.text(for: error)
        case .success(let target):
            message = nil
            if !target.needsConfirm { open(target) } else if typing { queued = target; typing = false } else {
                pendingCode = code
                pending = target
            }
        }
    }

    private func openManual() {
        let parsed = [ComputerKind.relay, .https].lazy.compactMap { kind -> Origin? in
            if case .success(let origin) = AddressParser.parse(address, kind: kind) { return origin }
            return nil
        }.first
        guard let origin = parsed else {
            message = AddressError.badHost.message
            return
        }
        decide(PairURL.manual(origin, known: store.computers.map(\.origin)), code: nil)
    }

    private func open(_ target: PairTarget) { open(target.origin, kind: target.kind, url: target.url) }

    private func open(_ origin: Origin, kind: ComputerKind, url: URL) {
        let computer = store.computers.first { $0.origin == origin }
            ?? Computer(name: origin.host, kind: kind, origin: origin)
        if !store.computers.contains(where: { $0.origin == origin }) { store.add(computer) }
        typing = false
        finish(computer, url)
    }

    private static func text(for error: PairError) -> String {
        switch error {
        case .notAPairingCode: return Strings.scanRefusedNotPair
        case .unknownHost: return Strings.scanRefusedHost
        case .badSecret: return Strings.scanRefusedSecret
        }
    }
}
