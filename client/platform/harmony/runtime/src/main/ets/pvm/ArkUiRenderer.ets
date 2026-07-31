import type { UiBatch, UiNode, UiRenderer, UiRevision } from './PvmRuntimeHost'

export interface ArkUiViewHost {
  replace(root: object, changed: object[], structureChanged: boolean): void
}

export interface ArkUiNodeFactory {
  reuse(node: UiNode): object | undefined
  touch?(node: UiNode): void
  touchRevision?(nodeId: number, revision: number): void
  update?(
    node: UiNode,
    emit: (nodeId: number, event: string, value?: string) => void,
  ): object | undefined
  create(
    node: UiNode,
    children: object[],
    emit: (nodeId: number, event: string, value?: string) => void,
  ): object
}

export class ArkUiRenderer implements UiRenderer {
  private visibleNodeIds: Set<number> = new Set()
  private pathsByNodeId: Map<number, number[]> = new Map()
  private appearedNodeIds: Set<number> = new Set()
  private host: ArkUiViewHost
  private factory: ArkUiNodeFactory
  private renderedRoot?: object
  private rootId: number = 0
  private rootType: string = ''
  private rootRevision: number = 0
  private eventSink: (nodeId: number, event: string, value?: string) => void =
    (_nodeId: number, _event: string, _value?: string): void => {}
  private readonly emitEvent: (nodeId: number, event: string, value?: string) => void =
    (nodeId: number, event: string, value?: string): void => {
      this.emit(nodeId, event, value)
    }

  constructor(host: ArkUiViewHost, factory: ArkUiNodeFactory) {
    this.host = host
    this.factory = factory
  }

  replaceTree(
    root: UiNode,
    emit: (nodeId: number, event: string, value?: string) => void,
  ): void {
    this.replaceBatch(
      {
        operation: 'replace',
        structureChanged: true,
        changed: [],
        root: root,
      },
      emit,
    )
  }

  replaceBatch(
    batch: UiBatch,
    emit: (nodeId: number, event: string, value?: string) => void,
  ): void {
    this.eventSink = emit
    const root = batch.root
    const nextRootId = root?.id ?? batch.rootId
    const nextRootType = root?.type ?? batch.rootType
    const nextRootRevision = root?.revision ?? batch.rootRevision
    if (
      nextRootId === undefined ||
      nextRootType === undefined ||
      nextRootRevision === undefined
    ) {
      throw new Error('UI batch root metadata is missing')
    }
    if (
      this.renderedRoot !== undefined &&
      this.rootId === nextRootId &&
      this.rootType === nextRootType &&
      this.rootRevision === nextRootRevision
    ) {
      return
    }
    const structureChanged =
      batch.structureChanged === undefined ? true : batch.structureChanged
    if (
      this.renderedRoot === undefined ||
      structureChanged ||
      this.rootId !== nextRootId ||
      this.rootType !== nextRootType
    ) {
      if (root === undefined) {
        throw new Error('A structural ArkUI update requires a complete root')
      }
      this.replaceStructure(root)
      return
    }
    const changedIds = batch.changed ?? []
    if (changedIds.length < 1) throw new Error('Incremental ArkUI batch has no changed nodes')
    if (new Set(changedIds).size !== changedIds.length) {
      throw new Error('Incremental ArkUI batch contains duplicate changed ids')
    }
    const changedModels =
      root === undefined
        ? this.changedPatchNodes(batch.nodes ?? [], changedIds)
        : this.resolveChanged(root, changedIds)
    if (changedModels.length !== changedIds.length) {
      throw new Error('Incremental ArkUI batch contains an unknown changed node')
    }
    if (root === undefined) {
      this.refreshPatchRevisions(batch.revisions ?? [], new Set(changedIds))
    } else {
      this.refreshAncestorRevisions(root, changedIds)
    }
    const changed = changedModels.map((node) => this.renderChanged(node))
    this.rootRevision = nextRootRevision
    this.host.replace(this.renderedRoot, changed, false)
  }

  private replaceStructure(root: UiNode): void {
    const nextVisible = this.indexStructure(root)
    this.appearedNodeIds = new Set(
      Array.from(this.appearedNodeIds).filter((id) => nextVisible.has(id)),
    )
    this.visibleNodeIds = nextVisible
    this.renderedRoot = this.render(root)
    this.rootId = root.id
    this.rootType = root.type
    this.rootRevision = root.revision
    this.host.replace(this.renderedRoot, [], true)
  }

  private render(node: UiNode): object {
    const supported = [
      'Text', 'Image', 'Row', 'Column', 'Stack', 'Scroll',
      'List', 'Button', 'Input', 'Switch', 'NativeSurface',
    ]
    if (!supported.includes(node.type)) throw new Error(`Unsupported VM node type ${node.type}`)
    const reused = this.factory.reuse(node)
    if (reused !== undefined) return reused
    return this.factory.create(
      node,
      node.children.map((child) => this.render(child)),
      this.emitEvent,
    )
  }

  private renderChanged(node: UiNode): object {
    if (node.type !== 'List' && this.factory.update !== undefined) {
      const updated = this.factory.update(node, this.emitEvent)
      if (updated !== undefined) return updated
    }
    return this.render(node)
  }

  private emit(nodeId: number, event: string, value?: string): void {
    if (!this.visibleNodeIds.has(nodeId)) return
    if (event === 'appear') {
      if (this.appearedNodeIds.has(nodeId)) return
      this.appearedNodeIds.add(nodeId)
    }
    this.eventSink(nodeId, event, value)
  }

  private resolveChanged(root: UiNode, ids: number[]): UiNode[] {
    const result: UiNode[] = []
    ids.forEach((id) => {
      const path = this.pathsByNodeId.get(id)
      if (path === undefined) return
      let node = root
      for (let index = 0; index < path.length; index += 1) {
        const child = node.children[path[index]]
        if (child === undefined) return
        node = child
      }
      if (node.id === id) result.push(node)
    })
    return result
  }

  private changedPatchNodes(nodes: UiNode[], ids: number[]): UiNode[] {
    const byId: Map<number, UiNode> = new Map()
    nodes.forEach((node) => {
      if (byId.has(node.id)) throw new Error(`Duplicate changed UI node ${node.id}`)
      byId.set(node.id, node)
    })
    return ids.flatMap((id) => {
      const node = byId.get(id)
      return node === undefined ? [] : [node]
    })
  }

  private refreshPatchRevisions(
    revisions: UiRevision[],
    changed: Set<number>,
  ): void {
    if (this.factory.touchRevision === undefined) return
    const touched: Set<number> = new Set()
    revisions.forEach((item) => {
      if (touched.has(item.id)) throw new Error(`Duplicate UI revision id ${item.id}`)
      touched.add(item.id)
      if (!changed.has(item.id)) this.factory.touchRevision?.(item.id, item.revision)
    })
  }

  private refreshAncestorRevisions(root: UiNode, ids: number[]): void {
    if (this.factory.touch === undefined) return
    const touched: Set<number> = new Set()
    ids.forEach((id) => {
      const path = this.pathsByNodeId.get(id)
      if (path === undefined) return
      let node = root
      path.forEach((childIndex) => {
        if (!touched.has(node.id)) {
          this.factory.touch?.(node)
          touched.add(node.id)
        }
        node = node.children[childIndex]
      })
    })
  }

  private indexStructure(root: UiNode): Set<number> {
    const result: Set<number> = new Set()
    const paths: Map<number, number[]> = new Map()
    const visit = (node: UiNode, path: number[]): void => {
      if (result.has(node.id)) throw new Error(`Duplicate UI node id ${node.id}`)
      result.add(node.id)
      paths.set(node.id, path)
      node.children.forEach((child, index) => visit(child, [...path, index]))
    }
    visit(root, [])
    this.pathsByNodeId = paths
    return result
  }
}
