import { UiNode, UiRenderer } from './PvmRuntimeHost'

export interface ArkUiViewHost {
  replace(root: object): void
}

export interface ArkUiNodeFactory {
  create(
    node: UiNode,
    children: object[],
    emit: (nodeId: number, event: string, value?: string) => void,
  ): object
}

export class ArkUiRenderer implements UiRenderer {
  private renderGeneration: number = 0
  private visibleNodeIds: Set<number> = new Set()
  private appearedNodeIds: Set<number> = new Set()
  private host: ArkUiViewHost
  private factory: ArkUiNodeFactory

  constructor(host: ArkUiViewHost, factory: ArkUiNodeFactory) {
    this.host = host
    this.factory = factory
  }

  replaceTree(
    root: UiNode,
    emit: (nodeId: number, event: string, value?: string) => void,
  ): void {
    this.renderGeneration += 1
    const generation = this.renderGeneration
    const nextVisible = this.collectIds(root)
    this.appearedNodeIds = new Set(
      Array.from(this.appearedNodeIds).filter((id) => nextVisible.has(id)),
    )
    this.visibleNodeIds = nextVisible
    const guardedEmit = (nodeId: number, event: string, value?: string): void => {
      if (generation !== this.renderGeneration || !this.visibleNodeIds.has(nodeId)) return
      if (event === 'appear') {
        if (this.appearedNodeIds.has(nodeId)) return
        this.appearedNodeIds.add(nodeId)
      }
      emit(nodeId, event, value)
    }
    this.host.replace(this.render(root, guardedEmit))
  }

  private render(
    node: UiNode,
    emit: (nodeId: number, event: string, value?: string) => void,
  ): object {
    const supported = [
      'Text', 'Image', 'Row', 'Column', 'Stack', 'Scroll',
      'List', 'Button', 'Input', 'Switch', 'NativeSurface',
    ]
    if (!supported.includes(node.type)) throw new Error(`Unsupported VM node type ${node.type}`)
    return this.factory.create(node, node.children.map((child) => this.render(child, emit)), emit)
  }

  private collectIds(root: UiNode): Set<number> {
    const result: Set<number> = new Set()
    const visit = (node: UiNode): void => {
      result.add(node.id)
      node.children.forEach(visit)
    }
    visit(root)
    return result
  }
}
