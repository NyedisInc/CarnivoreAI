import Foundation

enum UnreachableReason: Equatable {
    case noNetwork
    case serverUnreachable
    case tlsError
    case linkOffline
    case versionMismatch(server: String, needs: String)

    static func classify(_ error: Error, kind: ComputerKind) -> UnreachableReason {
        guard let code = (error as? URLError)?.code else { return .serverUnreachable }
        switch code {
        case .notConnectedToInternet, .dataNotAllowed, .internationalRoamingOff, .callIsActive:
            return .noNetwork
        case .serverCertificateUntrusted, .serverCertificateHasBadDate, .serverCertificateHasUnknownRoot,
             .serverCertificateNotYetValid, .clientCertificateRejected, .clientCertificateRequired:
            return .tlsError
        case .secureConnectionFailed, .networkConnectionLost, .cannotConnectToHost, .timedOut:
            if kind == .relay { return .linkOffline }
            return code == .secureConnectionFailed ? .tlsError : .serverUnreachable
        default:
            return .serverUnreachable
        }
    }

    var name: String {
        switch self {
        case .noNetwork: return Strings.reasonNoNetworkName
        case .serverUnreachable: return Strings.reasonServerUnreachableName
        case .tlsError: return Strings.reasonTlsErrorName
        case .linkOffline: return Strings.reasonLinkOfflineName
        case .versionMismatch: return Strings.reasonVersionMismatchName
        }
    }

    func detail(computer: String) -> String {
        switch self {
        case .noNetwork: return Strings.reasonNoNetworkDetail
        case .serverUnreachable: return Strings.fill(Strings.reasonServerUnreachableDetail, ["computer": computer])
        case .tlsError: return Strings.fill(Strings.reasonTlsErrorDetail, ["computer": computer])
        case .linkOffline: return Strings.fill(Strings.reasonLinkOfflineDetail, ["computer": computer])
        case .versionMismatch(let server, let needs):
            return Strings.fill(Strings.reasonVersionMismatchDetail,
                                ["computer": computer, "server": server, "needs": needs])
        }
    }
}
