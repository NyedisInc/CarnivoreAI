/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const claims: string[] = [];
let ids: string[] = ['ses_a', 'ses_b'];

vi.mock('./auth.svelte', () => ({
  authFetch: vi.fn(async (path: string, init: { method: string }) => {
    const id = decodeURIComponent(path.split('/')[2]!);
    if (init.method === 'PUT') claims.push(id);
    return { session_id: id, master: init.method === 'PUT' ? 'tab-me' : null, master_attached: true };
  }),
}));
vi.mock('./host', () => ({ primarySessionId: () => ids[0] }));
vi.mock('./sessions.svelte', () => ({ sessions: { data: [] } }));
vi.mock('../engine/layout.svelte', () => ({ terminalLayout: { state: { layout: {} } } }));
vi.mock('../engine/model', () => ({ instancesOf: () => ids.slice(1).map((n) => `terminal:${n}`) }));
vi.mock('../engine/meta', () => ({ kindOf: () => 'terminal' }));
vi.mock('../engine/slot-identity', () => ({ sessionForSlot: (slot: string) => slot.replace('terminal:', '') }));

const tell = (sessionId: string, master: string | null) =>
  window.dispatchEvent(new CustomEvent('cloude:size-master', { detail: { sessionId, master } }));
const flush = () => new Promise((r) => setTimeout(r, 0));

describe('master all', () => {
  beforeEach(() => {
    claims.length = 0;
    localStorage.setItem('carnivore.terminal.master_all', '1');
    (globalThis as any).TerminalSizeMaster = { clientId: () => 'tab-me' };
    vi.resetModules();
  });
  afterEach(() => { delete (globalThis as any).TerminalSizeMaster; });

  it('re-claims a session the server forgot (restart) on the next connect', async () => {
    const m = await import('./master-all.svelte');
    const stop = m.startMasterAll();
    await flush();
    expect(claims.sort()).toEqual(['ses_a', 'ses_b']);
    tell('ses_b', null);
    await flush();
    expect(claims.filter((c) => c === 'ses_b').length).toBe(2);
    expect(m.masterAll.enabled).toBe(true);
    stop();
  });

  it('a connect after the server forgot claims again even with no frame', async () => {
    const m = await import('./master-all.svelte');
    const sm = await import('./size-master.svelte');
    const stop = m.startMasterAll();
    await flush();
    sm.sizeMasters['ses_a'] = null;
    window.dispatchEvent(new CustomEvent('cloude:terminal-connection'));
    await flush();
    expect(claims.filter((c) => c === 'ses_a').length).toBe(2);
    stop();
  });

  it('a takeover by another browser still turns the switch off', async () => {
    const m = await import('./master-all.svelte');
    const stop = m.startMasterAll();
    await flush();
    tell('ses_a', 'tab-other');
    expect(m.masterAll.enabled).toBe(false);
    stop();
  });

  it('a hand release with the crown is not reclaimed', async () => {
    const m = await import('./master-all.svelte');
    const sm = await import('./size-master.svelte');
    const stop = m.startMasterAll();
    await flush();
    await sm.toggleSizeMaster('ses_a');
    tell('ses_a', null);
    await flush();
    expect(claims.filter((c) => c === 'ses_a').length).toBe(1);
    stop();
  });
  it('is inert in a solo-terminal window: no claim, the shared flag untouched', async () => {
    document.documentElement.setAttribute('data-solo', '7');
    try {
      const m = await import('./master-all.svelte');
      expect(m.masterAll.enabled).toBe(false);
      const stop = m.startMasterAll();
      await flush();
      m.setMasterAll(true);
      tell('ses_a', 'tab-other');
      await flush();
      expect(claims).toEqual([]);
      expect(localStorage.getItem('carnivore.terminal.master_all')).toBe('1');
      stop();
    } finally {
      document.documentElement.removeAttribute('data-solo');
    }
  });
});
