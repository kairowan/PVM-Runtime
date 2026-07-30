import { PvmRenderedNode, PvmRuntimeSession } from './PvmRuntimeSession'
import { hilog } from '@kit.PerformanceAnalysisKit'

const DOMAIN = 0x5056
const TAG = 'PVMRuntimeTree'

@Component
export struct PvmRuntimeTree {
  session: PvmRuntimeSession | undefined = undefined
  @State private root: PvmRenderedNode | null = null
  @State private errorMessage: string = ''
  @State private revision: number = 0
  @State private inputVersions: Map<number, number> = new Map()
  private focusedInputId: number = 0

  aboutToAppear(): void {
    try {
      if (this.session === undefined) {
        throw new Error('PVM Runtime session is required')
      }
      this.session.start(
        (root) => {
          this.refreshInputVersions(root)
          this.revision += 1
          this.root = root
        },
        this.getUIContext(),
      )
    } catch (error) {
      this.errorMessage = `${error}`
    }
  }

  aboutToDisappear(): void {
    try {
      this.session?.close()
    } catch (error) {
      hilog.error(DOMAIN, TAG, 'Failed to persist PVM state: %{public}s', `${error}`)
    }
  }

  build() {
    Scroll() {
      Column({ space: 14 }) {
        if (this.errorMessage.length > 0) {
          Text('PVM Runtime failed')
            .fontSize(22)
            .fontWeight(FontWeight.Bold)
            .fontColor('#B42318')
          Text(this.errorMessage)
            .fontSize(15)
            .fontColor('#B42318')
        } else if (this.root !== null) {
          this.renderNode(this.root)
        } else {
          LoadingProgress()
            .width(40)
            .height(40)
        }
      }
      .width('100%')
      .alignItems(HorizontalAlign.Start)
      .padding({ left: 20, right: 20, top: 20, bottom: 20 })
    }
    .width('100%')
    .height('100%')
    .backgroundColor('#FFFFFF')
  }

  @Builder
  private renderChildren(node: PvmRenderedNode) {
    ForEach(
      node.children,
      (child: PvmRenderedNode) => {
        this.renderNode(child)
      },
      (child: PvmRenderedNode) => this.nodeKey(child),
    )
  }

  @Builder
  private renderNode(node: PvmRenderedNode) {
    if (node.model.type === 'Text') {
      Text(node.model.props['text'] ?? '')
        .id(`pvm-node-${node.model.id}`)
        .fontSize(22)
        .fontColor('#111827')
        .width('100%')
        .accessibilityText(
          node.model.props['accessibilityLabel'] ?? node.model.props['text'] ?? '',
        )
        .onClick(() => this.emit(node, 'tap'))
        .onAppear(() => this.emit(node, 'appear'))
    } else if (node.model.type === 'Button') {
      Button(node.model.props['text'] ?? '')
        .id(`pvm-node-${node.model.id}`)
        .fontSize(18)
        .fontColor('#111827')
        .width('100%')
        .height(54)
        .backgroundColor('#F0F2F5')
        .borderRadius(14)
        .enabled(node.model.props['enabled'] !== 'false')
        .accessibilityText(
          node.model.props['accessibilityLabel'] ?? node.model.props['text'] ?? '',
        )
        .onClick(() => this.emit(node, 'tap'))
        .onAppear(() => this.emit(node, 'appear'))
    } else if (node.model.type === 'Input') {
      TextInput({
        placeholder: node.model.props['text'] ?? '',
        text: node.model.props['value'] ?? '',
      })
        .id(`pvm-node-${node.model.id}`)
        .fontSize(18)
        .fontColor('#111827')
        .placeholderColor('#667085')
        .width('100%')
        .height(52)
        .backgroundColor('#FFFFFF')
        .border({ width: 1, color: '#D0D5DD', radius: 10 })
        .enabled(node.model.props['enabled'] !== 'false')
        .accessibilityText(
          node.model.props['accessibilityLabel'] ?? node.model.props['text'] ?? '',
        )
        .onFocus(() => {
          this.focusedInputId = node.model.id
        })
        .onBlur(() => {
          if (this.focusedInputId === node.model.id) this.focusedInputId = 0
          this.bumpInputVersion(node.model.id)
        })
        .onChange((value: string) => this.emit(node, 'change', value))
        .onSubmit(() => this.emit(node, 'submit', node.model.props['value'] ?? ''))
        .onAppear(() => this.emit(node, 'appear'))
    } else if (node.model.type === 'Row') {
      Row({ space: 12 }) {
        this.renderChildren(node)
      }
      .id(`pvm-node-${node.model.id}`)
      .width('100%')
      .alignItems(VerticalAlign.Center)
      .accessibilityText(node.model.props['accessibilityLabel'] ?? '')
      .onClick(() => this.emit(node, 'tap'))
      .onAppear(() => this.emit(node, 'appear'))
    } else if (node.model.type === 'Column') {
      Column({ space: 14 }) {
        this.renderChildren(node)
      }
      .id(`pvm-node-${node.model.id}`)
      .width('100%')
      .alignItems(HorizontalAlign.Start)
      .accessibilityText(node.model.props['accessibilityLabel'] ?? '')
      .onClick(() => this.emit(node, 'tap'))
      .onAppear(() => this.emit(node, 'appear'))
    } else if (node.model.type === 'Stack') {
      Stack() {
        this.renderChildren(node)
      }
      .id(`pvm-node-${node.model.id}`)
      .width('100%')
      .accessibilityText(node.model.props['accessibilityLabel'] ?? '')
      .onClick(() => this.emit(node, 'tap'))
      .onAppear(() => this.emit(node, 'appear'))
    } else if (node.model.type === 'Scroll') {
      Scroll() {
        Column({ space: 14 }) {
          this.renderChildren(node)
        }
        .width('100%')
      }
      .id(`pvm-node-${node.model.id}`)
      .width('100%')
      .accessibilityText(node.model.props['accessibilityLabel'] ?? '')
      .onAppear(() => this.emit(node, 'appear'))
    } else if (node.model.type === 'List') {
      List({ space: 12 }) {
        ForEach(
          node.children,
          (child: PvmRenderedNode) => {
            ListItem() {
              this.renderNode(child)
            }
          },
          (child: PvmRenderedNode) => this.nodeKey(child),
        )
      }
      .id(`pvm-node-${node.model.id}`)
      .width('100%')
      .accessibilityText(node.model.props['accessibilityLabel'] ?? '')
      .onAppear(() => this.emit(node, 'appear'))
    } else if (node.model.type === 'Switch') {
      Toggle({
        type: ToggleType.Switch,
        isOn: node.model.props['value'] === 'true',
      })
        .id(`pvm-node-${node.model.id}`)
        .enabled(node.model.props['enabled'] !== 'false')
        .accessibilityText(node.model.props['accessibilityLabel'] ?? '')
        .onChange((value: boolean) => this.emit(node, 'change', `${value}`))
        .onAppear(() => this.emit(node, 'appear'))
    } else if (node.model.type === 'Image') {
      if (this.isLocalImageSource(node.model.props['source'] ?? '')) {
        Image(node.model.props['source'])
          .id(`pvm-node-${node.model.id}`)
          .objectFit(ImageFit.Contain)
          .width('100%')
          .accessibilityText(node.model.props['accessibilityLabel'] ?? '')
          .onClick(() => this.emit(node, 'tap'))
          .onAppear(() => this.emit(node, 'appear'))
      } else {
        Text('Blocked image source')
          .id(`pvm-node-${node.model.id}`)
          .fontSize(16)
          .fontColor('#B42318')
          .width('100%')
          .accessibilityText(node.model.props['accessibilityLabel'] ?? '')
          .onClick(() => this.emit(node, 'tap'))
          .onAppear(() => this.emit(node, 'appear'))
      }
    } else {
      Text(`NativeSurface: ${node.model.props['surfaceType'] ?? 'unregistered'}`)
        .id(`pvm-node-${node.model.id}`)
        .fontSize(16)
        .fontColor('#667085')
        .width('100%')
        .accessibilityText(node.model.props['accessibilityLabel'] ?? '')
        .onClick(() => this.emit(node, 'tap'))
        .onAppear(() => this.emit(node, 'appear'))
    }
  }

  private emit(node: PvmRenderedNode, event: string, value?: string): void {
    if (node.model.events.includes(event)) {
      node.emit(node.model.id, event, value)
    }
  }

  private isLocalImageSource(source: string): boolean {
    if (
      source.length < 1 ||
      source.length > 256 ||
      source.startsWith('/') ||
      source.includes(':') ||
      source.includes('\\')
    ) {
      return false
    }
    return source.split('/').every((segment) => {
      return segment.length > 0 && segment !== '.' && segment !== '..'
    })
  }

  private nodeKey(node: PvmRenderedNode): string {
    if (node.model.type === 'Input') {
      return `input:${node.model.id}:${this.inputVersions.get(node.model.id) ?? 0}`
    }
    if (node.containsInput) {
      return `input-tree:${node.model.type}:${node.model.id}`
    }
    // ponytail: a VM replace batch is authoritative; rebuild its non-input
    // subtree in O(n). Move to observed-node diffing only when profiling needs it.
    return `${this.revision}:${node.model.id}`
  }

  private refreshInputVersions(root: PvmRenderedNode): void {
    const versions = new Map(this.inputVersions)
    let focusedInputVisible = false
    const visit = (node: PvmRenderedNode): void => {
      if (node.model.type === 'Input' && node.model.id === this.focusedInputId) {
        focusedInputVisible = true
      }
      if (node.model.type === 'Input' && node.model.id !== this.focusedInputId) {
        versions.set(node.model.id, (versions.get(node.model.id) ?? 0) + 1)
      }
      node.children.forEach(visit)
    }
    visit(root)
    if (!focusedInputVisible) this.focusedInputId = 0
    this.inputVersions = versions
  }

  private bumpInputVersion(nodeId: number): void {
    const versions = new Map(this.inputVersions)
    versions.set(nodeId, (versions.get(nodeId) ?? 0) + 1)
    this.inputVersions = versions
  }
}
