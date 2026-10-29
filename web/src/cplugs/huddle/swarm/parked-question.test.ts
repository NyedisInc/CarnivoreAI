/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { beforeAll, describe, expect, test } from 'vitest';
import type { FloorSession, ListingRow } from '../../sdk';
import { heldShape } from './characters/states';
import { buildFloor } from './floor';
import { squareState, type PanelAgent } from './panel-state';

const client = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../../../client/js');
const ses = (key: string, rowId: number, projectId: number, listing: ListingRow, asleep = false): FloorSession => ({
  key, name: `carnivore_${key}`, label: key, sessionId: asleep ? null : `ses_${key}`, sessionUuid: `u-${key}`, sessionRowId: rowId, asleep,
  projectId, projectName: null, harness: 'claude', listing,
});
const agent = (id: number, rank: string, over: Partial<PanelAgent> = {}): PanelAgent =>
  ({ id, display_name: `a${id}`, rank, state: 'asleep', thread_key: `${id}`, session_id: null, ...over });
const companies = [{ id: 1, name: 'Nyedis' }, { id: 2, name: 'acme' }];
const projects = [
  { id: 17, name: 'Carnivore.ai', companyId: 1 }, { id: 73, name: 'Tamvale SOLFORD', companyId: 1 },
  { id: 16, name: 'Example App', companyId: 2 }, { id: 72, name: 'acme HQ', companyId: 2 },
];

beforeAll(() => {
  for (const f of ['status-led.js', 'session-status-summary.js']) (0, eval)(fs.readFileSync(path.join(client, f), 'utf8'));
});

describe('a parked question on a Swarm agent', () => {
  test('the agent holds the "?" node, and its company and SysOp roll it up', () => {
    const asking: ListingRow = { activity_status: 'question' };
    const floor = buildFloor({
      agents: [
        agent(1, 'alpha', { thread_key: 'all', project_id: 71 }),
        agent(8, 'company', { company_id: 1, project_id: 73 }),
        agent(4, 'project', { project_id: 17, company_id: 1, state: 'awake', session_id: 'ses_body', session_row_id: 200 }),
      ],
      sessions: [ses('body', 200, 17, asking), ses('task', 211, 17, { activity_status: 'working' })],
      companies, projects, rowOf: (id) => (id === 'ses_body' ? asking : undefined), showInactive: false,
    });
    const project = floor.projects.find((p) => p.agent?.id === 4)!;
    const company = floor.companies.find((c) => c.agent?.id === 8)!;
    for (const it of [project, company, floor.alpha!]) expect(squareState(it.agent!, it.row, 0, it.rollup)).toBe('question');
    expect(heldShape('question')).toBe('qmark');
  });

  test('a company whose agents and sessions are all asleep shows in the default view', () => {
    const asleep: ListingRow = { activity_status: 'asleep' };
    const floor = buildFloor({
      agents: [
        agent(7, 'company', { company_id: 2, project_id: 72 }),
        agent(6, 'project', { project_id: 16, company_id: 2, session_row_id: 206 }),
      ],
      sessions: [ses('agent6', 206, 16, asleep, true), ses('ia', 300, 16, asleep, true), ses('ib', 301, 16, asleep, true)],
      companies, projects, rowOf: () => undefined, showInactive: false,
    });
    expect(floor.companies.map((c) => c.label)).toContain('a7');
    expect(floor.projects.map((p) => p.agent?.id)).toContain(6);
    expect(floor.agents.map((a) => a.label)).toEqual(['ia', 'ib']);
  });
});
