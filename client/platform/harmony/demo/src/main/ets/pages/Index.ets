import { common } from '@kit.AbilityKit'
import { hilog } from '@kit.PerformanceAnalysisKit'
import { PvmRuntimeSession, PvmRuntimeTree } from '@pvm/runtime'
import { createDemoSession } from '../pvm/DemoAssets'

const DOMAIN = 0x5056
const TAG = 'PVMRuntimeDemo'

@Entry
@Component
struct Index {
  private readonly session: PvmRuntimeSession =
    createDemoSession(getContext(this) as common.UIAbilityContext)

  onPageHide(): void {
    try {
      this.session.persist()
    } catch (error) {
      hilog.error(DOMAIN, TAG, 'Failed to persist PVM state: %{public}s', `${error}`)
    }
  }

  build() {
    Column() {
      PvmRuntimeTree({
        session: this.session,
      })
    }
    .width('100%')
    .height('100%')
  }
}
