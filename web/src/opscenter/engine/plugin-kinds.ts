import type { WidgetManifest } from '../widgets/types';
import type { CellMeta, PluginKind } from './types';

const KINDS = new Map<PluginKind, CellMeta>();

export function registerPluginKind(kind: PluginKind, meta: CellMeta): void {
  KINDS.set(kind, meta);
}

export function pluginKinds(): PluginKind[] {
  return [...KINDS.keys()];
}

export function pluginKindMeta(kind: string): CellMeta | undefined {
  return KINDS.get(kind as PluginKind);
}

export function isPluginSlot(kindOrSlot: string): boolean {
  return /^[a-z][a-z0-9-]*\.[a-z][a-z0-9-]*(:|$)/.test(kindOrSlot);
}

export interface PanelProvider {
  manifests(): Readonly<Record<string, WidgetManifest>>;
  isPanel(kind: string): boolean;
  tail(kind: string): string | undefined;
  fit(kind: string): { w: number; h: number };
  info(kind: string): { about: string; data: string } | undefined;
  revision(): unknown;
}

let panelProvider: PanelProvider = { manifests: () => ({}), isPanel: () => false, tail: () => undefined, info: () => undefined, fit: () => ({ w: 6, h: 5 }), revision: () => 0 };

export function setPanelProvider(provider: PanelProvider): void {
  panelProvider = provider;
}

export function panels(): PanelProvider {
  return panelProvider;
}
