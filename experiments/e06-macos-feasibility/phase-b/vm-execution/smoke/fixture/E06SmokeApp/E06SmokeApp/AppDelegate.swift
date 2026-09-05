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
        let (previousKeychain, previousKeychainStatus) = readKeychainName()
        let previousFile = readMarkerFile()

        defaults.set(namespace, forKey: "taskflow-e06-namespace")
        let keychainWrite = writeKeychainName(namespace)
        writeMarkerFile(namespace)

        emit([
            "namespace": namespace,
            "previous_default": previousDefault ?? "",
            "previous_file": previousFile ?? "",
            "previous_keychain_name": previousKeychain ?? "",
            "previous_keychain_status": Int(previousKeychainStatus),
            "delete_keychain_status": Int(keychainWrite.deleteStatus),
            "add_keychain_status": Int(keychainWrite.addStatus),
            "verify_keychain_status": Int(keychainWrite.verifyStatus),
            "verified_keychain_name": keychainWrite.verifiedName ?? "",
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

    private func readKeychainName() -> (String?, OSStatus) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "taskflow-e06-canary",
            kSecAttrAccount as String: "namespace-name",
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        guard status == errSecSuccess,
              let data = result as? Data else { return (nil, status) }
        return (String(data: data, encoding: .utf8), status)
    }

    private func writeKeychainName(_ namespace: String) -> (
        deleteStatus: OSStatus,
        addStatus: OSStatus,
        verifiedName: String?,
        verifyStatus: OSStatus
    ) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "taskflow-e06-canary",
            kSecAttrAccount as String: "namespace-name"
        ]
        let deleteStatus = SecItemDelete(query as CFDictionary)
        var item = query
        item[kSecValueData as String] = Data(namespace.utf8)
        let addStatus = SecItemAdd(item as CFDictionary, nil)
        let (verifiedName, verifyStatus) = readKeychainName()
        return (deleteStatus, addStatus, verifiedName, verifyStatus)
    }

    private func emit(_ value: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]),
              let json = String(data: data, encoding: .utf8) else { return }
        print("TASKFLOW_E06_RESULT:\(json)")
    }
}
