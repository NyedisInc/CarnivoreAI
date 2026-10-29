import SwiftUI

struct UnreachableView: View {
    let computer: Computer
    let reason: UnreachableReason
    let retry: () -> Void
    let close: () -> Void
    @EnvironmentObject private var theme: ThemeStore

    var body: some View {
        let p = theme.palette
        VStack(spacing: 0) {
            HStack {
                Text(Strings.unreachableLabel.uppercased())
                    .font(.system(size: 11, weight: .semibold, design: .monospaced))
                    .tracking(1.6)
                    .foregroundStyle(p.accent)
                Spacer()
                Text(reason.name)
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(p.textMuted)
            }
            .padding(.horizontal, 16)
            .frame(height: 40)
            .background(p.ground)
            hairline(p)
            VStack(alignment: .leading, spacing: 0) {
                Text(Strings.fill(Strings.unreachableTitle, ["computer": computer.name]))
                    .font(.system(size: 17, weight: .semibold, design: .monospaced))
                    .foregroundStyle(p.text)
                    .padding(.vertical, 16)
                hairline(p)
                Text(reason.detail(computer: computer.name))
                    .font(.system(size: 13, design: .monospaced))
                    .foregroundStyle(p.textMuted)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.vertical, 16)
                hairline(p)
                HStack(alignment: .firstTextBaseline) {
                    Text(Strings.unreachableAddress)
                        .foregroundStyle(p.textFaint)
                    Text(computer.origin.rootURL.absoluteString)
                        .foregroundStyle(p.textMuted)
                        .lineLimit(1)
                        .truncationMode(.middle)
                    if computer.isUnencrypted {
                        Text(Strings.tagUnencrypted).foregroundStyle(p.warning)
                    }
                }
                .font(.system(size: 11, design: .monospaced))
                .padding(.vertical, 12)
                hairline(p)
            }
            .padding(.horizontal, 16)
            Spacer(minLength: 0)
            hairline(p)
            HStack(spacing: 8) {
                Spacer()
                outlined(Strings.actionComputers, edge: p.line, ink: p.textMuted, fill: .clear, action: close)
                outlined(Strings.actionRetry, edge: p.success, ink: p.success, fill: p.success.opacity(0.12), action: retry)
            }
            .padding(12)
            .background(p.ground)
        }
        .background(p.page.ignoresSafeArea())
    }

    private func hairline(_ p: Palette) -> some View {
        Rectangle().fill(p.line).frame(height: 1)
    }

    private func outlined(_ title: String, edge: Color, ink: Color, fill: Color,
                          action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: 13, design: .monospaced))
                .foregroundStyle(ink)
                .padding(.horizontal, 16)
                .frame(minHeight: 40)
                .background(fill)
                .overlay(RoundedRectangle(cornerRadius: 2).stroke(edge, lineWidth: 1))
        }
        .buttonStyle(.plain)
    }
}
