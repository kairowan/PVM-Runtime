import { common } from '@kit.AbilityKit'
import { preferences } from '@kit.ArkData'
import { UIContext } from '@kit.ArkUI'
import { CapabilityArgument, CapabilityRegistry } from './PvmRuntimeHost'

function stringArgument(argumentsValue: CapabilityArgument[], index: number): string {
  const value = argumentsValue[index]
  if (typeof value !== 'string') {
    throw new Error(`Capability argument ${index} must be a string`)
  }
  return value
}

export function installBasicHarmonyCapabilities(
  registry: CapabilityRegistry,
  context: common.Context,
  uiContext: UIContext,
  preferenceName: string = 'pvm.runtime.preferences',
): void {
  const store = preferences.getPreferencesSync(context, { name: preferenceName })

  registry.registerSync('ui.toast', (operation, argumentsValue): string => {
    if (operation !== 'show' || argumentsValue.length !== 1) {
      throw new Error('Invalid ui.toast call')
    }
    uiContext.getPromptAction().showToast({
      message: stringArgument(argumentsValue, 0),
      duration: 4000,
    })
    return 'ok'
  })

  registry.registerAsync('storage.kv', async (operation, argumentsValue): Promise<string> => {
    if (!registry.policy?.storageScopes.includes('app.preferences')) {
      throw new Error('Signed module did not declare app.preferences')
    }
    const key = stringArgument(argumentsValue, 0)
    switch (operation) {
      case 'get': {
        const value = store.getSync(key, 'Not set')
        return typeof value === 'string' ? value : `${value}`
      }
      case 'set':
        store.putSync(key, stringArgument(argumentsValue, 1))
        store.flushSync()
        return 'ok'
      case 'remove':
        store.deleteSync(key)
        store.flushSync()
        return 'ok'
      default:
        throw new Error(`Unsupported storage.kv operation ${operation}`)
    }
  })
}
