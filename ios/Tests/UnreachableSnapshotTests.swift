import SwiftUI
import XCTest
@testable import Carnivore

@MainActor
final class UnreachableSnapshotTests: XCTestCase {
    func testRenderUnreachableUnderThemes() throws {
        guard let dir = ProcessInfo.processInfo.environment["SNAPSHOT_DIR"] else {
            throw XCTSkip("SNAPSHOT_DIR not set")
        }
        let origin = Origin(url: URL(string: "https://abcdefghijklmnopqrstuvwxyz.link.carnivore.ai")!)!
        let computer = Computer(name: "studio", kind: .relay, origin: origin)
        for id in ["carnivore", "green_crt", "matrix", "carnivore-light"] {
            let defaults = UserDefaults(suiteName: "snapshot-\(id)")!
            let store = ThemeStore(defaults: defaults)
            store.report(id: id)
            let view = UnreachableView(computer: computer, reason: .linkOffline, retry: {}, close: {})
                .environmentObject(store)
                .frame(width: 390, height: 844)
            let renderer = ImageRenderer(content: view)
            renderer.scale = 3
            let png = try XCTUnwrap(renderer.uiImage?.pngData())
            try png.write(to: URL(fileURLWithPath: dir).appendingPathComponent("unreachable-\(id).png"))
        }
    }
}
