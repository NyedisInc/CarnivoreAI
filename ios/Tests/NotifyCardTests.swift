import CryptoKit
import SwiftUI
import UserNotifications
import XCTest
@testable import Carnivore

final class NotifyCardTests: XCTestCase {
    private struct Vector: Decodable { let name, device_id, key, ciphertext: String }
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
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "notify_payload_vectors", withExtension: "json"))
        return try JSONDecoder().decode(VectorFile.self, from: Data(contentsOf: url)).cases
    }

    private func fixture(_ name: String) throws -> (payload: [String: Any], card: NotifyCard) {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: name, withExtension: "json", subdirectory: "notify_cards"), name)
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
        return (object["payload"] as? [String: Any] ?? [:], NotifyCard(raw: object["card"] as? [String: Any] ?? [:]))
    }

    private func texts(_ model: CardModel) -> [String] {
        var out = [model.word, model.whereText]
        for block in model.blocks {
            switch block {
            case let .question(t, _, _), let .secondary(t), let .warning(t), let .exitCode(t), let .more(t), let .image(t): out.append(t)
            case let .rows(rows): out += rows.flatMap { [$0.key, $0.value] }
            case let .command(lines, _): out += lines
            case let .options(opts): out += opts.flatMap { [$0.letter, $0.label, $0.desc] }
            case let .fileHead(n, t, m, f): out += [n, t, m, f]
            case let .domain(h, p): out += [h, p]
            case let .video(c, o): out += [c] + (o.map { [$0] } ?? [])
            case let .version(a, b): out += [a, b]
            case let .changes(l), let .tail(l): out += l
            case let .fileList(l): out += l.flatMap { $0 }
            case let .positions(p), let .thread(p): out += p.flatMap { $0 }
            }
        }
        return out
    }


    func testV2VectorsDecodeForAllFifteenKinds() throws {
        var seen = Set<NotifyKind>()
        for v in try vectors() {
            let payload = try PayloadCrypto.open(blob: hex(v.ciphertext), key: SymmetricKey(data: hex(v.key)), rowId: v.device_id)
            let env = try XCTUnwrap(payload.envelope, v.name)
            if v.name != "huge" { XCTAssertEqual(env.kind.rawValue, v.name) }
            XCTAssertLessThanOrEqual(env.acts.count, NotifyContract.limitActs, v.name)
            XCTAssertFalse(try XCTUnwrap(payload.title).isEmpty, v.name)
            if env.kind != .notice { XCTAssertEqual(env.cap?.count, NotifyContract.limitCap, v.name) }
            XCTAssertTrue(env.cardJSON != nil || env.more, v.name)
            seen.insert(env.kind)
        }
        XCTAssertEqual(seen, Set(NotifyKind.allCases))
    }

    func testV1PayloadStillDecodesWithoutAnEnvelope() throws {
        let v1 = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "apns_payload_vectors", withExtension: "json"))
        let first = try XCTUnwrap(JSONDecoder().decode(VectorFile.self, from: Data(contentsOf: v1)).cases.first)
        let payload = try PayloadCrypto.open(blob: hex(first.ciphertext), key: SymmetricKey(data: hex(first.key)), rowId: first.device_id)
        XCTAssertNil(payload.envelope)
        XCTAssertNotNil(payload.title)
    }

    func testUserInfoRoundTripsTheCardAndTheCapability() throws {
        let v = try XCTUnwrap(try vectors().first { $0.name == "permission" })
        let payload = try PayloadCrypto.open(blob: hex(v.ciphertext), key: SymmetricKey(data: hex(v.key)), rowId: v.device_id)
        let env = try XCTUnwrap(payload.envelope)
        let info = try XCTUnwrap(NotifyUserInfo(userInfo: NotifyUserInfo.encode(env, origin: "https://abc.link.carnivore.ai:443")))
        XCTAssertEqual(info.kind, .permission)
        XCTAssertEqual(info.cap, env.cap)
        XCTAssertEqual(info.base, URL(string: "https://abc.link.carnivore.ai:443"))
        XCTAssertEqual(info.acts, env.acts)
        XCTAssertEqual(NotifyCard(json: info.cardJSON).string("tool"), "bash")
        XCTAssertTrue(info.isExpired(now: Date(timeIntervalSince1970: 1_800_000_000)))
        XCTAssertFalse(info.isExpired(now: Date(timeIntervalSince1970: 1_700_000_000)))
    }


    func testCategoriesCarryTheContractFlags() throws {
        let categories = NotifyCategories.all()
        XCTAssertEqual(categories.count, NotifyKind.allCases.count)
        for kind in NotifyKind.allCases {
            let category = try XCTUnwrap(categories.first { $0.identifier == NotifyContract.categoryId(kind) }, kind.rawValue)
            let want = NotifyContract.actions[kind] ?? []
            XCTAssertEqual(category.actions.map(\.identifier), want.map(\.id), kind.rawValue)
            for (action, spec) in zip(category.actions, want) {
                let expectAuth = spec.faceId || spec.id == "copy_link" || spec.id == "play"
                XCTAssertEqual(action.options.contains(.authenticationRequired), expectAuth, "\(kind) \(spec.id)")
                XCTAssertEqual(action.options.contains(.foreground), spec.foreground, "\(kind) \(spec.id)")
                XCTAssertEqual(action is UNTextInputNotificationAction, spec.textInput, "\(kind) \(spec.id)")
                XCTAssertFalse(action.options.contains(.destructive), "no red: \(kind) \(spec.id)")
                XCTAssertFalse(action.title.isEmpty)
            }
        }
    }

    func testPayloadActsReplaceTheStaticLabelsAndKeepFaceId() {
        let actions = NotifyCategories.actions(kind: .permission, acts: [["opt.1", "allow"], ["opt.4", "deny"]])
        XCTAssertEqual(actions.map(\.title), ["allow", "deny"])
        XCTAssertTrue(actions.allSatisfy { $0.options.contains(.authenticationRequired) })
    }


    func testQuestionKindsDrawQuestionGlyphNotIdleMinus() {
        XCTAssertEqual(CardGlyphs.name(for: .yesno), "question")
        XCTAssertEqual(CardGlyphs.name(for: .choice), "question")
        XCTAssertEqual(CardModel.hue(for: .yesno), .caution)
        XCTAssertEqual(CardModel.hue(for: .choice), .caution)
    }

    func testEveryKindShowsItsExpectedStrings() throws {
        let expect: [String: [String]] = [
            "yesno": ["question", "api-docs . nostromo", "merge exp/argent-widget-engine into master?", "on your answer"],
            "choice": ["pick one", "plan a", "A", "patch the widget engine in place, smallest diff, 1 file"],
            "permission": ["run npm run build in web/?", "cd web && npm run build", "bash", "web/", "needs face id when locked"],
            "file": ["mix-v3-notes.pdf", "214 KB, 3 pages", "pdf", "from mixdown-2"],
            "link": ["carnivore.ai", "/preview", "https://carnivore.ai/preview", "safari", "carnivore.ai preview build"],
            "image": ["dashboard screenshot, 1170 by 2532"],
            "video": ["repro of the resize bug, 0:24"],
            "finished": ["done in 6 min", "src/core/sessions/resize.py", "+18 -4", "+31 -0"],
            "died": ["vite v6 building for production", "exit code 1"],
            "update": ["2 sessions run an older version", "2.1.301 to 2.1.312", "billing-5, api-docs"],
            "appupdate": ["1.16.8", "you have 1.16.7", "your global ai setup syncs across the pack"],
            "swarm": ["which order should the board cards run in?", "home"],
            "crosstalk": ["api-docs", "tests are green, ready for you"],
            "signin": ["the renewal was refused, sign in again", "nyedis (claude)", "renewal refused", "home, mixdown-2"],
            "notice": ["carnivore alert", "something changed, open it to read more"],
        ]
        for kind in NotifyKind.allCases {
            let (payload, card) = try fixture(kind.rawValue)
            let model = CardModel.make(kind: kind, card: card, body: payload["body"] as? String)
            XCTAssertFalse(model.isEmpty, kind.rawValue)
            let all = texts(model)
            for needle in expect[kind.rawValue] ?? [] {
                XCTAssertTrue(all.contains { $0.contains(needle) }, "\(kind): \(needle) in \(all)")
            }
        }
    }


    private func make(_ kind: NotifyKind, _ raw: [String: Any], body: String? = "x") -> [String] { texts(CardModel.make(kind: kind, card: NotifyCard(raw: raw), body: body)) }

    func testFinishedDrawsPerFileLineCountsAndLeavesOutUnknownOnes() {
        let all = make(.finished, ["files": ["a.py", "b.ts", "c.bin"], "stats": [[18, 4], [9, 2], []], "mins": 6])
        XCTAssertTrue(all.contains("+18 -4") && all.contains("+9 -2"))
        XCTAssertEqual(all.filter { $0.hasPrefix("+") }.count, 2)
        XCTAssertTrue(all.contains("c.bin"))
        XCTAssertEqual(make(.finished, ["files": ["a.py"], "mins": 6]).filter { $0.hasPrefix("+") }, [])
    }

    func testFileDrawsPageCountAndFirstPageOnlyWhenPresent() {
        let base: [String: Any] = ["name": "mix.pdf", "bytes": 219_136, "from": "mixdown-2"]
        XCTAssertTrue(make(.file, base.merging(["pages": 3]) { $1 }).contains("214 KB, 3 pages"))
        XCTAssertTrue(make(.file, base.merging(["head": ["mix v3 notes"]]) { $1 }).contains(Strings.cardRowFirstPage))
        let plain = make(.file, base)
        XCTAssertTrue(plain.contains("214 KB") && !plain.contains(Strings.cardRowFirstPage))
    }

    func testSwarmPositionNamesTheComputerWhenTheCardSaysSo() {
        let positions: [[String]] = [["home", "smallest first", "studio"], ["api-docs", "riskiest first"]]
        let model = CardModel.make(kind: .swarm, card: NotifyCard(raw: ["ask": "which order?", "positions": positions]), body: "x")
        let block = model.blocks.compactMap { b -> [[String]]? in if case let .positions(p) = b { return p }; return nil }.first
        XCTAssertEqual(block?.map { $0.count }, [3, 2])
    }

    func testDiedDrawsTailAndExitOnlyWhenTheServerSentThem() {
        XCTAssertEqual(make(.died, ["tail": ["error: boom"], "exit": 137]).filter { $0.contains("exit code") }, ["exit code 137"])
        XCTAssertTrue(make(.died, ["tail": ["error: boom"]]).filter { $0.contains("exit code") }.isEmpty)
        XCTAssertTrue(make(.died, ["exit": 0]).contains("exit code 0"))
    }

    func testSigninNamesTheProviderAndUpdateAppupdateDropAbsentVersions() {
        XCTAssertTrue(make(.signin, ["account": "nyedis", "provider": "claude", "reason": "renewal refused"]).contains("nyedis (claude)"))
        XCTAssertTrue(make(.update, ["agent": "claude code", "from": "2.1.301", "to": "2.1.312"]).contains("2.1.301 to 2.1.312"))
        XCTAssertFalse(make(.update, ["agent": "claude code", "to": "2.1.312"]).contains { $0.contains(" to ") })
        XCTAssertFalse(make(.appupdate, ["to": "1.16.8"]).contains { $0.contains("you have") })
    }

    func testSettleLineFollowsWhere() {
        func line(_ place: String) -> String { NotifySettle(place: place, agent: "a", working: false).line }
        XCTAssertEqual(line("computer"), Strings.cardStateSettled)
        XCTAssertEqual(line("phone"), Strings.cardStateAlreadyUsed)
        XCTAssertEqual(line("auto"), Strings.cardStateAnswered)
        XCTAssertEqual(line("elsewhere"), Strings.cardStateAnswered)
    }

    func testHugeClipsAtTwelveLinesAndEmptyReadsNothingToOpen() throws {
        var cmd = (0..<200).map { "./scripts/check-step-\($0).sh && \\" }
        cmd[0] = "cd web && npm run build && \\"
        let huge = CardModel.make(kind: .permission, card: NotifyCard(raw: ["strip": ["permission", "a", "b"], "cmd": cmd, "tool": "bash", "dir": "web/"]), body: "x")
        let lines = huge.blocks.compactMap { b -> Int? in if case let .command(l, clipped) = b, clipped { return l.count }; return nil }
        XCTAssertEqual(lines, [NotifyContract.limitCardClipLines])
        XCTAssertTrue(texts(huge).contains(Strings.fill(Strings.cardStateMoreCount, ["count": "200", "unit": Strings.cardUnitLines])))
        let longAsk = String(repeating: "step of the merge plan touches the widget engine. ", count: 30)
        let long = CardModel.make(kind: .yesno, card: NotifyCard(raw: ["ask": longAsk]), body: nil)
        XCTAssertTrue(texts(long).contains(Strings.cardStateMore))
        let empty = CardModel.make(kind: .yesno, card: NotifyCard(raw: [:]), body: nil)
        XCTAssertTrue(empty.isEmpty)
        XCTAssertEqual(texts(empty), [Strings.cardStateNothing, Strings.cardStateNoOpen, Strings.cardStateEmpty])
    }

    func testSizeAndDurationText() {
        XCTAssertEqual(CardModel.sizeText(219_136), "214 KB")
        XCTAssertEqual(CardModel.sizeText(54_525_952), "52 MB")
        XCTAssertEqual(CardModel.durationText(24), "0:24")
    }

    @MainActor func testEveryKindDrawsANonEmptyFrameInDarkAndLight() throws {
        for scheme in [ColorScheme.dark, .light] {
            for kind in NotifyKind.allCases {
                let (payload, card) = try fixture(kind.rawValue)
                let view = CardView(model: CardModel.make(kind: kind, card: card, body: payload["body"] as? String)).frame(width: 361).environment(\.colorScheme, scheme)
                let renderer = ImageRenderer(content: view)
                renderer.scale = 2
                let image = try XCTUnwrap(renderer.uiImage, "\(kind) \(scheme)")
                XCTAssertGreaterThan(image.size.height, 80, "\(kind) \(scheme)")
                XCTAssertGreaterThan(inkFraction(image), 0.01, "blank frame: \(kind) \(scheme)")
            }
        }
    }

    @MainActor func testThumbnailRendersForEveryKind() {
        for kind in NotifyKind.allCases {
            XCTAssertGreaterThan(CardThumb.png(kind: kind)?.count ?? 0, 200, kind.rawValue)
        }
    }

    private func inkFraction(_ image: UIImage) -> Double {
        guard let cg = image.cgImage, let data = cg.dataProvider?.data, let bytes = CFDataGetBytePtr(data) else { return 0 }
        let bpp = cg.bitsPerPixel / 8, total = cg.width * cg.height
        var differ = 0
        for i in 0..<total {
            let o = i * bpp
            if abs(Int(bytes[o]) - Int(bytes[0])) > 24 || abs(Int(bytes[o + 1]) - Int(bytes[1])) > 24 || abs(Int(bytes[o + 2]) - Int(bytes[2])) > 24 { differ += 1 }
        }
        return Double(differ) / Double(total)
    }

    func testDarkCardTonesDeriveFromTheCarnivorePalette() {
        func rgb(_ c: Color) -> [CGFloat] {
            var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
            UIColor(c).getRed(&r, green: &g, blue: &b, alpha: &a)
            return [r, g, b].map { ($0 * 255).rounded() }
        }
        let p = Palettes.palette(id: "carnivore")
        XCTAssertEqual(rgb(CardTones.dark.page), rgb(p.page))
        XCTAssertEqual(rgb(CardTones.dark.linePanel), rgb(p.line))
    }


    func testActOutcomesFollowTheRouteTable() {
        func body(_ s: String) -> Data { Data(s.utf8) }
        XCTAssertEqual(AnswerClient.outcome(status: 200, body: body(#"{"state":"sent","agent":"api-docs","working":true}"#)), .sent(agent: "api-docs", working: true, replay: false))
        XCTAssertEqual(AnswerClient.outcome(status: 200, body: body(#"{"state":"sent","agent":"a","working":false,"replay":true}"#)), .sent(agent: "a", working: false, replay: true))
        XCTAssertEqual(AnswerClient.outcome(status: 409, body: body(#"{"error":"already_answered","where":"computer"}"#)), .alreadyAnswered)
        XCTAssertEqual(AnswerClient.outcome(status: 409, body: body(#"{"error":"already_used"}"#)), .alreadyUsed)
        XCTAssertEqual(AnswerClient.outcome(status: 410, body: body(#"{"error":"expired"}"#)), .expired)
        for status in [404, 422, 429, 500] { XCTAssertEqual(AnswerClient.outcome(status: status, body: Data()), .notSent, "\(status)") }
    }

    func testCapabilityTravelsInTheHeaderNeverTheURL() throws {
        let cap = String(repeating: "A", count: NotifyContract.limitCap)
        let req = try XCTUnwrap(AnswerClient.request(base: try XCTUnwrap(URL(string: "https://abc.link.carnivore.ai:443")), path: AnswerClient.actPath, method: "POST", cap: cap,
                                       body: AnswerClient.actBody(action: "opt.2", text: nil)))
        XCTAssertEqual(req.value(forHTTPHeaderField: AnswerClient.capHeader), cap)
        XCTAssertFalse(try XCTUnwrap(req.url).absoluteString.contains(cap))
        XCTAssertEqual(req.url?.path, "/api/v1/notify/act")
        let body = try XCTUnwrap(JSONSerialization.jsonObject(with: try XCTUnwrap(req.httpBody)) as? [String: String])
        XCTAssertEqual(body, ["action": "opt.2"])
    }
}
