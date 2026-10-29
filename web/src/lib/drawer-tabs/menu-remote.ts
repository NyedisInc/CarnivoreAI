import type { MenuNode } from './add-component-menu';

export interface WireNode {
  id: string;
  label: string;
  children?: WireNode[];
  blocked?: string;
  sep?: boolean;
  checked?: boolean;
  toggle?: boolean;
  icon?: string;
  hint?: string;
  title?: string;
  danger?: boolean;
  desc?: string;
  badge?: string;
  runs?: boolean;
}

export interface WireRect {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

export interface RemoteMenuHost {
  show(id: number, spec: { label: string; anchor: WireRect | null; nodes: WireNode[] }, controls: RemoteMenuControls): void;
  hide(id: number): void;
}

export interface RemoteMenuControls {
  choose(path: readonly string[]): void;
  close(): void;
}

let host: RemoteMenuHost | null = null;
let nextId = 1;

export function setRemoteMenuHost(next: RemoteMenuHost | null): void {
  host = next;
}

export function remoteMenuHost(): RemoteMenuHost | null {
  return host;
}

export function nextRemoteMenuId(): number {
  return nextId++;
}

export function isRemotable(nodes: readonly MenuNode[]): boolean {
  return nodes.every((node) => !node.swatches && !node.agent && !node.aggregateLightHtml && !node.glyphHtml && !node.locked && (!node.children || isRemotable(node.children)));
}

/* label: ' */
export function toWire(nodes: readonly MenuNode[]): WireNode[] {
  return nodes.map((node) => ({
    id: node.id,
    label: node.label,
    ...(node.children ? { children: toWire(node.children) } : {}),
    ...(node.blocked ? { blocked: node.blocked } : {}),
    ...(node.sep ? { sep: true } : {}),
    ...(node.checked !== undefined ? { checked: node.checked } : {}),
    ...(node.toggle ? { toggle: true } : {}),
    ...(node.icon ? { icon: node.icon } : {}),
    ...(node.hint ? { hint: node.hint } : {}),
    ...(node.title ? { title: node.title } : {}),
    ...(node.danger ? { danger: true } : {}),
    ...(node.desc ? { desc: node.desc } : {}),
    ...(node.badge ? { badge: node.badge } : {}),
    ...(node.run ? { runs: true } : {}),
  }));
}

export function findByPath(nodes: readonly MenuNode[], path: readonly string[]): MenuNode | null {
  const [head, ...rest] = path;
  const found = nodes.find((node) => node.id === head);
  if (!found) return null;
  return rest.length === 0 ? found : findByPath(found.children ?? [], rest);
}
