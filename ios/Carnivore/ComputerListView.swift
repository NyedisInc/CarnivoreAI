import SwiftUI

struct ComputerListView: View {
    @ObservedObject var store: ComputerStore
    @State private var adding = false
    @State private var opened: OpenTarget?
    @State private var scanning = false
    @EnvironmentObject private var theme: ThemeStore

    var body: some View {
        NavigationStack {
            List {
                ForEach(store.computers) { computer in
                    Button { opened = OpenTarget(computer: computer, startURL: nil) } label: {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(computer.name).font(.system(.body, design: .monospaced))
                            HStack(spacing: 8) {
                                Text(computer.origin.rootURL.absoluteString)
                                if computer.isUnencrypted {
                                    Text(Strings.tagUnencrypted).foregroundStyle(theme.palette.warning)
                                }
                            }
                            .font(.system(.caption, design: .monospaced))
                            .foregroundStyle(theme.palette.textMuted)
                        }
                    }
                }
                .onDelete { store.remove(at: $0) }
            }
            .overlay {
                if store.computers.isEmpty {
                    Text(Strings.listEmpty)
                        .font(.system(.footnote, design: .monospaced))
                        .foregroundStyle(theme.palette.textMuted)
                }
            }
            .navigationTitle(Strings.actionComputers)
            .toolbar {
                Button(Strings.actionScan) { scanning = true }
                Button(Strings.actionAdd) { adding = true }
            }
            .sheet(isPresented: $scanning) {
                PairScreen(finish: { computer, url in
                    scanning = false
                    opened = OpenTarget(computer: computer, startURL: url)
                }, store: store)
            }
            .sheet(isPresented: $adding) { AddComputerView(store: store) }
            .onReceive(TapRouter.shared.$pending) { tap in
                guard let tap else { return }
                guard let computer = store.computer(forOrigin: tap.origin) else { return TapRouter.shared.clear() }
                if opened?.computer.id != computer.id { opened = OpenTarget(computer: computer, startURL: nil) }
            }
            .fullScreenCover(item: $opened) { target in
                WebScreen(computer: target.computer, startURL: target.startURL) { opened = nil }
            }
        }
    }
}

struct OpenTarget: Identifiable {
    let id = UUID()
    let computer: Computer
    let startURL: URL?
}

struct AddComputerView: View {
    @ObservedObject var store: ComputerStore
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var address = ""
    @State private var kind = ComputerKind.relay
    @State private var error: String?
    @EnvironmentObject private var theme: ThemeStore

    var body: some View {
        NavigationStack {
            Form {
                Picker(Strings.addKind, selection: $kind) {
                    ForEach(ComputerKind.allCases, id: \.self) { Text($0.label).tag($0) }
                }
                .pickerStyle(.segmented)
                TextField(Strings.addName, text: $name)
                TextField(placeholder, text: $address)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .keyboardType(.URL)
                if kind == .lan {
                    Text(Strings.addLanWarning).font(.footnote)
                        .foregroundStyle(theme.palette.warning)
                }
                if let error { Text(error).foregroundStyle(theme.palette.danger).font(.footnote) }
            }
            .navigationTitle(Strings.addTitle)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button(Strings.actionCancel) { dismiss() } }
                ToolbarItem(placement: .confirmationAction) { Button(Strings.actionSave, action: save) }
            }
        }
    }

    private var placeholder: String {
        switch kind {
        case .relay: return Strings.addPlaceholderRelay
        case .lan: return Strings.addPlaceholderLan
        case .https: return Strings.addPlaceholderHttps
        }
    }

    private func save() {
        switch AddressParser.parse(address, kind: kind) {
        case .failure(let e): error = e.message
        case .success(let origin):
            let label = name.trimmingCharacters(in: .whitespaces)
            store.add(Computer(name: label.isEmpty ? origin.host : label, kind: kind, origin: origin))
            dismiss()
        }
    }
}
