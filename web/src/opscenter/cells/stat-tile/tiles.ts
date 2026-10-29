
import { stats, type StatCard } from '../../data/stats';
import type { StatTileId } from '../../engine/stat-tile-meta';

export const TILE_CARD: Readonly<Record<StatTileId, string>> = {
  'stat-running': 'running',
  'stat-sessions': 'sessions',
  'stat-projects': 'projects',
  'stat-ledger': 'ledger',
  'stat-alive': 'alive',
  'stat-subagents': 'subagents',
};

export function cardOfTile(id: string): StatCard | null {
  const cardId = (TILE_CARD as Record<string, string>)[id];
  return cardId ? (stats.find((card) => card.id === cardId) ?? null) : null;
}
