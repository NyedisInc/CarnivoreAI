import CryptoKit
import Security
import XCTest
@testable import Carnivore

final class PushTests: XCTestCase {
    private struct Vector: Decodable {
        let name, device_id, key, nonce, aad, plaintext, ciphertext: String
    }
    private struct VectorFile: Decodable { let cases: [Vector] }

    private func hex(_ s: String) -> Data {
        var data = Data()
        var i = s.startIndex
        while i < s.endIndex {
            let j = s.index(i, offsetBy: 2)
            data.append(UInt8(s[i..<j], radix: 16)!)
            i = j
        }
        return data
    }

    private func vectors() throws -> [Vector] {
        let url = try XCTUnwrap(Bundle(for: PushTests.self).url(forResource: "apns_payload_vectors", withExtension: "json"))
        return try JSONDecoder().decode(VectorFile.self, from: Data(contentsOf: url)).cases
    }

    func testDecryptsEveryServerVector() throws {
        let all = try vectors()
        XCTAssertGreaterThanOrEqual(all.count, 3)
        for v in all {
            XCTAssertEqual(PayloadCrypto.associatedData(rowId: v.device_id), hex(v.aad), v.name)
            let plain = try PayloadCrypto.decrypt(blob: hex(v.ciphertext), key: SymmetricKey(data: hex(v.key)),
                                                  rowId: v.device_id)
            XCTAssertEqual(plain, hex(v.plaintext), v.name)
        }
    }

    func testWrongDeviceWrongKeyAndTamperFail() throws {
        let v = try XCTUnwrap(try vectors().first)
        let key = SymmetricKey(data: hex(v.key))
        let blob = hex(v.ciphertext)
        XCTAssertThrowsError(try PayloadCrypto.decrypt(blob: blob, key: key, rowId: "d_000000000000"))
        XCTAssertThrowsError(try PayloadCrypto.decrypt(blob: blob, key: SymmetricKey(size: .bits256), rowId: v.device_id))
        var tampered = blob
        tampered[20] ^= 1
        XCTAssertThrowsError(try PayloadCrypto.decrypt(blob: tampered, key: key, rowId: v.device_id))
        var oldVersion = blob
        oldVersion[0] = 2
        XCTAssertThrowsError(try PayloadCrypto.decrypt(blob: oldVersion, key: key, rowId: v.device_id))
        XCTAssertThrowsError(try PayloadCrypto.decrypt(blob: Data([1, 2, 3]), key: key, rowId: v.device_id))
    }

    func testRewriteTriesEachComputerAndNamesTheSender() throws {
        let all = try vectors()
        let v = try XCTUnwrap(all.first)
        let key = SymmetricKey(data: hex(v.key))
        let info: [AnyHashable: Any] = ["p": hex(v.ciphertext).base64EncodedString()]
        let other = PushRewrite.Candidate(origin: "https://b.example:443", key: SymmetricKey(size: .bits256),
                                          rowId: "d_000000000000")
        let right = PushRewrite.Candidate(origin: "https://a.example:443", key: key, rowId: v.device_id)
        for list in [[other, right], [right, other]] {
            let ok = PushRewrite.rewrite(userInfo: info, candidates: list)
            XCTAssertEqual(ok.title, "turn finished")
            XCTAssertEqual(ok.path, "/session/cloude_my-build")
            XCTAssertEqual(ok.origin, "https://a.example:443")
        }
        let wrongRow = PushRewrite.Candidate(origin: "https://a.example:443", key: key, rowId: "d_000000000000")
        for bad in [PushRewrite.rewrite(userInfo: info, candidates: []),
                    PushRewrite.rewrite(userInfo: info, candidates: [other, wrongRow]),
                    PushRewrite.rewrite(userInfo: ["p": "not base64!"], candidates: [right]),
                    PushRewrite.rewrite(userInfo: [:], candidates: [right])] {
            XCTAssertEqual(bad, PushRewrite.generic)
        }
        let empty = try XCTUnwrap(all.last)
        let emptyInfo: [AnyHashable: Any] = ["p": hex(empty.ciphertext).base64EncodedString()]
        let emptyCand = PushRewrite.Candidate(origin: "https://a.example:443", key: SymmetricKey(data: hex(empty.key)),
                                              rowId: empty.device_id)
        XCTAssertNil(PushRewrite.rewrite(userInfo: emptyInfo, candidates: [emptyCand]).path)
    }

    func testKeyStoreKeepsOneKeyPerComputerAndRotatesOnReregister() {
        let a = "https://a.example:443", b = "https://b.example:443"
        func b64(_ k: SymmetricKey) -> String { PushKeyStore.base64url(k) }
        var list: [PushKeyStore.Entry] = []
        let pa = PushKeyStore.preparing(list, origin: a)
        list = pa.list
        let pb = PushKeyStore.preparing(list, origin: b)
        list = pb.list
        XCTAssertNotEqual(b64(pa.key), b64(pb.key))
        XCTAssertEqual(b64(PushKeyStore.preparing(list, origin: a).key), b64(pa.key))
        list = PushKeyStore.setting(rowId: "d_aaaaaaaaaaaa", origin: a, in: list)
        list = PushKeyStore.setting(rowId: "d_bbbbbbbbbbbb", origin: b, in: list)
        XCTAssertEqual(PushKeyStore.setting(rowId: "not-a-row-id", origin: b, in: list), list)
        XCTAssertEqual(PushKeyStore.setting(rowId: "d_cccccccccccc", origin: "https://x.example:443", in: list), list)
        XCTAssertEqual(PushKeyStore.candidates(from: list).map(\.rowId), ["d_aaaaaaaaaaaa", "d_bbbbbbbbbbbb"])
        let again = PushKeyStore.preparing(list, origin: a)
        XCTAssertNotEqual(b64(again.key), b64(pa.key))
        XCTAssertEqual(PushKeyStore.candidates(from: again.list).map(\.origin), [b])
    }

    func testKeyIsDeviceOnlyAndLostKeyTriggersReregistration() {
        XCTAssertEqual(PushKeyStore.accessibility as String,
                       kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly as String)
        let a = "https://a.example:443"
        let entry = PushKeyStore.preparing([], origin: a).list
        XCTAssertTrue(PushKeyStore.needsReregistration(origin: a, registered: [a], entries: []))
        XCTAssertFalse(PushKeyStore.needsReregistration(origin: a, registered: [a], entries: entry))
        XCTAssertFalse(PushKeyStore.needsReregistration(origin: a, registered: [], entries: []))
    }

    func testBridgeTrustComparesPort() throws {
        let o = try AddressParser.parse("https://example.com", kind: .https).get()
        XCTAssertTrue(ShellBridge.sameOrigin(scheme: "https", host: "Example.com", port: 0, as: o))
        XCTAssertTrue(ShellBridge.sameOrigin(scheme: "https", host: "example.com", port: 443, as: o))
        XCTAssertFalse(ShellBridge.sameOrigin(scheme: "https", host: "example.com", port: 8443, as: o))
        XCTAssertFalse(ShellBridge.sameOrigin(scheme: "http", host: "example.com", port: 0, as: o))
    }

    func testBridgeHonorsPushOnlyForRelayLinks() throws {
        func computer(_ kind: ComputerKind, _ text: String) throws -> Computer {
            Computer(name: "x", kind: kind, origin: try AddressParser.parse(text, kind: kind).get())
        }
        let relay = try computer(.relay, "aaaaaaaaaaaaaaaaaaaaaaaaaa.link.carnivore.ai")
        XCTAssertTrue(ShellBridge(computer: relay).canPush)
        XCTAssertFalse(ShellBridge(computer: try computer(.lan, "198.51.100.10:8000")).canPush)
        XCTAssertFalse(ShellBridge(computer: try computer(.https, "https://example.com")).canPush)
        var plain = relay
        plain.origin = try AddressParser.parse("http://198.51.100.10", kind: .lan).get()
        XCTAssertFalse(ShellBridge(computer: plain).canPush)
    }

    func testTapRoutesOnlyToTheSendingComputer() {
        let router = TapRouter()
        router.tapped(userInfo: ["path": "/session/x"])
        XCTAssertNil(router.pending)
        router.tapped(userInfo: ["path": "https://evil.example", "origin": "https://a.example:443"])
        XCTAssertNil(router.pending)
        router.tapped(userInfo: ["path": "/session/x", "origin": "https://a.example:443"])
        XCTAssertNil(router.take(forOrigin: "https://b.example:443"))
        XCTAssertEqual(router.pending?.path, "/session/x")
        XCTAssertEqual(router.take(forOrigin: "https://a.example:443"), "/session/x")
        XCTAssertNil(router.pending)
    }

    func testTapPathMustBeSameOriginRelative() {
        XCTAssertEqual(TapRouter.path(from: ["path": "/session/x"]), "/session/x")
        XCTAssertEqual(TapRouter.path(from: ["path": "/"]), "/")
        for bad in ["https://evil.example/x", "//evil.example", "/\\evil.example", "javascript:alert(1)",
                    "session/x", "", "/a\nb", "/a\\b"] {
            XCTAssertNil(TapRouter.path(from: ["path": bad]), bad)
        }
        XCTAssertNil(TapRouter.path(from: [:]))
        XCTAssertNil(TapRouter.path(from: ["path": 5]))
    }
}

@MainActor
final class ThemeBridgeTests: XCTestCase {
    func testThemeMessageChangesPalette() {
        ShellBridge.reportTheme("green_crt")
        let done = expectation(description: "main queue")
        DispatchQueue.main.async { done.fulfill() }
        wait(for: [done], timeout: 2)
        XCTAssertEqual(ThemeStore.shared.palette.id, "green_crt")
        ShellBridge.reportTheme("carnivore")
    }
}
