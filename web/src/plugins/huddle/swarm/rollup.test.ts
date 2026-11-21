/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { beforeAll, describe, expect, test } from 'vitest';
import type { FloorSession } from '../../sdk';
import { buildFloor, type FloorInput } from './floor';
import { squareState, type PanelAgent } from './panel-state';

const client = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../../../client/js');
const ses = (key: string, projectId: number, status: string): FloorSession => ({
  key, name: `cloude_${key}`, label: key, sessionId: `ses_${key}`, sessionUuid: `u-${key}`, sessionRowId: null, asleep: false, projectId,
  projectName: null, harness: 'claude', listing: { activity_status: status },
});
const agent = (id: number, rank: string, over: Partial<PanelAgent> = {}): PanelAgent =>
  ({ id, display_name: `a${id}`, rank, state: 'awake', thread_key: `${id}`, session_id: null, ...over });

beforeAll(() => {
  for (const f of ['status-led.js', 'session-status-summary.js']) (0, eval)(fs.readFileSync(path.join(client, f), 'utf8'));
});

describe('swarm roll-up', () => {
  const input = (sessions: FloorSession[]): FloorInput => ({
    agents: [agent(1, 'alpha', { thread_key: 'all' }), agent(2, 'project', { project_id: 10, thread_key: '10', state: 'asleep' })],
    sessions, companies: [{ id: 5, name: 'Nyedis' }], projects: [{ id: 10, name: 'Carnivore', companyId: 5 }, { id: 11, name: 'Argent', companyId: 5 }],
    rowOf: () => undefined, showInactive: true,
  } as unknown as FloorInput);

  test('a project with a working agent paints working, a company rolls up its projects, Alpha rolls up the companies', () => {
    const floor = buildFloor(input([ses('a', 10, 'working'), ses('b', 11, 'idle')]));
    const project = floor.projects.find((p) => p.projectId === 10)!;
    expect(squareState(project.agent!, undefined, 0, project.rollup)).toBe('working');
    expect(floor.projects.find((p) => p.projectId === 11)!.rollup).toBe('idle');
    expect(floor.companies[0]!.rollup).toBe('working');
    expect(floor.alpha!.rollup).toBe('working');
    const quiet = buildFloor(input([ses('a', 10, 'idle'), ses('b', 11, 'idle')]));
    expect(quiet.companies[0]!.rollup).toBe('idle');
    expect(quiet.alpha!.rollup).toBe('idle');
  });
});
