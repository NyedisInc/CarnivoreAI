import SwiftUI

struct RootShellView: View {
    @ObservedObject var computerStore: ComputerStore
    @ObservedObject var sessionStore: AppSessionStore
    @ObservedObject var lockManager: AppLockManager
    @EnvironmentObject private var theme: ThemeStore

    @State private var showPairModal = false
    @State private var showSecuritySheet = false
    @State private var reloadToken = 0

    var body: some View {
        Group {
            if let comp = computerStore.activeComputer, sessionStore.isAuthenticated {
                authenticatedWebShell(comp)
            } else {
                NativeAuthView(computerStore: computerStore, sessionStore: sessionStore)
            }
        }
        .onAppear {
            sessionStore.onDiscoveredComputerName = { id, discovered in
                computerStore.rename(id: id, to: discovered)
            }
            sessionStore.select(computer: computerStore.activeComputer)
        }
        .onChange(of: computerStore.activeComputerId) { _, _ in
            sessionStore.select(computer: computerStore.activeComputer)
        }
        .onReceive(TapRouter.shared.$pending) { tap in
            guard let tap else { return }
            guard let computer = computerStore.computer(forOrigin: tap.origin) else {
                TapRouter.shared.clear()
                return
            }
            if computerStore.activeComputer?.id != computer.id {
                computerStore.activeComputerId = computer.id
            }
        }
        .sheet(isPresented: $showPairModal) {
            NativeAuthView(computerStore: computerStore, sessionStore: sessionStore, isModal: true) {
                showPairModal = false
            }
        }
        .sheet(isPresented: $showSecuritySheet) {
            SecuritySettingsSheet(
                computerStore: computerStore,
                sessionStore: sessionStore,
                lockManager: lockManager,
                onPairAnother: {
                    showSecuritySheet = false
                    showPairModal = true
                }
            )
        }
    }

    private func authenticatedWebShell(_ comp: Computer) -> some View {
        let p = theme.palette
        return VStack(spacing: 0) {
            HStack(spacing: 10) {
                Menu {
                    if computerStore.computers.count > 1 {
                        Section("Switch Computer") {
                            ForEach(computerStore.computers) { item in
                                Button {
                                    Haptics.selection()
                                    computerStore.activeComputerId = item.id
                                } label: {
                                    Label(item.displayName, systemImage: item.id == comp.id ? "checkmark" : "desktopcomputer")
                                }
                            }
                        }
                    }
                    Section {
                        Button {
                            showPairModal = true
                        } label: {
                            Label(Strings.appPairOrAddComputer, systemImage: "qrcode.viewfinder")
                        }
                        Button {
                            showSecuritySheet = true
                        } label: {
                            Label(Strings.appSecurityComputers, systemImage: lockManager.biometricIcon)
                        }
                    }
                    Section {
                        Button(role: .destructive) {
                            Task { await sessionStore.signOut() }
                        } label: {
                            Label(Strings.appSignOut, systemImage: "rectangle.portrait.and.arrow.right")
                        }
                    }
                } label: {
                    HStack(spacing: 6) {
                        Image("CarnivoreMark")
                            .resizable()
                            .interpolation(.high)
                            .scaledToFit()
                            .frame(width: 14, height: 14)
                        Text(comp.displayName)
                            .font(.system(size: 12, weight: .semibold, design: .monospaced))
                            .foregroundStyle(p.text)
                            .lineLimit(1)
                        Image(systemName: "chevron.down")
                            .font(.system(size: 9, weight: .bold))
                            .foregroundStyle(p.textMuted)
                    }
                    .padding(.vertical, 4)
                    .contentShape(Rectangle())
                }

                Spacer()

                Button {
                    Haptics.tap()
                    reloadToken += 1
                } label: {
                    Image(systemName: "arrow.clockwise")
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(p.textMuted)
                        .frame(width: 28, height: 28)
                }
                .accessibilityLabel("Reload")

                Button {
                    Haptics.tap()
                    showSecuritySheet = true
                } label: {
                    Image(systemName: lockManager.isEnabled ? lockManager.biometricIcon : "lock.open")
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(lockManager.isEnabled ? p.accent : p.textMuted)
                        .frame(width: 28, height: 28)
                }
                .accessibilityLabel("Security & Lock")
            }
            .padding(.horizontal, 12)
            .frame(height: 32)
            .background(p.ground)

            Rectangle().fill(p.line).frame(height: 1)

            WebScreen(
                computer: comp,
                sessionStore: sessionStore,
                externalReloadToken: reloadToken,
                close: {
                    Task { await sessionStore.signOut() }
                }
            )
            .id(comp.id)
        }
        .background(p.page.ignoresSafeArea())
    }
}

private struct SecuritySettingsSheet: View {
    @ObservedObject var computerStore: ComputerStore
    @ObservedObject var sessionStore: AppSessionStore
    @ObservedObject var lockManager: AppLockManager
    let onPairAnother: () -> Void

    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var theme: ThemeStore
    @State private var renamingComputer: Computer?
    @State private var renameText = ""

    var body: some View {
        let p = theme.palette
        NavigationStack {
            List {
                Section("App Lock & Privacy") {
                    Toggle(isOn: $lockManager.isEnabled) {
                        Label(Strings.fill(Strings.appRequireLockWith, ["label": lockManager.biometricLabel]), systemImage: lockManager.biometricIcon)
                            .font(.system(size: 14, design: .monospaced))
                    }
                    .tint(p.accent)

                    if lockManager.isEnabled {
                        Picker(Strings.appAutoLock, selection: $lockManager.timeout) {
                            ForEach(AppLockTimeout.allCases) { option in
                                Text(option.label)
                                    .font(.system(size: 14, design: .monospaced))
                                    .tag(option)
                            }
                        }
                        .font(.system(size: 14, design: .monospaced))

                        Button {
                            dismiss()
                            lockManager.lockNow()
                        } label: {
                            Label(Strings.appLockNow, systemImage: "lock.fill")
                                .font(.system(size: 14, weight: .semibold, design: .monospaced))
                                .foregroundStyle(p.accent)
                        }
                    }
                }

                Section("Computers") {
                    ForEach(computerStore.computers) { comp in
                        HStack {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(comp.displayName)
                                    .font(.system(size: 14, weight: .semibold, design: .monospaced))
                                Text(comp.shortAddress)
                                    .font(.system(size: 11, design: .monospaced))
                                    .foregroundStyle(p.textMuted)
                            }
                            Spacer()
                            if comp.id == computerStore.activeComputer?.id {
                                Image(systemName: "checkmark")
                                    .foregroundStyle(p.success)
                            }
                        }
                        .contentShape(Rectangle())
                        .onTapGesture {
                            computerStore.activeComputerId = comp.id
                            dismiss()
                        }
                        .swipeActions(edge: .leading, allowsFullSwipe: false) {
                            Button(Strings.appRename) {
                                renameText = comp.displayName
                                renamingComputer = comp
                            }
                            .tint(p.accent)
                        }
                    }
                    .onDelete { offsets in
                        computerStore.remove(at: offsets)
                    }

                    Button {
                        onPairAnother()
                    } label: {
                        Label(Strings.appPairOrAddComputer, systemImage: "qrcode.viewfinder")
                            .font(.system(size: 14, design: .monospaced))
                    }
                }

                Section {
                    Button(role: .destructive) {
                        dismiss()
                        Task { await sessionStore.signOut() }
                    } label: {
                        Label(Strings.fill(Strings.appSignOutOf, ["name": computerStore.activeComputer?.displayName ?? Strings.appComputer]), systemImage: "rectangle.portrait.and.arrow.right")
                            .font(.system(size: 14, weight: .semibold, design: .monospaced))
                    }
                }
            }
            .navigationTitle("Security")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button(Strings.appDone) { dismiss() }
                        .font(.system(size: 14, weight: .semibold, design: .monospaced))
                }
            }
            .alert("Rename Computer", isPresented: Binding(
                get: { renamingComputer != nil },
                set: { if !$0 { renamingComputer = nil } }
            )) {
                TextField(Strings.appComputerName, text: $renameText)
                Button(Strings.appSave) {
                    if let target = renamingComputer {
                        computerStore.rename(id: target.id, to: renameText)
                    }
                    renamingComputer = nil
                }
                Button(Strings.appCancel, role: .cancel) { renamingComputer = nil }
            }
        }
    }
}
