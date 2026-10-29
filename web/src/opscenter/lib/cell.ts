
import type { CellId, CellMeta, LayoutPage } from '../engine/types';
import type { SessionScope } from '../widgets/session-scope';
import type { PlacementOptions } from '../widgets/placement-options';

export interface CellProps {
  store?: import('../engine/layout.svelte').LayoutStore;
  width: number;
  height: number;
  meta: CellMeta;
  instance: string;
  collapsed?: boolean;
  phone?: boolean;
  limit?: number | null;
  onToggleCollapse?: () => void;
  page?: LayoutPage;
  scope?: SessionScope | null;
  options?: PlacementOptions;
  onOption?: (option: string, value: boolean | number | string) => void;
}

export interface CellEntry {
  meta: CellMeta;
  component: unknown;
}

export type CellRegistry = Readonly<Record<CellId, CellEntry>>;
