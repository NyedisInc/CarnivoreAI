/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const server = vi.hoisted(() => ({ reply: { items: [] as unknown[] } }));

vi.mock('../../opscenter/api/auth.svelte', () => ({
  auth: { state: 'signed-in' },
  initAuth: async () => {},
  ApiError: class extends Error {},
  authFetch: async (path: string) => (path === '/approvals' ? server.reply : null),
}));

import ApprovalCard from './ApprovalCard.svelte';
import { approvals, refreshApprovals } from './approvals.svelte';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');

const PROMPT = 'map the billing flow end to end and write the report to docs/billing.md';

function item(agentKey: string, prompt: string): unknown {
  return {
    id: 'act_pc', source: 'agent_action', session_id: '', kind: 'plugin_session_create', action: 'plugin_session_create',
    caller: 'cplug:local/flow', summary: 'plugin local/flow asks to start a session in project Flow',
    display: {
      verb: 'start', object: 'session', name: 'local/flow', tone: agentKey === 'plugin_agent' ? 'confirm' : 'danger',
      consequences: [
        { key: 'plugin_project', params: { project: 'Flow', where: '/work/flow' } },
        { key: agentKey, params: { agent: 'claude', profile: 'Claude default', badge: 'harness default' } },
        { key: 'plugin_prompt', params: { prompt: JSON.stringify(prompt) } },
      ],
      detail: [],
    },
  };
}

const apps: ReturnType<typeof mount>[] = [];

afterEach(() => {
  for (const app of apps.splice(0)) unmount(app);
  document.body.innerHTML = '';
  server.reply = { items: [] };
  approvals.items = [];
  approvals.notices = {};
});

async function card(row: unknown): Promise<HTMLElement> {
  server.reply = { items: [row] };
  const target = document.createElement('div');
  document.body.appendChild(target);
  await refreshApprovals();
  for (const it of approvals.items) apps.push(mount(ApprovalCard, { target, props: { item: it, onJump: () => {} } as never }));
  await tick();
  flushSync();
  return target;
}

describe('the plugin session-create card face', () => {
  test('shows the project, the agent and the whole prompt on the face, not only in the fold', async () => {
    const host = await card(item('plugin_agent', PROMPT));
    const face = [...host.querySelectorAll('[data-qc-facts] [data-qc-fact="effect"]')].map((el) => el.textContent ?? '');
    expect(face).toHaveLength(3);
    expect(face[0]).toContain('Flow');
    expect(face[1]).toContain('claude');
    expect(face[2]).toContain(PROMPT);
    expect(host.querySelector('[data-approval-detail]')).toBeNull();
  });

  test('another agent card still shows two effect lines', async () => {
    const row = item('plugin_agent', PROMPT) as { action: string; kind: string };
    row.action = row.kind = 'project_move';
    const host = await card(row);
    expect(host.querySelectorAll('[data-qc-facts] [data-qc-fact="effect"]')).toHaveLength(2);
  });
});
