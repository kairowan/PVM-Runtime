import PVMRuntime
import UIKit

@main
@MainActor
final class AppDelegate: UIResponder, UIApplicationDelegate {
    func application(
        _ application: UIApplication,
        configurationForConnecting connectingSceneSession: UISceneSession,
        options: UIScene.ConnectionOptions
    ) -> UISceneConfiguration {
        UISceneConfiguration(
            name: "Default Configuration",
            sessionRole: connectingSceneSession.role
        )
    }
}

@MainActor
final class SceneDelegate: UIResponder, UIWindowSceneDelegate {
    var window: UIWindow?
    private var demo: DemoViewController?

    func scene(
        _ scene: UIScene,
        willConnectTo session: UISceneSession,
        options connectionOptions: UIScene.ConnectionOptions
    ) {
        guard let windowScene = scene as? UIWindowScene else { return }
        let window = UIWindow(windowScene: windowScene)
        let demo = DemoViewController()
        window.rootViewController = demo
        window.makeKeyAndVisible()
        self.window = window
        self.demo = demo
    }

    func sceneDidEnterBackground(_ scene: UIScene) {
        demo?.persistState()
    }

    func sceneDidDisconnect(_ scene: UIScene) {
        demo?.persistState()
        demo?.close()
        demo = nil
        window = nil
    }
}

@MainActor
final class DemoViewController: UIViewController {
    private let runtimeView = UIView()
    private var host: PVMHost?
    private var pushInbox: PVMPushInbox?

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .systemBackground
        runtimeView.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(runtimeView)
        NSLayoutConstraint.activate([
            runtimeView.leadingAnchor.constraint(
                equalTo: view.safeAreaLayoutGuide.leadingAnchor,
                constant: 20
            ),
            runtimeView.trailingAnchor.constraint(
                equalTo: view.safeAreaLayoutGuide.trailingAnchor,
                constant: -20
            ),
            runtimeView.topAnchor.constraint(
                equalTo: view.safeAreaLayoutGuide.topAnchor,
                constant: 20
            ),
            runtimeView.bottomAnchor.constraint(
                lessThanOrEqualTo: view.safeAreaLayoutGuide.bottomAnchor,
                constant: -20
            ),
        ])

        do {
            try startRuntime()
        } catch {
            showError(error)
        }
    }

    func persistState() {
        guard let host, let stateURL = try? stateURL() else { return }
        do {
            try host.snapshotState().write(to: stateURL, options: [.atomic, .completeFileProtection])
        } catch {
            showError(error)
        }
    }

    func close() {
        host?.close()
        host = nil
        pushInbox = nil
    }

    private func startRuntime() throws {
        let bootstrapURL = try resource("bootstrap", extension: "json")
        let bootstrapData = try Data(contentsOf: bootstrapURL)
        guard let bootstrap = try JSONSerialization.jsonObject(with: bootstrapData) as? [String: Any],
              bootstrap["platform"] as? String == "ios",
              bootstrap["profile"] as? String == "offline_sealed",
              bootstrap["mode"] as? String == "bundled",
              let applicationID = bootstrap["applicationId"] as? String,
              applicationID == Bundle.main.bundleIdentifier,
              let channel = bootstrap["channel"] as? String,
              let profile = bootstrap["profile"] as? String,
              let release = (bootstrap["release"] as? NSNumber)?.uint64Value
        else {
            throw PVMHostError("Demo bootstrap does not match the iOS Offline Sealed app")
        }

        if screenshotToken != nil {
            UserDefaults.standard.removeObject(forKey: "status")
            try? FileManager.default.removeItem(at: screenshotMarkerURL)
        }
        if restoredStateToken != nil {
            try? FileManager.default.removeItem(at: restoredStateMarkerURL)
        }

        let registry = PVMCapabilityRegistry()
        let pushInbox = PVMBasicCapabilities.install(registry: registry, presenting: self)
        let renderer = PVMUIKitRenderer(root: runtimeView)
        let host = try PVMHost(
            module: resource("module", extension: "pvm"),
            publicKey: resource("module-public-key", extension: "pem"),
            applicationID: applicationID,
            channel: channel,
            profile: profile,
            minimumRelease: release,
            capabilities: registry,
            renderer: renderer,
            errors: { [weak self] error in self?.showError(error) }
        )
        do {
            if let stateURL = try? stateURL(), FileManager.default.fileExists(atPath: stateURL.path) {
                do {
                    try host.restoreState(Data(contentsOf: stateURL))
                } catch {
                    try? FileManager.default.removeItem(at: stateURL)
                }
            }
            try host.start()
            self.host = host
            self.pushInbox = pushInbox
            seedScreenshotStateIfRequested()
            verifyRestoredStateIfRequested()
        } catch {
            host.close()
            throw error
        }
    }

    private func resource(_ name: String, extension fileExtension: String) throws -> URL {
        guard let url = Bundle.main.url(forResource: name, withExtension: fileExtension) else {
            throw PVMHostError("Missing bundled resource \(name).\(fileExtension)")
        }
        return url
    }

    private func stateURL() throws -> URL {
        let root = try FileManager.default.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )
        return root.appendingPathComponent("counter.state")
    }

    private func showError(_ error: Error) {
        runtimeView.subviews.forEach { $0.removeFromSuperview() }
        let label = UILabel()
        label.numberOfLines = 0
        label.textColor = .systemRed
        label.text = "PVM Runtime failed:\n\(error.localizedDescription)"
        label.translatesAutoresizingMaskIntoConstraints = false
        runtimeView.addSubview(label)
        NSLayoutConstraint.activate([
            label.leadingAnchor.constraint(equalTo: runtimeView.leadingAnchor),
            label.trailingAnchor.constraint(equalTo: runtimeView.trailingAnchor),
            label.topAnchor.constraint(equalTo: runtimeView.topAnchor),
        ])
    }

    private func seedScreenshotStateIfRequested() {
        guard screenshotToken != nil else { return }
        perform(#selector(seedFirstIncrement), with: nil, afterDelay: 0.25)
    }

    @objc private func seedFirstIncrement() {
        guard tapButton("Increment") else { return }
        perform(#selector(seedSecondIncrement), with: nil, afterDelay: 0.15)
    }

    @objc private func seedSecondIncrement() {
        guard tapButton("Increment") else { return }
        perform(#selector(seedName), with: nil, afterDelay: 0.15)
    }

    @objc private func seedName() {
        guard let input = runtimeView.pvmDescendants.compactMap({ $0 as? UITextField }).first else {
            return
        }
        input.text = "Alice"
        input.sendActions(for: .editingChanged)
        perform(#selector(seedAsyncStorage), with: nil, afterDelay: 0.15)
    }

    @objc private func seedAsyncStorage() {
        guard let screenshotToken, tapButton("Load async storage") else { return }
        waitForExpectedState(
            token: screenshotToken,
            markerURL: screenshotMarkerURL,
            attemptsRemaining: 100
        )
    }

    private func verifyRestoredStateIfRequested() {
        guard let restoredStateToken else { return }
        waitForExpectedState(
            token: restoredStateToken,
            markerURL: restoredStateMarkerURL,
            attemptsRemaining: 100
        )
    }

    private func waitForExpectedState(
        token: String,
        markerURL: URL,
        attemptsRemaining: Int
    ) {
        guard attemptsRemaining > 0 else { return }
        let descendants = runtimeView.pvmDescendants
        let labels = Set(descendants.compactMap { ($0 as? UILabel)?.text })
        let name = descendants.compactMap { ($0 as? UITextField)?.text }.first
        if labels.contains("Protected counter: 2"),
           labels.contains("Status: Not set"),
           name == "Alice" {
            try? Data(token.utf8).write(to: markerURL, options: .atomic)
            return
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { [weak self] in
            self?.waitForExpectedState(
                token: token,
                markerURL: markerURL,
                attemptsRemaining: attemptsRemaining - 1
            )
        }
    }

    private var screenshotToken: String? {
        processArgument(after: "-PVMSeedScreenshotToken")
    }

    private var restoredStateToken: String? {
        processArgument(after: "-PVMVerifyRestoredStateToken")
    }

    private func processArgument(after flag: String) -> String? {
        let arguments = ProcessInfo.processInfo.arguments
        guard let index = arguments.firstIndex(of: flag),
              arguments.indices.contains(index + 1),
              !arguments[index + 1].isEmpty
        else {
            return nil
        }
        return arguments[index + 1]
    }

    private var screenshotMarkerURL: URL {
        FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("pvm-screenshot-ready")
    }

    private var restoredStateMarkerURL: URL {
        FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("pvm-state-restored")
    }

    @discardableResult
    private func tapButton(_ title: String) -> Bool {
        let button = runtimeView.pvmDescendants
            .compactMap { $0 as? UIButton }
            .first(where: { $0.title(for: .normal) == title })
        guard let button else { return false }
        button.sendActions(for: .touchUpInside)
        return true
    }
}

private extension UIView {
    var pvmDescendants: [UIView] {
        subviews + subviews.flatMap(\.pvmDescendants)
    }
}
