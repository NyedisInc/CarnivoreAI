import { beforeEach, describe, expect, test, vi } from 'vitest';

const seams = vi.hoisted(() => ({
  opened: [] as (string | null)[],
  modalWorks: true,
  agents: [] as Record<string, unknown>[],
  pages: [] as number[],
}));

vi.mock('../../sdk', () => ({
  openSessionModal: (id: string | null) => {
    seams.opened.push(id);
    return seams.modalWorks && id !== null;
  },
  floorSource: () => ({
    sessions: [{ sessionUuid: 'u-peer', sessionId: 'ses_peer' }],
    companies: [{ id: 1, name: 'Nyedis' }],
    projects: [{ id: 17, name: 'Carnivore.ai', companyId: 1 }],
  }),
}));
vi.mock('../agents/agent-page.svelte', () => ({ openAgentPage: (id: number) => (seams.pages.push(id), true) }));
vi.mock('./chat-avatar', () => ({ rosterAgent: (id: number | null) => seams.agents.find((a) => a.id === id) ?? null }));

import { fullPathOf, openAuthorTerminal, pathTip } from './agent-open';

const uiFixes = { id: 80, display_name: 'Ui-Fixes', rank: 'feature', project_id: 17, company_id: null, session_id: 'ses_39776240' };

beforeEach(() => {
  seams.opened = [];
  seams.pages = [];
  seams.modalWorks = true;
  seams.agents = [uiFixes];
});

describe('the lineage tip', () => {
  test('a lone name crumb (the tiny recipient node) gets its company and project from the roster and the floor', () => {
    const full = fullPathOf([{ kind: 'agent', name: 'Ui-Fixes', agent_id: 80 }], 80);
    expect(pathTip(full)).toBe('Nyedis / Carnivore.ai / Ui-Fixes');
  });

  test('the server path is kept as is; a name alone (SysOp, a plain session) has no tip', () => {
    const path = [{ kind: 'company' as const, name: 'Nyedis', agent_id: 8 }, { kind: 'project' as const, name: 'Carnivore.ai', agent_id: 4 }];
    expect(pathTip(fullPathOf(path, 4))).toBe('Nyedis / Carnivore.ai');
    expect(pathTip(fullPathOf([{ kind: 'agent', name: 'shell', agent_id: null }], null))).toBe('');
  });
});

describe('the terminal door', () => {
  test('an agent opens its CURRENT body as the modal, never an old session id', () => {
    expect(openAuthorTerminal(80, 'eb900bd3-15e8-b753-18d7-924a425e5624')).toBe(true);
    expect(seams.opened).toEqual(['ses_39776240']);
    expect(seams.pages).toEqual([]);
  });

  test('a plain crosstalk peer opens by its session uuid; an asleep agent opens its chat instead', () => {
    openAuthorTerminal(null, 'u-peer');
    expect(seams.opened).toEqual(['ses_peer']);
    seams.agents = [{ ...uiFixes, session_id: null }];
    expect(openAuthorTerminal(80, null)).toBe(true);
    expect(seams.pages).toEqual([80]);
  });
});
