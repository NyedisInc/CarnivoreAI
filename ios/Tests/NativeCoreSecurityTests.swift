import CryptoKit
import Foundation
import XCTest
@testable import Carnivore

final class NativeCoreSecurityTests: XCTestCase {

    func testNotificationMACSignVerifyAndTamperRejection() {
        let key = SymmetricKey(size: .bits256)
        let raw: [String: String] = [
            "kind": "permission",
            "base": "https://abcdefghijklmnopqrstuvwxy2.link.carnivore.ai:443",
            "cap": String(repeating: "a", count: 43),
            "path": "/session/ses_123",
            "origin": "https://abcdefghijklmnopqrstuvwxy2.link.carnivore.ai:443",
        ]
        let signed = NotificationMAC.sign(raw, key: key)
        XCTAssertNotNil(signed[NotificationMAC.macKey])
        XCTAssertTrue(NotificationMAC.verify(signed, key: key))

        var tamperedBase = signed
        tamperedBase["base"] = "https://evil.example.com:443"
        XCTAssertFalse(NotificationMAC.verify(tamperedBase, key: key))

        var tamperedPath = signed
        tamperedPath["path"] = "/session/other"
        XCTAssertFalse(NotificationMAC.verify(tamperedPath, key: key))

        XCTAssertFalse(NotificationMAC.verify(raw, key: key))
        XCTAssertNil(NotifyUserInfo(userInfo: raw, requireValidMAC: true))
    }

    func testNotifyUserInfoPinsAllowedBaseAndValidatesMediaId() {
        let validHost = "https://abcdefghijklmnopqrstuvwxy2.link.carnivore.ai:443"
        XCTAssertTrue(NotifyUserInfo.isAllowedBase(URL(string: validHost)!))
        XCTAssertFalse(NotifyUserInfo.isAllowedBase(URL(string: "https://attacker.example.com:443")!))
        XCTAssertFalse(NotifyUserInfo.isAllowedBase(URL(string: "http://abcdefghijklmnopqrstuvwxy2.link.carnivore.ai:80")!))
        XCTAssertFalse(NotifyUserInfo.isAllowedBase(URL(string: "https://abcdefghijklmnopqrstuvwxy2.link.carnivore.ai:8443")!))

        XCTAssertTrue(NotifyMedia.isValidId("0123456789abcdef0123456789abcdef"))
        XCTAssertFalse(NotifyMedia.isValidId("../etc/passwd"))
        XCTAssertFalse(NotifyMedia.isValidId("0123456789abcdef0123456789abcde?"))
        XCTAssertFalse(NotifyMedia.isValidId("0123456789ABCDEF0123456789ABCDEF"))
        XCTAssertFalse(NotifyMedia.isValidId("short"))
    }


    func testAnswerClientRefusesSmuggledPathsAndBlocksRedirects() {
        let base = URL(string: "https://abcdefghijklmnopqrstuvwxy2.link.carnivore.ai")!
        XCTAssertNotNil(AnswerClient.request(base: base, path: "/api/v1/notify/act", method: "POST", cap: "abc"))
        XCTAssertNil(AnswerClient.request(base: base, path: "//evil.com/steal", method: "GET", cap: "abc"))
        XCTAssertNil(AnswerClient.request(base: base, path: "https://evil.com/steal", method: "GET", cap: "abc"))
        XCTAssertNil(AnswerClient.request(base: base, path: "relative/no-slash", method: "GET", cap: "abc"))

        let exp = expectation(description: "redirect blocked")
        let dummyResponse = HTTPURLResponse(url: base, statusCode: 302, httpVersion: nil, headerFields: ["Location": "https://evil.com"])!
        let redirectedReq = URLRequest(url: URL(string: "https://evil.com")!)
        let dummyTask = SecureSession.shared.dataTask(with: base)
        RedirectBlockingDelegate.shared.urlSession(
            SecureSession.shared,
            task: dummyTask,
            willPerformHTTPRedirection: dummyResponse,
            newRequest: redirectedReq
        ) { next in
            XCTAssertNil(next, "Redirects must be blocked so tokens/capabilities never leak")
            exp.fulfill()
        }
        wait(for: [exp], timeout: 2)
    }


    func testIPv6OriginsDoNotCrashAndBracketProperly() throws {
        let origin = try XCTUnwrap(Origin(url: URL(string: "http://[::1]:8000/")!))
        XCTAssertTrue(origin.isIPv6)
        XCTAssertEqual(origin.host, "::1")
        XCTAssertEqual(origin.uriHost, "[::1]")
        XCTAssertEqual(origin.rootURL.absoluteString, "http://[::1]:8000/")
        XCTAssertEqual(origin.pushId, "http://[::1]:8000")
        XCTAssertEqual(origin.wsURL(path: "/ws/events")?.absoluteString, "ws://[::1]:8000/ws/events")
        XCTAssertEqual(origin.apiURL(path: "/api/v1/approvals")?.absoluteString, "http://[::1]:8000/api/v1/approvals")

        if case .success(let parsed) = AddressParser.parse("[fe80::1]:8000", kind: .lan) {
            XCTAssertEqual(parsed.rootURL.absoluteString, "http://[fe80::1]:8000/")
        } else {
            XCTFail("Expected valid IPv6 LAN origin")
        }
    }

    func testRegexAnchorsRejectTrailingNewlines() {
        XCTAssertFalse(PushKeyStore.isRowId("d_0123456789ab\n"))
        XCTAssertFalse(StatusKeyStore.isWellFormed(String(repeating: "a", count: 32) + "\n"))
        if case .success = AddressParser.parse("192.168.1.9\n", kind: .lan) {
        }
        if case .success = AddressParser.parse("192.168.1.9\nevil.com", kind: .lan) {
            XCTFail("Inner newline must be refused")
        }
    }


    func testDualSlotRotationKeepsOldKeyActiveUntilCommitted() {
        let origin = "https://a.example:443"
        var list = PushKeyStore.preparing([], origin: origin).list
        let originalKey = list[0].key
        list = PushKeyStore.setting(rowId: "d_aaaaaaaaaaaa", origin: origin, in: list)
        XCTAssertEqual(PushKeyStore.candidates(from: list).count, 1)

        let reReg = PushKeyStore.preparing(list, origin: origin)
        XCTAssertEqual(PushKeyStore.candidates(from: reReg.list).count, 1)
        XCTAssertEqual(reReg.list[0].key, originalKey)
        XCTAssertNotNil(reReg.list[0].pendingKey)
        XCTAssertNotEqual(reReg.list[0].pendingKey, originalKey)

        let committed = PushKeyStore.setting(rowId: "d_bbbbbbbbbbbb", origin: origin, in: reReg.list)
        XCTAssertEqual(committed[0].key, reReg.list[0].pendingKey)
        XCTAssertNil(committed[0].pendingKey)
        XCTAssertEqual(committed[0].rowId, "d_bbbbbbbbbbbb")
    }


    func testSafeFilenameStripsTraversalAndControlChars() {
        XCTAssertEqual(NotifyActions.safeFilename("../../etc/passwd"), "passwd")
        XCTAssertEqual(NotifyActions.safeFilename("report:2026.pdf"), "report_2026.pdf")
        XCTAssertEqual(NotifyActions.safeFilename("..."), "file")
    }

    func testDictationFirstWordRevisionDoesNotDuplicateSentence() {
        var t = DictationTranscript()
        t.absorb(Heard(text: "run all unit tests"))
        t.absorb(Heard(text: "Wait run all unit tests"))
        XCTAssertEqual(t.text, "Wait run all unit tests")
    }


    func testCardThumbCGRendersPNGForAllFifteenKinds() {
        for kind in NotifyKind.allCases {
            let png = CardThumbCG.png(kind: kind)
            XCTAssertNotNil(png, "Missing CG PNG for \(kind.rawValue)")
            XCTAssertGreaterThan(png?.count ?? 0, 100, "Tiny PNG for \(kind.rawValue)")
        }
    }


    @MainActor
    func testTapRouterHandlesNativeDeepLinks() {
        let router = TapRouter.shared
        XCTAssertTrue(router.handleURL(URL(string: "carnivore://session/ses_abc123")!))
        XCTAssertEqual(router.consumeDeepLink(), .session(id: "ses_abc123"))

        XCTAssertTrue(router.handleURL(URL(string: "carnivore://inbox")!))
        XCTAssertEqual(router.consumeDeepLink(), .inbox)

        XCTAssertTrue(router.handleURL(URL(string: "carnivore://dictate?session=ses_9")!))
        XCTAssertEqual(router.consumeDeepLink(), .dictate(sessionId: "ses_9"))

        XCTAssertFalse(router.handleURL(URL(string: "https://evil.example/session/1")!))
    }

    @MainActor
    func testAppLockManagerRespectsEnabledToggle() {
        let suite = UserDefaults(suiteName: "applock-test-\(UUID().uuidString)")!
        let lock = AppLockManager(defaults: suite)
        XCTAssertTrue(lock.isEnabled)
        lock.lockNow()
        XCTAssertTrue(lock.isLocked)
        lock.isEnabled = false
        XCTAssertFalse(lock.isLocked)
    }

    @MainActor
    func testWebAuthHandoffBuildsLinkCookieAndOriginPinnedSeedScript() throws {
        let origin = try XCTUnwrap(Origin(url: URL(string: "https://abcdefghijklmnopqrstuvwxy2.link.carnivore.ai")!))
        let cookie = try XCTUnwrap(WebAuthHandoff.makeLinkCookie(origin: origin, rawCookie: "__Host-cc_link=abc123token"))
        XCTAssertEqual(cookie.name, "__Host-cc_link")
        XCTAssertEqual(cookie.value, "abc123token")
        XCTAssertEqual(cookie.domain, "abcdefghijklmnopqrstuvwxy2.link.carnivore.ai")
        XCTAssertEqual(cookie.path, "/")
        XCTAssertTrue(cookie.isSecure)
        XCTAssertTrue(cookie.isHTTPOnly)

        let lanOrigin = try XCTUnwrap(Origin(url: URL(string: "http://192.168.1.5:8000")!))
        XCTAssertNil(WebAuthHandoff.makeLinkCookie(origin: lanOrigin, rawCookie: "__Host-cc_link=abc"))

        let creds = AuthCredentials(accessToken: "acc.1", refreshToken: "ref.2", linkCookie: "__Host-cc_link=abc123token", expiresAt: nil)
        let handoff = WebAuthHandoff(originId: origin.pushId, credentials: creds, overwriteLocalStorage: true, nonce: "n1")
        let script = try XCTUnwrap(WebAuthHandoff.makeSeedScript(origin: origin, handoff: handoff))
        XCTAssertTrue(script.contains("https://abcdefghijklmnopqrstuvwxy2.link.carnivore.ai"))
        XCTAssertTrue(script.contains("claude_tunnel_token"))
        XCTAssertTrue(script.contains("claude_refresh_token"))
        XCTAssertTrue(script.contains("__cc_native_handoff_"))
    }


    func testPairAndLinkCookieExtractionHandlesHostPrefixCookies() {
        let pairHeader = "__Host-cc_pair=abc123_XYZ-9; HttpOnly; Max-Age=600; Path=/; SameSite=strict; Secure"
        XCTAssertEqual(
            CarnivoreAPI.parseCookieValue(named: "__Host-cc_pair", fromSetCookieHeader: pairHeader),
            "__Host-cc_pair=abc123_XYZ-9"
        )
        let combined = "__Host-cc_link=tok_999; Path=/; Secure, __Host-cc_pair=; Max-Age=0"
        XCTAssertEqual(
            CarnivoreAPI.parseCookieValue(named: "__Host-cc_link", fromSetCookieHeader: combined),
            "__Host-cc_link=tok_999"
        )
        XCTAssertNil(CarnivoreAPI.parseCookieValue(named: "__Host-cc_pair", fromSetCookieHeader: combined))
    }

    func testLinkCookieOnlyCredentialsAreNotTreatedAsSignedIn() {
        let linkOnly = AuthCredentials(accessToken: "", refreshToken: "", linkCookie: "__Host-cc_link=xyz", expiresAt: nil)
        XCTAssertFalse(linkOnly.hasTokens)
        let authed = AuthCredentials(accessToken: "jwt.abc.def", refreshToken: "ref.123", linkCookie: "__Host-cc_link=xyz", expiresAt: nil)
        XCTAssertTrue(authed.hasTokens)
    }

    func testRelayHashComputerNameMasksHashAndExtractsSelfLabelFromPackActivity() throws {
        let host = "abcdefghijklmnopqrstuvwxy2.link.carnivore.ai"
        let origin = try XCTUnwrap(Origin(url: URL(string: "https://\(host)")!))
        let rawComp = Computer(name: host, kind: .relay, origin: origin)
        XCTAssertTrue(rawComp.isRawRelayHashName)
        XCTAssertEqual(rawComp.displayName, "My Computer")
        XCTAssertEqual(rawComp.shortAddress, "Relay · abcdef…")

        let namedComp = Computer(name: "nostromo", kind: .relay, origin: origin)
        XCTAssertFalse(namedComp.isRawRelayHashName)
        XCTAssertEqual(namedComp.displayName, "nostromo")

        let json = Data("""
        {"computers":[{"install_id":"inst1","label":"nostromo","is_self":true,"online":true,"cpu_pct":18.5,"ram_pct":42.0,"live_agents":3,"live_commands":1}]}
        """.utf8)
        let activity = try JSONDecoder().decode(PackActivityDTO.self, from: json)
        XCTAssertEqual(activity.selfComputerLabel, "nostromo")
        XCTAssertEqual(activity.computers?.first?.effectiveAgentsCount, 3)
        XCTAssertEqual(activity.computers?.first?.effectiveJobsCount, 1)
    }

    func testJoinedLocalOnlyErrorTranslatesToPlainEnglish() {
        let payload = Data(#"{"detail":{"reason":"joined_local_only"}}"#.utf8)
        let message = CarnivoreAPI.friendlyError(status: 403, data: payload)
        XCTAssertTrue(message.contains("Pack member"))
        XCTAssertTrue(message.contains("Main computer"))
        XCTAssertFalse(message.contains("joined_local_only"))
    }
}
