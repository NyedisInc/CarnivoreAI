import { describe, expect, test } from 'vitest';
import type { ProjectResponse, SessionInfo, SessionRecord } from '../../opscenter/api/types';
import type { BrowserInfo } from '../browser/api.svelte';
import { buildWall, DEFAULT_TOGGLES, liveKey, stripQuery, type WallInput } from './warroom-model';

function live(over: Partial<SessionInfo> & { tmux: string; rowId: number }): SessionInfo {
  const { tmux, rowId, ...rest } = over as Partial<SessionInfo> & { tmux: string; rowId: number };
  return {
    session: { id: `ses_${tmux}` } as SessionInfo['session'],
    tmux_session: tmux, session_row_id: rowId, label: null, agent_family: 'claude', project_id: null, project_name: null,
    ...rest,
  } as SessionInfo;
}
const record = (uuid: string, tmux: string, over: Partial<SessionRecord> = {}): SessionRecord =>
  ({ session_uuid: uuid, tmux_name: tmux, title: tmux, asleep: true, archived_at: null, project_id: null, agent_family: 'claude', last_work_at: null, ...over }) as SessionRecord;
const browser = (id: string, url: string): BrowserInfo => ({ id, label: '', url, state: 'live', viewers: 0, created_at: '', updated_at: '' });
const projects = [{ id: 2, name: 'beta' }, { id: 1, name: 'alpha' }] as ProjectResponse[];

function input(over: Partial<WallInput>): WallInput {
  return {
    sessions: [], asleep: [], browsers: [], projects, toggles: { ...DEFAULT_TOGGLES },
    colorOf: (id) => (id === null ? null : `c${id}`), unfiledLabel: 'no project', browsersLabel: 'browsers', ...over,
  };
}

describe('buildWall', () => {
  test('groups by project in the sidebar order (A-Z), unfiled last, colours from the project', () => {
    const wall = buildWall(input({
      sessions: [live({ tmux: 'a', rowId: 1, project_id: 1 }), live({ tmux: 'n', rowId: 2 }), live({ tmux: 'b', rowId: 3, project_id: 2 })],
    }));
    expect(wall.map((g) => g.label)).toEqual(['alpha', 'beta', 'no project']);
    expect(wall.map((g) => g.color)).toEqual(['c1', 'c2', null]);
  });

  test('tiles are keyed on the row id, never on session.id', () => {
    const row = live({ tmux: 'a', rowId: 7 });
    expect(liveKey(row)).toBe('row:7');
    const wall = buildWall(input({ sessions: [row] }));
    expect(wall[0]!.tiles[0]!.key).toBe('row:7');
    expect(wall[0]!.tiles[0]!.key).not.toContain(row.session.id);
    expect(liveKey(live({ tmux: 'x', rowId: 1, host_key: 'peer-a' }))).toBe('peer-a:row:1');
  });

  test('shells, asleep, browsers and computers each come and go with their toggle', () => {
    const sessions = [
      live({ tmux: 'agent', rowId: 1 }),
      live({ tmux: 'sh', rowId: 2, agent_family: 'shell' }),
      live({ tmux: 'far', rowId: 3, host_key: 'peer-a', host_label: 'hosta', host_state: 'up' }),
    ];
    const data = { sessions, asleep: [record('u1', 'sleepy')], browsers: [browser('b1', 'https://x.test/p?token=1')] };
    const kinds = (toggles: Partial<WallInput['toggles']>): string[] =>
      buildWall(input({ ...data, toggles: { ...DEFAULT_TOGGLES, ...toggles } })).flatMap((g) => g.tiles.map((t) => `${t.kind}:${t.name}`));
    expect(kinds({})).toEqual(['live:agent', 'live:far']);
    expect(kinds({ shells: true })).toContain('live:sh');
    expect(kinds({ asleep: true })).toContain('asleep:sleepy');
    expect(kinds({ computers: false })).toEqual(['live:agent']);
    const withBrowsers = buildWall(input({ ...data, toggles: { ...DEFAULT_TOGGLES, browsers: true } }));
    const tile = withBrowsers[withBrowsers.length - 1]!.tiles[0]!;
    expect(tile.kind === 'browser' && (tile as { url: string }).url).toBe('https://x.test/p');
    expect(stripQuery('https://a.test/x?q=1#h')).toBe('https://a.test/x');
  });

  test('a live row beats its asleep record, by tmux name or by uuid', () => {
    const wall = buildWall(input({
      sessions: [live({ tmux: 'same', rowId: 1 }), { ...live({ tmux: 'other', rowId: 2 }), session_uuid: 'u2' } as SessionInfo],
      asleep: [record('u1', 'same'), record('u2', 'renamed'), record('u3', 'alone')],
      toggles: { ...DEFAULT_TOGGLES, asleep: true },
    }));
    const asleep = wall.flatMap((g) => g.tiles).filter((t) => t.kind === 'asleep').map((t) => t.key);
    expect(asleep).toEqual(['asleep:u3']);
  });

  test('a paired computer groups under its own label and carries its offline state', () => {
    const wall = buildWall(input({ sessions: [live({ tmux: 'far', rowId: 3, host_key: 'peer-a', host_label: 'hosta', host_state: 'disconnected' })] }));
    expect(wall[0]!.label).toBe('hosta');
    const tile = wall[0]!.tiles[0]!;
    expect(tile.kind === 'live' && (tile as { offline: string | null }).offline).toBe('hosta');
  });
});
