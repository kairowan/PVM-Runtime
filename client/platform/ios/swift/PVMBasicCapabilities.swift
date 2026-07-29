import Foundation
import UIKit

@MainActor
public enum PVMBasicCapabilities {
    public static func install(
        registry: PVMCapabilityRegistry,
        presenting: UIViewController,
        defaults: UserDefaults = .standard
    ) -> PVMPushInbox {
        registry.registerSync("ui.toast") { operation, arguments in
            guard operation == "show", let message = arguments.first as? String else {
                throw PVMHostError("Invalid ui.toast call")
            }
            let alert = UIAlertController(title: nil, message: message, preferredStyle: .alert)
            presenting.present(alert, animated: true)
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { alert.dismiss(animated: true) }
            return "ok"
        }
        registry.registerAsync("storage.kv") { operation, arguments, complete in
            guard registry.policy?.storageScopes.contains("app.preferences") == true,
                  let key = arguments.first as? String
            else { throw PVMHostError("Storage scope or key is invalid") }
            switch operation {
            case "get": complete(defaults.string(forKey: key) ?? "Not set")
            case "set":
                defaults.set(arguments.dropFirst().first as? String, forKey: key)
                complete("ok")
            case "remove":
                defaults.removeObject(forKey: key)
                complete("ok")
            default: throw PVMHostError("Unsupported storage.kv operation")
            }
        }
        registry.registerAsync("network.http") { operation, arguments, complete in
            guard operation == "get", let rawURL = arguments.first as? String,
                  let url = URL(string: rawURL), url.scheme == "https",
                  let host = url.host?.lowercased(),
                  registry.policy?.networkDomains.contains(host) == true
            else { throw PVMHostError("Network domain is not declared by the signed module") }
            var request = URLRequest(url: url, cachePolicy: .reloadRevalidatingCacheData, timeoutInterval: 15)
            request.httpMethod = "GET"
            let delegate = PVMHTTPDelegate(allowedDomains: Set(registry.policy?.networkDomains ?? []))
            let configuration = URLSessionConfiguration.ephemeral
            configuration.httpShouldSetCookies = false
            let session = URLSession(configuration: configuration, delegate: delegate, delegateQueue: nil)
            session.dataTask(with: request) { data, response, error in
                defer { session.finishTasksAndInvalidate() }
                let status = (response as? HTTPURLResponse)?.statusCode ?? 0
                let finalHost = response?.url?.host?.lowercased()
                let validOrigin =
                    response?.url?.scheme == "https" &&
                    finalHost.map(delegate.allowedDomains.contains) == true
                let oversized = (data?.count ?? 0) > 1_048_576
                let body =
                    !oversized ? String(data: data ?? Data(), encoding: .utf8) ?? "" : ""
                var result: [String: Any] = [
                    "ok": error == nil && validOrigin && !oversized &&
                        (200...299).contains(status),
                    "status": status,
                    "body": body,
                ]
                if let error { result["error"] = error.localizedDescription }
                if !validOrigin { result["error"] = "Redirected to an undeclared domain" }
                if oversized { result["error"] = "HTTP body exceeds 1 MiB" }
                let encoded = try? JSONSerialization.data(withJSONObject: result)
                complete(encoded.flatMap { String(data: $0, encoding: .utf8) } ?? #"{"ok":false}"#)
            }.resume()
        }
        return PVMPushInbox(registry: registry, defaults: defaults)
    }
}

private final class PVMHTTPDelegate: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    let allowedDomains: Set<String>

    init(allowedDomains: Set<String>) {
        self.allowedDomains = allowedDomains
    }

    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        willPerformHTTPRedirection response: HTTPURLResponse,
        newRequest request: URLRequest,
        completionHandler: @escaping (URLRequest?) -> Void
    ) {
        guard request.url?.scheme == "https",
              let host = request.url?.host?.lowercased(),
              allowedDomains.contains(host)
        else {
            completionHandler(nil)
            return
        }
        completionHandler(request)
    }
}

public final class PVMPushInbox: @unchecked Sendable {
    private let defaults: UserDefaults
    private let key = "pvm.push.inbox"
    private let lock = NSLock()

    init(registry: PVMCapabilityRegistry, defaults: UserDefaults) {
        self.defaults = defaults
        registry.registerAsync("push.inbox") { [weak self] operation, _, complete in
            guard operation == "drain", let self else { throw PVMHostError("Push inbox unavailable") }
            complete(self.drain())
        }
    }

    public func enqueue(_ payload: [String: Any]) {
        lock.lock()
        defer { lock.unlock() }
        var events = defaults.array(forKey: key) as? [[String: Any]] ?? []
        if events.count >= 100 { events.removeFirst() }
        events.append(payload)
        defaults.set(events, forKey: key)
    }

    private func drain() -> String {
        lock.lock()
        defer { lock.unlock() }
        let events = defaults.array(forKey: key) ?? []
        defaults.removeObject(forKey: key)
        let data = try? JSONSerialization.data(withJSONObject: events)
        return data.flatMap { String(data: $0, encoding: .utf8) } ?? "[]"
    }
}
