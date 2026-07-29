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
  constructor(
    private host: ArkUiViewHost,
    private factory: ArkUiNodeFactory,
  ) {}

  replaceTree(
    root: UiNode,
    emit: (nodeId: number, event: string, value?: string) => void,
  ): void {
    this.host.replace(this.render(root, emit))
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
}
