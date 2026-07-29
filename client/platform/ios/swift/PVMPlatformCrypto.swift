import CryptoKit
import Foundation

public enum PVMPlatformCrypto {
    public static func verify(
        payload: Data,
        signature: Data,
        publicKeyPath: String
    ) -> Bool {
        guard signature.count == 64,
              let pem = try? String(contentsOfFile: publicKeyPath, encoding: .utf8),
              let der = Data(
                base64Encoded: pem
                    .split(whereSeparator: \.isNewline)
                    .filter { !$0.hasPrefix("-----") }
                    .joined()
              ),
              der.count == subjectPublicKeyInfoPrefix.count + 32,
              der.starts(with: subjectPublicKeyInfoPrefix),
              let key = try? Curve25519.Signing.PublicKey(
                rawRepresentation: der.dropFirst(subjectPublicKeyInfoPrefix.count)
              )
        else { return false }
        return key.isValidSignature(signature, for: payload)
    }

    private static let subjectPublicKeyInfoPrefix =
        Data([0x30, 0x2a, 0x30, 0x05, 0x06, 0x03, 0x2b, 0x65, 0x70, 0x03, 0x21, 0x00])
}
