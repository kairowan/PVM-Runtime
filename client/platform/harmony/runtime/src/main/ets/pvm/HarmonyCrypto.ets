import { cryptoFramework } from '@kit.CryptoArchitectureKit'
import { fileIo as fs } from '@kit.CoreFileKit'
import { SignatureVerifier } from './PvmRuntimeHost'

export class HarmonyEd25519Verifier implements SignatureVerifier {
  verify(payload: ArrayBuffer, signature: ArrayBuffer, publicKeyPath: string): boolean {
    const generator = cryptoFramework.createAsyKeyGenerator('Ed25519')
    const keyPair = generator.convertPemKeySync(fs.readTextSync(publicKeyPath), null)
    const verifier = cryptoFramework.createVerify('Ed25519')
    verifier.initSync(keyPair.pubKey)
    return verifier.verifySync(
      { data: new Uint8Array(payload) },
      { data: new Uint8Array(signature) },
    )
  }
}
