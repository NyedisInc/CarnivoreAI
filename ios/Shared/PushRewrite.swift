import CryptoKit
import Foundation

struct RewrittenPush: Equatable {
    let title: String
    let body: String
    let path: String?
    var origin: String? = nil
    var thread: String? = nil
}

enum PushRewrite {
    static let blobKey = "p"

    static let generic = RewrittenPush(title: Strings.pushGenericTitle, body: Strings.pushGenericBody, path: nil)

    struct Candidate {
        let origin: String
        let key: SymmetricKey
        let rowId: String
    }

    static func rewrite(userInfo: [AnyHashable: Any], candidates: [Candidate]) -> RewrittenPush {
        guard let encoded = userInfo[blobKey] as? String, let blob = Data(base64Encoded: encoded) else { return generic }
        for c in candidates {
            guard let payload = try? PayloadCrypto.open(blob: blob, key: c.key, rowId: c.rowId) else { continue }
            let thread = payload.thread.flatMap { $0.isEmpty || $0.count > 200 ? nil : $0 }
            return RewrittenPush(title: payload.title ?? generic.title, body: payload.body ?? generic.body,
                                 path: PathGuard.isSafe(payload.path) ? payload.path : nil, origin: c.origin, thread: thread)
        }
        return generic
    }
}
