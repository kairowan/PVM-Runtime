import { UIAbility } from '@kit.AbilityKit'
import { hilog } from '@kit.PerformanceAnalysisKit'
import { window } from '@kit.ArkUI'

const DOMAIN = 0x5056
const TAG = 'PVMRuntimeDemo'

export default class EntryAbility extends UIAbility {
  onWindowStageCreate(windowStage: window.WindowStage): void {
    windowStage.loadContent('pages/Index', (error) => {
      if (error.code) {
        hilog.error(
          DOMAIN,
          TAG,
          'Failed to load PVM Runtime page: %{public}s',
          JSON.stringify(error),
        )
      }
    })
  }
}
