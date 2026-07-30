import CryptoKit
import Foundation

public actor PVMModuleStore {
    public struct Configuration: Sendable {
        public let root: URL
        public let publicKeyPath: String
        public let applicationId: String
        public let channel: String
        public let profile: String
        public let server: URL
        public let activationToken: String?
        public let installationId: String?
        public let allowHTTPForLocalhost: Bool
        public let minimumRelease: UInt64

        public init(
            root: URL,
            publicKeyPath: String,
            applicationId: String,
            channel: String,
            profile: String,
            server: URL,
            activationToken: String? = nil,
            installationId: String? = nil,
            allowHTTPForLocalhost: Bool = false,
            minimumRelease: UInt64 = 0
        ) {
            self.root = root
            self.publicKeyPath = publicKeyPath
            self.applicationId = applicationId
            self.channel = channel
            self.profile = profile
            self.server = server
            self.activationToken = activationToken
            self.installationId = installationId
            self.allowHTTPForLocalhost = allowHTTPForLocalhost
            self.minimumRelease = minimumRelease
        }
    }

    public typealias Validator = @Sendable (_ module: URL, _ minimumRelease: UInt64) async throws -> UInt64

    private let config: Configuration
    private let validate: Validator
    private let fileManager = FileManager.default
    private let redirectRejector = PVMRedirectRejector()

    public init(configuration: Configuration, validator: @escaping Validator) throws {
        guard Self.isSegment(configuration.applicationId),
              Self.isSegment(configuration.channel),
              configuration.applicationId != ".", configuration.applicationId != "..",
              configuration.channel != ".", configuration.channel != "..",
              Self.profiles.contains(configuration.profile)
        else { throw PVMHostError("Invalid module store binding") }
        let localHTTP =
            configuration.allowHTTPForLocalhost &&
            configuration.server.scheme == "http" &&
            ["localhost", "127.0.0.1"].contains(configuration.server.host ?? "")
        guard configuration.server.scheme == "https" || localHTTP else {
            throw PVMHostError("Module service must use HTTPS")
        }
        self.config = configuration
        self.validate = validator
    }

    public func lastKnownGood() -> URL? {
        guard let state = readState() else { return nil }
        guard state.release >= config.minimumRelease else { return nil }
        let module = modules.appendingPathComponent("\(state.sha256).pvm")
        guard fileManager.fileExists(atPath: module.path),
              let size = fileSize(module),
              (1...Self.maximumModuleBytes).contains(size),
              (try? sha256(module)) == state.sha256
        else { return nil }
        try? fileManager.setAttributes(
            [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
            ofItemAtPath: module.path
        )
        return module
    }

    public func refresh(session: URLSession = .shared) async throws -> URL {
        do {
            return try await refreshStrict(session: session)
        } catch {
            if let cached = lastKnownGood() { return cached }
            throw error
        }
    }

    private func refreshStrict(session: URLSession) async throws -> URL {
        try fileManager.createDirectory(at: modules, withIntermediateDirectories: true)
        let previous = readState()
        let manifestURL =
            config.server
                .appendingPathComponent("v1")
                .appendingPathComponent("apps")
                .appendingPathComponent(config.applicationId)
                .appendingPathComponent(config.channel)
                .appendingPathComponent("ios")
                .appendingPathComponent(config.profile)
                .appendingPathComponent("manifest")
        var request = URLRequest(url: manifestURL, timeoutInterval: 15)
        request.cachePolicy = .reloadIgnoringLocalCacheData
        if let token = config.activationToken {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        let cached = lastKnownGood()
        if let previous, cached != nil,
           previous.release >= config.minimumRelease, !previous.etag.isEmpty {
            let etag = previous.etag
            request.setValue(etag, forHTTPHeaderField: "If-None-Match")
        }
        if let installationId = config.installationId {
            request.setValue(installationId, forHTTPHeaderField: "X-PVM-Installation-ID")
        }
        let (manifestData, response) = try await boundedData(for: request, session: session, maximum: 64 * 1024)
        guard let http = response as? HTTPURLResponse else {
            throw PVMHostError("Manifest response is not HTTP")
        }
        guard http.url == manifestURL else {
            throw PVMHostError("Manifest request was redirected")
        }
        if http.statusCode == 304 {
            guard let cached = lastKnownGood() else {
                throw PVMHostError("Server returned 304 without a cached module")
            }
            return cached
        }
        guard http.statusCode == 200 else {
            throw PVMHostError("Manifest request failed with HTTP \(http.statusCode)")
        }
        let envelope = try JSONDecoder().decode(SignedEnvelope.self, from: manifestData)
        guard envelope.envelopeFormat == 1,
              envelope.signatureAlgorithm == "Ed25519",
              let payload = Data(base64Encoded: envelope.payload),
              let signature = Data(base64Encoded: envelope.signature),
              PVMPlatformCrypto.verify(
                payload: payload,
                signature: signature,
                publicKeyPath: config.publicKeyPath
              )
        else { throw PVMHostError("Manifest signature verification failed") }
        let manifest = try JSONDecoder().decode(Manifest.self, from: payload)
        let releaseFloor = max(previous?.release ?? 0, config.minimumRelease)
        guard manifest.applicationId == config.applicationId,
              manifest.channel == config.channel,
              manifest.profile == config.profile,
              manifest.platform == "ios",
              manifest.release >= releaseFloor,
              Self.isSHA256(manifest.sha256),
              (1...Self.maximumModuleBytes).contains(manifest.size)
        else { throw PVMHostError("Manifest binding, release, hash, or size is invalid") }

        let destination = modules.appendingPathComponent("\(manifest.sha256).pvm")
        if fileManager.fileExists(atPath: destination.path),
           fileSize(destination) != manifest.size ||
            (try? sha256(destination)) != manifest.sha256 {
            try fileManager.removeItem(at: destination)
        }
        if !fileManager.fileExists(atPath: destination.path) {
            guard let moduleURL = URL(string: manifest.moduleURL, relativeTo: config.server)?.absoluteURL,
                  moduleURL.scheme == config.server.scheme,
                  moduleURL.host == config.server.host,
                  moduleURL.port == config.server.port,
                  moduleURL.path == "/v1/modules/\(manifest.sha256).pvm"
            else { throw PVMHostError("Manifest module URL changed origin or hash binding") }
            var moduleRequest = URLRequest(url: moduleURL, timeoutInterval: 30)
            if let token = config.activationToken {
                moduleRequest.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
            }
            let (moduleData, moduleResponse) =
                try await boundedData(
                    for: moduleRequest,
                    session: session,
                    maximum: manifest.size
                )
            guard let moduleHTTP = moduleResponse as? HTTPURLResponse,
                  moduleHTTP.statusCode == 200,
                  moduleHTTP.url == moduleURL,
                  moduleData.count == manifest.size
            else { throw PVMHostError("Module download was redirected, truncated, or rejected") }
            let temporary = modules.appendingPathComponent("\(manifest.sha256).tmp")
            try? fileManager.removeItem(at: temporary)
            try moduleData.write(to: temporary, options: .atomic)
            defer { try? fileManager.removeItem(at: temporary) }
            guard try sha256(temporary) == manifest.sha256
            else { throw PVMHostError("Module size or SHA-256 mismatch") }
            let release = try await validate(temporary, releaseFloor)
            guard release == manifest.release else {
                throw PVMHostError("Manifest/module release mismatch")
            }
            try fileManager.moveItem(at: temporary, to: destination)
            try fileManager.setAttributes(
                [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
                ofItemAtPath: destination.path
            )
        } else {
            let release = try await validate(destination, releaseFloor)
            guard release == manifest.release else {
                throw PVMHostError("Cached module release mismatch")
            }
        }

        let prior = previous?.history ?? []
        let history =
            ([manifest.sha256] + prior.filter {
                $0 != manifest.sha256 &&
                fileManager.fileExists(atPath: modules.appendingPathComponent("\($0).pvm").path)
            }).uniqued().prefix(2)
        let state =
            State(
                format: 1,
                applicationId: config.applicationId,
                channel: config.channel,
                platform: "ios",
                profile: config.profile,
                etag: http.value(forHTTPHeaderField: "ETag") ?? "",
                release: manifest.release,
                sha256: manifest.sha256,
                history: Array(history)
            )
        let encoded = try JSONEncoder().encode(state)
        try encoded.write(to: currentFile, options: [.atomic, .completeFileProtection])
        let keep = Set(state.history)
        for candidate in try fileManager.contentsOfDirectory(at: modules, includingPropertiesForKeys: nil)
        where candidate.pathExtension == "pvm" && !keep.contains(candidate.deletingPathExtension().lastPathComponent) {
            try? fileManager.removeItem(at: candidate)
        }
        return destination
    }

    private func readState() -> State? {
        guard let size = fileSize(currentFile),
              (1...Self.maximumStateBytes).contains(size),
              let data = try? Data(contentsOf: currentFile),
              let state = try? JSONDecoder().decode(State.self, from: data),
              state.format == 1,
              state.applicationId == config.applicationId,
              state.channel == config.channel,
              state.platform == "ios",
              state.profile == config.profile,
              state.release > 0,
              Self.isSHA256(state.sha256),
              !state.history.isEmpty,
              state.history.count <= 2,
              state.history.first == state.sha256,
              Set(state.history).count == state.history.count,
              state.history.allSatisfy(Self.isSHA256)
        else { return nil }
        return state
    }

    private func fileSize(_ file: URL) -> Int? {
        try? file.resourceValues(forKeys: [.fileSizeKey]).fileSize
    }

    private func boundedData(
        for request: URLRequest,
        session: URLSession,
        maximum: Int
    ) async throws -> (Data, URLResponse) {
        let (bytes, response) = try await session.bytes(
            for: request,
            delegate: redirectRejector
        )
        var data = Data()
        data.reserveCapacity(min(maximum, 16 * 1024))
        for try await byte in bytes {
            guard data.count < maximum else { throw PVMHostError("Response exceeds its size budget") }
            data.append(byte)
        }
        return (data, response)
    }

    private func sha256(_ file: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: file)
        defer { try? handle.close() }
        var hasher = SHA256()
        while true {
            let chunk = try handle.read(upToCount: 16 * 1024) ?? Data()
            if chunk.isEmpty { break }
            hasher.update(data: chunk)
        }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }

    private var modules: URL { config.root.appendingPathComponent("modules", isDirectory: true) }
    private var currentFile: URL { config.root.appendingPathComponent("current.json") }

    private struct Manifest: Decodable {
        let applicationId: String
        let channel: String
        let profile: String
        let platform: String
        let release: UInt64
        let sha256: String
        let size: Int
        let moduleURL: String

        enum CodingKeys: String, CodingKey {
            case applicationId = "application_id"
            case channel, profile, platform, release, sha256, size
            case moduleURL = "module_url"
        }
    }

    private struct SignedEnvelope: Decodable {
        let envelopeFormat: Int
        let payload: String
        let signature: String
        let signatureAlgorithm: String

        enum CodingKeys: String, CodingKey {
            case envelopeFormat = "envelope_format"
            case payload, signature
            case signatureAlgorithm = "signature_algorithm"
        }
    }

    private struct State: Codable {
        let format: Int
        let applicationId: String
        let channel: String
        let platform: String
        let profile: String
        let etag: String
        let release: UInt64
        let sha256: String
        let history: [String]

        enum CodingKeys: String, CodingKey {
            case format
            case applicationId = "application_id"
            case channel, platform, profile, etag, release, sha256, history
        }
    }

    private static let profiles = [
        "offline_sealed",
        "online_provisioned",
        "store_on_demand",
        "enterprise_managed",
    ]
    private static let maximumModuleBytes = 16 * 1024 * 1024
    private static let maximumStateBytes = 16 * 1024

    private static func isSegment(_ value: String) -> Bool {
        let bytes = value.utf8
        return !bytes.isEmpty && bytes.count <= 255 &&
            bytes.allSatisfy {
                ($0 >= 48 && $0 <= 57) || ($0 >= 65 && $0 <= 90) ||
                ($0 >= 97 && $0 <= 122) || $0 == 46 || $0 == 95 || $0 == 45
            }
    }

    private static func isSHA256(_ value: String) -> Bool {
        let bytes = value.utf8
        return bytes.count == 64 &&
            bytes.allSatisfy { ($0 >= 48 && $0 <= 57) || ($0 >= 97 && $0 <= 102) }
    }
}

private extension Sequence where Element: Hashable {
    func uniqued() -> [Element] {
        var seen = Set<Element>()
        return filter { seen.insert($0).inserted }
    }
}

private final class PVMRedirectRejector: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
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
