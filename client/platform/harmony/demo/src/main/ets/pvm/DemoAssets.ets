import { common } from '@kit.AbilityKit'
import { util } from '@kit.ArkTS'
import { fileIo as fs } from '@kit.CoreFileKit'
import { PvmRuntimeSession } from '@pvm/runtime'

interface DemoBootstrap {
  applicationId: string
  channel: string
  mode: string
  platform: string
  profile: string
  release: number
  publicKey: string
}

function writeAsset(context: common.Context, name: string): string {
  const content = context.resourceManager.getRawFileContentSync(name)
  const path = `${context.filesDir}/${name}`
  const file = fs.openSync(
    path,
    fs.OpenMode.CREATE | fs.OpenMode.WRITE_ONLY | fs.OpenMode.TRUNC,
  )
  try {
    if (fs.writeSync(file.fd, content.buffer) !== content.byteLength) {
      throw new Error(`Short write for rawfile ${name}`)
    }
  } finally {
    fs.closeSync(file)
  }
  return path
}

export function createDemoSession(context: common.UIAbilityContext): PvmRuntimeSession {
  const bootstrapBytes = context.resourceManager.getRawFileContentSync('bootstrap.json')
  const bootstrap = JSON.parse(
    util.TextDecoder.create().decodeToString(bootstrapBytes),
  ) as DemoBootstrap
  if (
    bootstrap.applicationId !== 'com.example.protected' ||
    bootstrap.applicationId !== context.applicationInfo.name ||
    bootstrap.channel !== 'enterprise' ||
    bootstrap.mode !== 'bundled' ||
    bootstrap.platform !== 'harmonyos' ||
    bootstrap.profile !== 'offline_sealed' ||
    bootstrap.release !== 5 ||
    bootstrap.publicKey !== 'module-public-key.pem'
  ) {
    throw new Error('Demo bootstrap does not match the HarmonyOS Offline Sealed app')
  }

  const modulePath = writeAsset(context, 'module.pvm')
  const publicKeyPath = writeAsset(context, bootstrap.publicKey)
  return new PvmRuntimeSession({
    context: context,
    modulePath: modulePath,
    publicKeyPath: publicKeyPath,
    statePath: `${context.filesDir}/counter.state`,
    applicationId: bootstrap.applicationId,
    channel: bootstrap.channel,
    profile: bootstrap.profile,
    minimumRelease: bootstrap.release,
    preferenceName: 'pvm.runtime.demo.preferences',
  })
}
