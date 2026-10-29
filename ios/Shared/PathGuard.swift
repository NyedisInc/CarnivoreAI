import Foundation

enum PathGuard {
    static func isSafe(_ path: String?) -> Bool {
        guard let path, path.hasPrefix("/") else { return false }
        let scalars = Array(path.unicodeScalars)
        if scalars.count > 1, scalars[1] == "/" || scalars[1] == "\\" { return false }
        return !scalars.contains { $0 == "\\" || $0.value < 0x20 || $0.value == 0x7f }
    }
}
