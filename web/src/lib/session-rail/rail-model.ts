import type { ZoneItem } from '../drawer-zone/zone-model';

/* the terminal grid */
export type RailEdge = 'side' | 'bottom';

export const RAIL_EDGES: readonly RailEdge[] = Object.freeze(['side', 'bottom'] as RailEdge[]);

export const RAIL_FIELD = 'session_rail';

export const RAIL_ID = 'session-widget-rail';

export const RAIL_BOTTOM_ID = 'session-widget-rail-bottom';

export const RAIL_MAX_ITEMS = 256;

export const DEFAULT_RAIL_ITEMS: readonly ZoneItem[] = Object.freeze([
  { widget: 'core.files', look: null },
  { widget: 'core.notes', look: null },
  { widget: 'core.bookmarks', look: null },
]);

/* the bottom rail */
export const DEFAULT_BOTTOM_ITEMS: readonly ZoneItem[] = Object.freeze([
  { widget: 'core.shell', look: null },
  { widget: 'core.scheduled-tasks', look: null },
]);

export interface RailSpec {
  field: string;
  id: string;
  axis: 'x' | 'y';
  defaults: readonly ZoneItem[];
}

export const RAIL_SPECS: Readonly<Record<RailEdge, RailSpec>> = Object.freeze({
  side: { field: RAIL_FIELD, id: RAIL_ID, axis: 'y', defaults: DEFAULT_RAIL_ITEMS },
  bottom: { field: 'session_rail_bottom', id: RAIL_BOTTOM_ID, axis: 'x', defaults: DEFAULT_BOTTOM_ITEMS },
});

export const RAIL_MAX_SECTIONS = 2;

export const RAIL_RATIO_DEFAULT = 0.5;

export const RAIL_RATIO_MIN = 0.15;
export const RAIL_RATIO_MAX = 0.85;

export const RAIL_RATIO_STEP = 0.02;

export type RailBand = 'start' | 'end';

export const RAIL_BANDS: readonly RailBand[] = Object.freeze(['start', 'end'] as RailBand[]);
