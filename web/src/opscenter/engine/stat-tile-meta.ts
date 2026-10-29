
import type { CellId, CellMeta, RowId } from './types';

export const STAT_TILE_IDS = [
  'stat-running',
  'stat-sessions',
  'stat-projects',
  'stat-ledger',
  'stat-alive',
  'stat-subagents',
] as const satisfies readonly CellId[];

export type StatTileId = (typeof STAT_TILE_IDS)[number];

const PHONE_ORDER: Readonly<Record<StatTileId, number>> = {
  'stat-running': 9,
  'stat-sessions': 16,
  'stat-projects': 17,
  'stat-ledger': 18,
  'stat-alive': 19,
  'stat-subagents': 20,
};

const LOOK: Readonly<Record<StatTileId, { icon: string; tone: CellMeta['iconTone'] }>> = {
  'stat-running': { icon: 'terminal-glyph', tone: 'oc-green' },
  'stat-sessions': { icon: 'session', tone: 'oc-cyan' },
  'stat-projects': { icon: 'check-bold', tone: 'oc-green' },
  'stat-ledger': { icon: 'arrow-down-circle', tone: 'oc-orange' },
  'stat-alive': { icon: 'person-bust', tone: 'oc-green' },
  'stat-subagents': { icon: 'users', tone: 'oc-cyan' },
};

const DEFAULT_ROW: RowId = 'r2';

export function statTileMeta(id: StatTileId, index: number): CellMeta {
  return {
    id,
    phoneOrder: PHONE_ORDER[id],
    titleKey: `opscenter.cell.${id.replace('-', '_')}.title`,
    icon: LOOK[id].icon,
    iconTone: LOOK[id].tone,
    showCount: false,
    chrome: 'bare',
    cornerSlot: [8, 8, 22],
    titleHeight: 0,
    defaultRow: DEFAULT_ROW,
    defaultIndex: index,
    defaultFr: 1 / STAT_TILE_IDS.length,
    defaultHeight: 69,
    minPx: 92,
    minHeight: 56,
    widthStates: [
      { name: 'narrow', min: 0 },
      { name: 'wide', min: 170 },
    ],
    heightStates: [
      { name: 'line', min: 0 },
      { name: 'flat', min: 69 },
      { name: 'graph', min: 112 },
    ],
  };
}

export const STAT_TILE_META: Readonly<Record<StatTileId, CellMeta>> = Object.fromEntries(
  STAT_TILE_IDS.map((id, index) => [id, statTileMeta(id, index)]),
) as Record<StatTileId, CellMeta>;
