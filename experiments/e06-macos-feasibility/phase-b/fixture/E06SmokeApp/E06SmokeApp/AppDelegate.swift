import Foundation
import Security
import UIKit
import Darwin

@main
final class AppDelegate: UIResponder, UIApplicationDelegate {
    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        let arguments = ProcessInfo.processInfo.arguments
        guard let flag = arguments.firstIndex(of: "--taskflow-namespace"), flag + 1 < arguments.count else {
            emit(["status": "invalid", "reason": "missing-namespace"])
            exit(2)
        }

        let namespace = arguments[flag + 1]
        let defaults = UserDefaults.standard
        let previousDefault = defaults.string(forKey: "taskflow-e06-namespace")
        let previousKeychain = readKeychainName()
        let previousFile = readMarkerFile()

        defaults.set(namespace, forKey: "taskflow-e06-namespace")
        writeKeychainName(namespace)
        writeMarkerFile(namespace)

        emit([
            "namespace": namespace,
            "previous_default": previousDefault ?? "",
            "previous_file": previousFile ?? "",
            "previous_keychain_name": previousKeychain ?? "",
            "status": "ok"
        ])
        fflush(stdout)
        exit(0)
    }

    private func markerURL() -> URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("taskflow-e06-marker.txt")
    }

    private func readMarkerFile() -> String? {
        try? String(contentsOf: markerURL(), encoding: .utf8)
    }

    private func writeMarkerFile(_ namespace: String) {
        try? namespace.write(to: markerURL(), atomically: true, encoding: .utf8)
    }

    private func readKeychainName() -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "taskflow-e06-canary",
            kSecAttrAccount as String: "namespace-name",
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private func writeKeychainName(_ namespace: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "taskflow-e06-canary",
            kSecAttrAccount as String: "namespace-name"
        ]
        SecItemDelete(query as CFDictionary)
        var item = query
        item[kSecValueData as String] = Data(namespace.utf8)
        SecItemAdd(item as CFDictionary, nil)
    }

    private func emit(_ value: [String: String]) {
        guard let data = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]),
              let json = String(data: data, encoding: .utf8) else { return }
        print("TASKFLOW_E06_RESULT:\(json)")
    }
}
