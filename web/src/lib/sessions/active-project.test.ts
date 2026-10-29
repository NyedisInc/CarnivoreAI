/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { flushSync } from 'svelte';
import { ACTIVE_CHANNEL, activeProject, publishActiveProject, resetActiveProject } from './active-project.svelte';

const g = globalThis as unknown as Record<string, unknown>;

function bind(session: string, project: number | null): void {
  g.TerminalController = { _sessionId: () => session, _currentSession: { session: { id: session }, project_id: project } };
}

const wait = (): Promise<void> => new Promise((r) => setTimeout(r, 20));

afterEach(() => {
  resetActiveProject();
  delete g.TerminalController;
});

test('the bind announcement re-reads the pane, and each change is published; an ask is answered', async () => {
  const pop = new BroadcastChannel(ACTIVE_CHANNEL);
  const heard: unknown[] = [];
  pop.onmessage = (event) => heard.push(event.data);
  bind('ses_9', 9);
  publishActiveProject();
  flushSync();
  expect({ ...activeProject }).toEqual({ session: 'ses_9', project: 9 });
  bind('ses_7', null);
  window.dispatchEvent(new CustomEvent('cloude:primary-session-bound'));
  flushSync();
  expect({ ...activeProject }).toEqual({ session: 'ses_7', project: null });
  await wait();
  expect(heard).toEqual([{ kind: 'active', session: 'ses_9', project: 9 }, { kind: 'active', session: 'ses_7', project: null }]);
  pop.postMessage({ kind: 'ask' });
  await wait();
  expect(heard.at(-1)).toEqual({ kind: 'active', session: 'ses_7', project: null });
  pop.close();
});
