import { PvmRenderedNode, PvmRuntimeSession } from './PvmRuntimeSession'
import { hilog } from '@kit.PerformanceAnalysisKit'

const DOMAIN = 0x5056
const TAG = 'PVMRuntimeTree'

class PvmTreeRenderState {
  root: PvmRenderedNode

  constructor(root: PvmRenderedNode) {
    this.root = root
  }
}

@Component
export struct PvmRuntimeTree {
  session: PvmRuntimeSession | undefined = undefined
  @State private renderState: PvmTreeRenderState | null = null
  @State private errorMessage: string = ''
  @State private inputVersions: Map<number, number> = new Map()
  private focusedInputId: number = 0

  aboutToAppear(): void {
    try {
      if (this.session === undefined) {
        throw new Error('PVM Runtime session is required')
      }
      this.session.start(
        (root, changed, structureChanged) => {
          this.refreshInputVersions(root, changed, structureChanged)
          this.renderState = new PvmTreeRenderState(root)
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
    Column({ space: 14 }) {
      if (this.errorMessage.length > 0) {
        Text('PVM Runtime failed')
          .fontSize(22)
          .fontWeight(FontWeight.Bold)
          .fontColor('#B42318')
        Text(this.errorMessage)
          .fontSize(15)
          .fontColor('#B42318')
      } else if (this.renderState !== null) {
        this.renderNode(this.renderState.root, true)
      } else {
        LoadingProgress()
          .width(40)
          .height(40)
      }
    }
    .width('100%')
    .height('100%')
    .alignItems(HorizontalAlign.Start)
    .padding({ left: 20, right: 20, top: 20, bottom: 20 })
    .backgroundColor('#FFFFFF')
  }

  @Builder
  private renderChildren(node: PvmRenderedNode) {
    ForEach(
      node.children,
      (child: PvmRenderedNode) => {
        this.renderNode(child, false)
      },
      (child: PvmRenderedNode) => this.nodeKey(child),
    )
  }

  @Builder
  private renderNode(node: PvmRenderedNode, fillViewport: boolean) {
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
      .height(fillViewport ? '100%' : 'auto')
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
      .height(fillViewport ? '100%' : 'auto')
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
      .height(fillViewport ? '100%' : 'auto')
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
      .height(fillViewport ? '100%' : 'auto')
      .accessibilityText(node.model.props['accessibilityLabel'] ?? '')
      .onAppear(() => this.emit(node, 'appear'))
    } else if (node.model.type === 'List') {
      List({ space: 12 }) {
        Repeat<PvmRenderedNode>(node.children)
          .each((item: RepeatItem<PvmRenderedNode>) => {
            ListItem() {
              this.renderNode(item.item, false)
            }
          })
          .key((child: PvmRenderedNode) => this.nodeKey(child))
          .virtualScroll({ totalCount: node.children.length, reusable: true })
      }
      .id(`pvm-node-${node.model.id}`)
      .width('100%')
      .height(fillViewport ? '100%' : 'auto')
      .layoutWeight(1)
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
    return `${node.model.type}:${node.model.id}:${node.revision}`
  }

  private refreshInputVersions(
    root: PvmRenderedNode,
    changed: PvmRenderedNode[],
    structureChanged: boolean,
  ): void {
    const versions = new Map(this.inputVersions)
    let focusedInputVisible = false
    let versionsChanged = false
    const visit = (node: PvmRenderedNode, includeChildren: boolean): void => {
      if (node.model.type === 'Input' && node.model.id === this.focusedInputId) {
        focusedInputVisible = true
      }
      if (
        node.model.type === 'Input' &&
        node.model.id !== this.focusedInputId &&
        versions.get(node.model.id) !== node.revision
      ) {
        versions.set(node.model.id, node.revision)
        versionsChanged = true
      }
      if (includeChildren) node.children.forEach((child) => visit(child, true))
    }
    if (structureChanged) {
      visit(root, true)
      if (!focusedInputVisible) this.focusedInputId = 0
    } else {
      changed.forEach((node) => visit(node, node.model.type === 'List'))
    }
    if (versionsChanged) this.inputVersions = versions
  }

  private bumpInputVersion(nodeId: number): void {
    const versions = new Map(this.inputVersions)
    versions.set(nodeId, (versions.get(nodeId) ?? 0) + 1)
    this.inputVersions = versions
  }
}
