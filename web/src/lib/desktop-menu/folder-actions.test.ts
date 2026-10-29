/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';

const toasts: Array<{ text: string; kind: string }> = [];
vi.mock('../widgets-page/undo-toast', () => ({ showToast: (spec: { text: string; kind: string }) => { toasts.push(spec); } }));

import { folderTargetId, openInEditor, revealInFinder } from './folder-actions';

const rows = [
  { session: { id: 'ses_1' }, host_key: 'local', project_id: 7 },
  { session: { id: 'ses_2' }, host_key: 'peer-a', project_id: 8 },
  { session: { id: 'ses_3' }, project_id: null },
] as never;

afterEach(() => {
  delete (globalThis as { carnivoreDesktop?: unknown }).carnivoreDesktop;
  toasts.length = 0;
});

describe('folderTargetId', () => {
  test('the session or its project, as an id', () => {
    expect(folderTargetId('session', 'ses_1', rows)).toBe('ses_1');
    expect(folderTargetId('project', 'ses_1', rows)).toBe('project:7');
  });
  test('nothing in view, another computer, a remote id or no project give null', () => {
    expect(folderTargetId('session', null, rows)).toBeNull();
    expect(folderTargetId('session', 'ses_2', rows)).toBeNull();
    expect(folderTargetId('session', 'remote:peer-a:x', rows)).toBeNull();
    expect(folderTargetId('project', 'ses_3', rows)).toBeNull();
    expect(folderTargetId('session', 'ses_9', rows)).toBeNull();
  });
});

describe('revealInFinder and openInEditor', () => {
  function bridge(answer: unknown): string[] {
    const calls: string[] = [];
    const call = async (id: string) => { calls.push(id); return answer; };
    (globalThis as { carnivoreDesktop?: unknown }).carnivoreDesktop = { capabilities: ['revealById', 'openInEditor'], revealById: call, openInEditor: call };
    return calls;
  }
  test('a browser tab without the bridge does nothing', async () => {
    await revealInFinder('ses_1');
    expect(toasts).toHaveLength(0);
  });
  test('success and main-explained refusals are silent; a failure is one toast', async () => {
    const calls = bridge({ ok: true, reason: 'ok', error: null });
    await revealInFinder('ses_1');
    bridge({ ok: false, reason: 'missing', error: null });
    await openInEditor('project:7');
    bridge({ ok: false, reason: 'no_editor', error: null });
    await openInEditor('project:7');
    expect(calls).toEqual(['ses_1']);
    expect(toasts).toHaveLength(0);
    bridge({ ok: false, reason: 'failed', error: 'boom' });
    await revealInFinder('ses_1');
    expect(toasts.map((x) => x.kind)).toEqual(['failed']);
  });
});
