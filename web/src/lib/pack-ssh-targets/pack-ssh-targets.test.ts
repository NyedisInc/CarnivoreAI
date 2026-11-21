/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { ApiError } from '../../opscenter/api/auth.svelte';
import { setLocale } from '../i18n/index.svelte';
import SshTargetBlock from './SshTargetBlock.svelte';
import SshTargetRows from './SshTargetRows.svelte';
import { sshTargets } from './ssh-targets-store.svelte';
import type { SshTarget, SshTargetsApi } from './ssh-targets-api';

setLocale('en');
const FP = `SHA256:${'A'.repeat(43)}`;
const target = (over: Partial<SshTarget> = {}): SshTarget => ({
  host_key: 'wsl1', label: 'big box', state: 'not_set_up', reason: null, takes_work: false, pinned: false, fingerprint: null,
  can: { os: 'linux', os_version: '22.04', cores: 16, mem_gb: 64, gpus: [{ model: 'rtx 5090', vram_gb: 32 }], tools: { git: true, docker: false, make: true }, labels: ['wsl'] },
  pressure: null, age_s: 3, last_ok_age_s: 3, last_error: null, live_jobs: 0, ...over,
});
const confirm409 = (known = 'new'): ApiError => new ApiError('confirm', 409, 'confirm_host_key', {
  detail: { code: 'confirm_host_key', fingerprints: [{ sha256: FP, type: 'ED25519' }], known, pinned: known === 'changed' ? `SHA256:${'B'.repeat(43)}` : null, changed_since_shown: false },
});

let world: SshTarget[] = [];
const sets: { takes_work: boolean; host_key_sha256?: string }[] = [];
let checks = 0;
let forgets = 0;
let fresh = true;
const api: SshTargetsApi = {
  list: async () => world,
  set: async (key, body) => {
    sets.push(body);
    if (body.takes_work && !body.host_key_sha256) throw confirm409();
    world = world.map((x) => (x.host_key === key ? { ...x, takes_work: body.takes_work, pinned: true, state: body.takes_work ? 'taking_work' : 'off' } : x));
    return world.find((x) => x.host_key === key)!;
  },
  check: async (key) => { checks += 1; return { fresh, target: world.find((x) => x.host_key === key)! }; },
  forget: async () => { forgets += 1; return { forgotten: ['uid1'], kept: [], refused: [] }; },
};

const mounted: ReturnType<typeof mount>[] = [];
const settle = async (): Promise<void> => { await new Promise((r) => setTimeout(r, 0)); flushSync(); };
const q = (sel: string): HTMLElement | null => document.body.querySelector<HTMLElement>(sel);
async function render(key = 'wsl1'): Promise<void> {
  const host = document.createElement('div');
  document.body.append(host);
  mounted.push(mount(SshTargetBlock, { target: host, props: { hostKey: key, api } }));
  await settle(); await settle();
}
const click = async (sel: string): Promise<void> => { q(sel)!.click(); await settle(); await settle(); };
const on = (): string | null => q('[data-ssh="takes-work"]')!.getAttribute('aria-checked');

beforeEach(() => { world = [target()]; sets.length = 0; checks = 0; forgets = 0; fresh = true; sshTargets.list = []; sshTargets.changed = {}; sshTargets.loaded = false; });
afterEach(async () => { for (const m of mounted.splice(0)) await unmount(m); document.body.replaceChildren(); });

describe('the takes-work switch and the host key confirm', () => {
  test('on with no key confirmed opens the confirm with the fingerprint and sends no confirming PUT', async () => {
    await render();
    expect(on()).toBe('false');
    await click('[data-ssh="takes-work"]');
    expect(q('[data-ssh="fingerprint"]')!.textContent).toBe(FP);
    expect(q('[data-ssh="confirm-cancel"]')).not.toBeNull();
    expect(q('[data-ssh="confirm-go"]')).not.toBeNull();
    expect(sets).toEqual([{ takes_work: true }]);
    expect(sets.some((s) => s.host_key_sha256)).toBe(false);
    expect(on()).toBe('false');
  });

  test('confirm sends the PUT with exactly the shown fingerprint and the switch reads on', async () => {
    await render();
    await click('[data-ssh="takes-work"]');
    await click('[data-ssh="confirm-go"]');
    expect(sets).toEqual([{ takes_work: true }, { takes_work: true, host_key_sha256: FP }]);
    expect(on()).toBe('true');
    expect(q('[data-ssh="state"]')!.textContent).toBe('takes work');
  });

  test('cancel sends nothing more and the switch stays off', async () => {
    await render();
    await click('[data-ssh="takes-work"]');
    await click('[data-ssh="confirm-cancel"]');
    expect(sets).toEqual([{ takes_work: true }]);
    expect(on()).toBe('false');
    expect(q('[data-ssh="confirm"]')).toBeNull();
  });
});

describe('state words and the check', () => {
  const words = async (over: Partial<SshTarget>): Promise<string> => {
    world = [target(over)];
    await render();
    return q('[data-ssh="state"]')!.textContent ?? '';
  };
  test('each state shows its words', async () => {
    expect(await words({ state: 'off', takes_work: false, pinned: true })).toBe('does not take work');
    document.body.replaceChildren();
    expect(await words({ state: 'host_key_not_confirmed' })).toBe('host key not confirmed');
    document.body.replaceChildren();
    expect(await words({ state: 'taking_work', takes_work: true })).toBe('takes work');
    document.body.replaceChildren();
    expect(await words({ state: 'taking_work', takes_work: true, pressure: { pegged: true, why: 'gpu busy' } })).toBe('takes work, gpu busy');
    document.body.replaceChildren();
    expect(await words({ state: 'did_not_answer', takes_work: true, last_ok_age_s: 120 })).toBe('did not answer over ssh, last figures 2 min ago');
  });

  test('a changed host key says so with the way out, and the way out reaches the confirm with the changed sentence', async () => {
    world = [target({ state: 'did_not_answer', takes_work: true, pinned: true })];
    await render();
    api.check = async () => { throw new ApiError('changed', 409, 'host_key_changed'); };
    await click('[data-ssh="check"]');
    expect(q('[data-ssh="state"]')!.textContent).toBe('host key changed');
    expect(q('[data-ssh="changed-way"]')!.textContent).toContain('check it, then confirm the new fingerprint');
    api.set = async () => { throw confirm409('changed'); };
    await click('[data-ssh="reconfirm"]');
    expect(q('[data-ssh="confirm-changed"]')).not.toBeNull();
  });

  test('check shows the not fresh wording only when the server says the answer was not fresh', async () => {
    api.check = async (key) => { checks += 1; return { fresh, target: world.find((x) => x.host_key === key)! }; };
    await render();
    await click('[data-ssh="check"]');
    expect(checks).toBe(1);
    expect(q('[data-ssh="not-fresh"]')).toBeNull();
    fresh = false;
    await click('[data-ssh="check"]');
    expect(q('[data-ssh="not-fresh"]')).not.toBeNull();
  });

  test('the facts read linux (wsl), memory, graphics card and tools', async () => {
    await render();
    const facts = q('[data-ssh="facts"]')!.textContent ?? '';
    expect(facts).toContain('linux (wsl) 22.04');
    expect(facts).toContain('rtx 5090, 32 gb');
    expect(facts).toContain('git, make');
    expect(facts).not.toContain('docker');
  });
});

describe('removing the copies', () => {
  test('the button asks first; cancel sends nothing, remove sends one delete and says so', async () => {
    world = [target({ state: 'taking_work', takes_work: true, pinned: true })];
    await render();
    await click('[data-ssh="forget"]');
    expect(q('[data-ssh="forget-ask"]')).not.toBeNull();
    await click('[data-ssh="forget-cancel"]');
    expect(forgets).toBe(0);
    await click('[data-ssh="forget"]');
    await click('[data-ssh="forget-go"]');
    expect(forgets).toBe(1);
    expect(q('[data-ssh="forgot"]')!.textContent).toBe('the copies are removed from this computer.');
  });

  test('a computer with no pinned key has nothing to remove and a running job disables the button', async () => {
    await render();
    expect(q('[data-ssh="forget"]')).toBeNull();
    document.body.replaceChildren();
    world = [target({ state: 'taking_work', takes_work: true, pinned: true, live_jobs: 1 })];
    sshTargets.list = [];
    await render();
    expect((q('[data-ssh="forget"]') as HTMLButtonElement).disabled).toBe(true);
  });
});

describe('who shows the block', () => {
  test('a computer the server does not list (paired, or not ssh) shows no block', async () => {
    world = [target({ host_key: 'other' })];
    await render('paired-one');
    expect(q('[data-ssh="block"]')).toBeNull();
  });

  test('the project rows carry state in words and no control', async () => {
    world = [target({ state: 'taking_work', takes_work: true }), target({ host_key: 'b', label: 'second', state: 'off' })];
    const host = document.createElement('div');
    document.body.append(host);
    mounted.push(mount(SshTargetRows, { target: host, props: { api } }));
    await settle(); await settle();
    const rows = [...document.body.querySelectorAll('[data-ssh-row]')];
    expect(rows.map((r) => r.textContent)).toEqual(['big boxtakes work', 'seconddoes not take work']);
    expect(q('[data-ad="ssh-rows"] h4')!.textContent).toBe('computers over ssh');
    expect(host.querySelectorAll('button, input, select, [role="switch"], [role="checkbox"]').length).toBe(0);
  });

  test('with no ssh computer the rows render nothing', async () => {
    world = [];
    const host = document.createElement('div');
    document.body.append(host);
    mounted.push(mount(SshTargetRows, { target: host, props: { api } }));
    await settle(); await settle();
    expect(q('[data-ad="ssh-rows"]')).toBeNull();
  });
});

describe('far strings are text', () => {
  test('markup in a label, a system name, a graphics card and a fingerprint type is shown as text, never as elements', async () => {
    const evil = '<img src=x onerror=alert(1)>';
    world = [target({ label: evil, can: { os: evil, cores: 1, gpus: [{ model: evil }], tools: { [evil]: true }, labels: [] } })];
    await render();
    expect(document.body.querySelector('img')).toBeNull();
    expect(q('[data-ssh="facts"]')!.textContent).toContain(evil);
    api.set = async () => { throw new ApiError('c', 409, 'confirm_host_key', { detail: { fingerprints: [{ sha256: evil, type: evil }], known: 'new', pinned: null, changed_since_shown: false } }); };
    await click('[data-ssh="takes-work"]');
    expect(q('[data-ssh="fingerprint"]')!.textContent).toBe(evil);
    expect(document.body.querySelector('img')).toBeNull();
  });
});
