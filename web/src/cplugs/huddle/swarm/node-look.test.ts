/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import type { FloorSession } from '../../sdk';
import { colorBook } from './agent-colors.svelte';
import { DEFAULT_PACK } from './characters';
import { buildFloor } from './floor';
import { lookOf, type NodeLooks } from './node-look';
import type { PanelAgent } from './panel-state';
import SwarmPanel from './SwarmPanel.svelte';
import ChatAvatar from '../chat/ChatAvatar.svelte';
import type { BurstParty } from '../chat/chat-model';

const NOW = 1_000_000;
const ROSTER: PanelAgent[] = [
  { id: 4, display_name: 'Mimir', rank: 'feature', state: 'awake', thread_key: 'agent:4', session_id: 'ses_4', session_uuid: 'u-4', tmux_session: 'carnivore_mimir', project_id: 12 } as PanelAgent,
];
const CV = {
  key: 'u-cv', name: 'carnivore_cv', label: 'bot-Layer1', sessionId: 'ses_cv', sessionUuid: 'u-cv', sessionRowId: 50, asleep: false,
  projectId: 12, projectName: 'cloudecode', harness: 'claude', listing: { activity_status: 'working' },
} as FloorSession;
const ROWS: Record<string, { activity_status: string }> = { ses_4: { activity_status: 'question' }, ses_cv: { activity_status: 'working' } };

const floor = buildFloor({
  agents: ROSTER, sessions: [CV], companies: [{ id: 1, name: 'acme' }], projects: [{ id: 12, name: 'cloudecode', companyId: 1 }],
  showInactive: true, rowOf: (id) => (id ? ROWS[id] : undefined),
});
const book = colorBook(ROSTER, { companies: [{ id: 1, name: 'acme' }], projects: [{ id: 12, name: 'cloudecode', companyId: 1 }], sessions: [CV] });
const looks: NodeLooks = { of: (ref) => lookOf(floor, book, ref, NOW), pack: DEFAULT_PACK };

const apps: object[] = [];
afterEach(() => { for (const app of apps.splice(0)) unmount(app); document.body.innerHTML = ''; });

function face(el: Element | null): { state: string | null; status: string | null; body: string } {
  const ch = el?.querySelector('[data-state]') as HTMLElement | null;
  return { state: ch?.getAttribute('data-state') ?? null, status: ch?.getAttribute('data-status') ?? null, body: ch?.style.getPropertyValue('--c') ?? '' };
}

function host(id: string): HTMLElement {
  const el = document.createElement('div');
  el.id = id;
  document.body.appendChild(el);
  return el;
}

function avatar(party: Partial<BurstParty>, name: string): HTMLElement {
  const target = host(`av-${name}`);
  apps.push(mount(ChatAvatar, { target, props: { party: { key: name, dir: 'from', path: [], agentId: null, sessionUuid: null, owner: false, ...party } as BurstParty, name, looks } }));
  return target;
}

describe('one node, one look', () => {
  test('the drawer square and the chat avatar draw the same colors and live state', () => {
    const panel = host('panel');
    apps.push(mount(SwarmPanel, { target: panel, props: {
      floor, agents: ROSTER, density: 'expanded', now: NOW, colors: book, still: false, showInactive: true, onToggleInactive: vi.fn(), onOpen: vi.fn(),
    } }));
    const agentAv = avatar({ agentId: 4 }, 'Mimir');
    const cvAv = avatar({ sessionUuid: 'u-cv' }, 'bot-Layer1');
    flushSync();

    const tileAgent = face(panel.querySelector('[data-swarm-agent="4"]'));
    const tileCv = face(panel.querySelector('[data-swarm-session="u-cv"]'));
    expect(tileAgent.status).toBe('question');
    expect(tileCv.status).toBe('working');
    expect(tileAgent.body).not.toBe('');
    expect(tileCv.body).not.toBe('');

    expect(face(agentAv)).toEqual(tileAgent);
    expect(face(cvAv)).toEqual(tileCv);
  });
});
