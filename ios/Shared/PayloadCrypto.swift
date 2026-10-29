import CryptoKit
import Foundation

struct PushPayload: Equatable {
    let title: String?
    let body: String?
    let path: String?
}

enum PayloadError: Error, Equatable {
    case malformed
    case badVersion
    case authenticationFailed
    case notJSON
}

enum PayloadCrypto {
    static let version: UInt8 = 1
    static let nonceBytes = 12
    static let tagBytes = 16

    static func associatedData(rowId: String) -> Data {
        var data = Data("carnivore-apns-v1".utf8)
        data.append(0)
        data.append(Data(rowId.utf8))
        return data
    }

    static func decrypt(blob: Data, key: SymmetricKey, rowId: String) throws -> Data {
        let bytes = [UInt8](blob)
        guard bytes.count >= 1 + nonceBytes + tagBytes else { throw PayloadError.malformed }
        guard bytes[0] == version else { throw PayloadError.badVersion }
        let nonce = bytes[1..<(1 + nonceBytes)]
        let tag = bytes[(bytes.count - tagBytes)...]
        let cipher = bytes[(1 + nonceBytes)..<(bytes.count - tagBytes)]
        do {
            let box = try AES.GCM.SealedBox(nonce: AES.GCM.Nonce(data: Data(nonce)),
                                            ciphertext: Data(cipher), tag: Data(tag))
            return try AES.GCM.open(box, using: key, authenticating: associatedData(rowId: rowId))
        } catch {
            throw PayloadError.authenticationFailed
        }
    }

    static func parse(_ plaintext: Data) throws -> PushPayload {
        guard let object = try? JSONSerialization.jsonObject(with: plaintext) as? [String: Any] else {
            throw PayloadError.notJSON
        }
        return PushPayload(title: object["title"] as? String, body: object["body"] as? String,
                           path: object["path"] as? String)
    }

    static func open(blob: Data, key: SymmetricKey, rowId: String) throws -> PushPayload {
        try parse(try decrypt(blob: blob, key: key, rowId: rowId))
    }
}
