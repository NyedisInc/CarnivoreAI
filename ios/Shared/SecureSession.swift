import Foundation

final class RedirectBlockingDelegate: NSObject, URLSessionTaskDelegate, Sendable {
    static let shared = RedirectBlockingDelegate()

    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        willPerformHTTPRedirection response: HTTPURLResponse,
        newRequest request: URLRequest,
        completionHandler: @escaping (URLRequest?) -> Void
    ) {
        completionHandler(nil)
    }
}

enum SecureSession {
    static let shared: URLSession = make(timeout: 20)

    static func make(timeout: TimeInterval = 20) -> URLSession {
        let cfg = URLSessionConfiguration.ephemeral
        cfg.httpShouldSetCookies = false
        cfg.httpCookieAcceptPolicy = .never
        cfg.httpCookieStorage = nil
        cfg.urlCache = nil
        cfg.requestCachePolicy = .reloadIgnoringLocalCacheData
        cfg.timeoutIntervalForRequest = timeout
        cfg.timeoutIntervalForResource = max(timeout, 30)
        return URLSession(configuration: cfg, delegate: RedirectBlockingDelegate.shared, delegateQueue: nil)
    }
}
