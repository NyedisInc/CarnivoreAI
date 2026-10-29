import type { SessionInfo, SessionRecord, ProjectResponse } from '../../opscenter/api/types';
import type { BrowserInfo } from '../browser/api.svelte';
import { isListedSession, kindOf, KIND_TERMINAL, type BucketRow } from '../drawer/bucketing';

export interface WarroomToggles {
  shells: boolean;
  browsers: boolean;
  asleep: boolean;
  computers: boolean;
}

export const DEFAULT_TOGGLES: Readonly<WarroomToggles> = { shells: false, browsers: false, asleep: false, computers: true };

export interface LiveTile {
  kind: 'live';
  key: string;
  row: SessionInfo;
  name: string;
  offline: string | null;
}

export interface AsleepTile {
  kind: 'asleep';
  key: string;
  record: SessionRecord;
  name: string;
  lastActive: string | null;
}

export interface BrowserTile {
  kind: 'browser';
  key: string;
  browser: BrowserInfo;
  name: string;
  url: string;
}

export type Tile = LiveTile | AsleepTile | BrowserTile;

export interface TileGroup {
  key: string;
  label: string;
  color: string | null;
  tiles: Tile[];
}

export interface WallInput {
  sessions: readonly SessionInfo[];
  asleep: readonly SessionRecord[];
  browsers: readonly BrowserInfo[];
  projects: readonly ProjectResponse[];
  toggles: WarroomToggles;
  colorOf: (projectId: number | null) => string | null;
  unfiledLabel: string;
  browsersLabel: string;
}

export function stripQuery(url: string): string {
  const cut = url.search(/[?#]/);
  return cut < 0 ? url : url.slice(0, cut);
}

export function isPaired(row: SessionInfo): boolean {
  return !!row.host_key && row.host_key !== 'local';
}

export function liveKey(row: SessionInfo): string {
  const own = typeof row.session_row_id === 'number' ? `row:${row.session_row_id}` : `tmux:${row.tmux_session ?? ''}`;
  return isPaired(row) ? `${row.host_key}:${own}` : own;
}

function nameOf(row: SessionInfo): string {
  return (row.label ?? '').trim() || row.tmux_session || row.session.id;
}

function listed(row: SessionInfo): boolean {
  return isListedSession(row as unknown as BucketRow);
}

export function buildWall(input: WallInput): TileGroup[] {
  const { toggles } = input;
  const live = input.sessions.filter((row) => {
    if (!listed(row)) return false;
    if (!toggles.shells && kindOf(row as unknown as BucketRow) === KIND_TERMINAL) return false;
    if (!toggles.computers && isPaired(row)) return false;
    return true;
  });
  const liveTmux = new Set(input.sessions.map((r) => r.tmux_session).filter((n): n is string => !!n));
  const liveUuids = new Set(
    input.sessions.map((r) => (r as { session_uuid?: string | null }).session_uuid).filter((u): u is string => !!u),
  );

  const groups = new Map<string, TileGroup>();
  const order: string[] = [];
  const put = (key: string, label: string, color: string | null, tile: Tile): void => {
    let group = groups.get(key);
    if (!group) {
      group = { key, label, color, tiles: [] };
      groups.set(key, group);
      order.push(key);
    }
    group.tiles.push(tile);
  };
  const projectName = (id: number | null | undefined): string | null =>
    input.projects.find((p) => p.id === id)?.name ?? null;

  for (const row of live) {
    const tile: LiveTile = { kind: 'live', key: liveKey(row), row, name: nameOf(row), offline: null };
    if (isPaired(row)) {
      tile.offline = (row.host_state || 'up') === 'up' ? null : row.host_label || row.host_key || null;
      put(`host:${row.host_key}`, row.host_label || row.host_key || '', null, tile);
    } else {
      const id = row.project_id ?? null;
      put(
        id === null ? 'project:none' : `project:${id}`,
        (id === null ? null : row.project_name || projectName(id)) || input.unfiledLabel,
        id === null ? null : input.colorOf(id),
        tile,
      );
    }
  }
  if (toggles.asleep) {
    for (const record of input.asleep) {
      if (record.asleep === false || record.archived_at || !record.tmux_name) continue;
      if (liveTmux.has(record.tmux_name) || liveUuids.has(record.session_uuid)) continue;
      if (!toggles.shells && kindOf({ agent_family: record.agent_family } as BucketRow) === KIND_TERMINAL) continue;
      const id = record.project_id;
      put(
        id === null ? 'project:none' : `project:${id}`,
        (id === null ? null : projectName(id)) || input.unfiledLabel,
        id === null ? null : input.colorOf(id),
        {
          kind: 'asleep',
          key: `asleep:${record.session_uuid}`,
          record,
          name: (record.title ?? '').trim() || record.tmux_name,
          lastActive: record.last_work_at,
        },
      );
    }
  }
  if (toggles.browsers) {
    for (const browser of input.browsers) {
      put('browsers', input.browsersLabel, null, {
        kind: 'browser',
        key: `browser:${browser.id}`,
        browser,
        name: browser.label || stripQuery(browser.url) || browser.id,
        url: stripQuery(browser.url),
      });
    }
  }

  const rankOf = (key: string): [number, string, string, number] => {
    if (key === 'project:none') return [1, '', '', 0];
    if (key.startsWith('project:')) {
      const project = input.projects.find((p) => `project:${p.id}` === key);
      return project
        ? [project.company_name ? 0 : 0.5, (project.company_name ?? '\uffff').toLowerCase(), project.name.toLowerCase(), project.id ?? 0]
        : [0.9, '', '', 0];
    }
    return [key.startsWith('host:') ? 2 : 3, key, '', 0];
  };
  const byRank = (a: string, b: string): number => {
    const x = rankOf(a);
    const y = rankOf(b);
    return x[0] - y[0] || x[1].localeCompare(y[1], undefined, { numeric: true }) || x[2].localeCompare(y[2], undefined, { numeric: true, sensitivity: 'base' }) || x[3] - y[3];
  };
  const out = order.map((key) => groups.get(key) as TileGroup).sort((a, b) => byRank(a.key, b.key) || a.key.localeCompare(b.key));
  for (const group of out) group.tiles.sort(compareTiles);
  return out;
}

const KIND_RANK = { live: 0, asleep: 1, browser: 2 } as const;

export function compareTiles(a: Tile, b: Tile): number {
  const idOf = (t: Tile): number => (t.kind === 'live' && typeof t.row.session_row_id === 'number' ? t.row.session_row_id : Number.MAX_SAFE_INTEGER);
  return KIND_RANK[a.kind] - KIND_RANK[b.kind] || idOf(a) - idOf(b) || a.key.localeCompare(b.key);
}
