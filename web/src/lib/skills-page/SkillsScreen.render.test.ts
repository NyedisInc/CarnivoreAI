/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

let onChanged: (() => void) | null = null;
vi.mock('../../opscenter/api/events.svelte', () => ({
    subscribe: (_kind: string, handler: () => void) => {
        onChanged = handler;
        return () => {
            onChanged = null;
        };
    },
}));

import SkillsScreen from './SkillsScreen.svelte';
import { fakeServer } from './skills-fixtures';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { Translate } from '../sessions/types';

const en = createI18n({ locale: 'en' }) as { t: Translate };
const t: Translate = (key, params) => en.t(key, params);

let mounted: Record<string, unknown> | null = null;

beforeEach(() => {
    onChanged = null;
});
afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
});

async function settle(): Promise<void> {
    for (let i = 0; i < 6; i += 1) await Promise.resolve();
    await tick();
    flushSync();
    for (let i = 0; i < 6; i += 1) await Promise.resolve();
    await tick();
    flushSync();
}

async function page(server = fakeServer(), extra: Record<string, unknown> = {}): Promise<{ root: HTMLElement; server: ReturnType<typeof fakeServer> }> {
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(SkillsScreen, { target, props: { embedded: true, fetcher: server.fetcher, t, ...extra } });
    await settle();
    return { root: target, server };
}

const card = (root: HTMLElement, name: string): HTMLElement =>
    root.querySelector<HTMLElement>(`[data-item-id="${name}"]`) as HTMLElement;

const chips = (root: HTMLElement, name: string): string =>
    Array.from(card(root, name).querySelectorAll('.mgr-chip')).map((c) => c.getAttribute('aria-label')).join(' | ');

async function open(root: HTMLElement, name: string): Promise<void> {
    (card(root, name).querySelector('.catalog-card__open') as HTMLElement).click();
    await settle();
}

const puts = (server: ReturnType<typeof fakeServer>) => server.seen.filter((s) => s.method === 'PUT').map((s) => s.body);

describe('the list', () => {
    test('lists every skill with harness, cost and foreign marks, and no switch for a plugin skill', async () => {
        const { root } = await page();
        expect(root.querySelectorAll('[data-item-id]').length).toBe(5);
        expect(chips(root, 'progress')).toBe('');
        expect(card(root, 'sme').textContent).not.toContain('est. 150 tokens');
        expect(card(root, 'progress').classList.contains('catalog-card')).toBe(true);
        expect(card(root, 'progress').getAttribute('data-kind')).toBe('skill');
        expect(card(root, 'progress').querySelector('.catalog-card__brief')).not.toBeNull();
        expect(card(root, 'progress').querySelector('.catalog-card__meta, .mgr-card__foot')).toBeNull();
        expect(card(root, 'progress').querySelector('[data-act="card-star"]')).not.toBeNull();
        expect(card(root, 'dup').textContent + chips(root, 'dup')).toContain('shadowed');
        expect(card(root, 'pluginskill').querySelector('[role="switch"]')).toBeNull();
        expect(card(root, 'sme').querySelector('[role="switch"]')).not.toBeNull();
        expect(card(root, 'noisy').querySelector('[role="switch"]')?.getAttribute('aria-checked')).toBe('false');
    });

    test('the chips narrow the list: off, codex; favorites narrows to none here; no shadowed or heavy chip', async () => {
        const { root } = await page();
        const chip = async (label: string): Promise<void> => {
            const button = Array.from(root.querySelectorAll<HTMLButtonElement>('.oc-chip')).find((b) => b.textContent?.startsWith(label));
            button!.click();
            await settle();
            expect(button!.getAttribute('aria-pressed')).toBe('true');
        };
        const names = (): string[] => Array.from(root.querySelectorAll('[data-item-id]')).map((e) => (e as HTMLElement).dataset.itemId!);
        const labels = Array.from(root.querySelectorAll('.oc-page__chips .oc-chip')).map((b) => b.textContent?.trim());
        expect(labels).toEqual(['claude', 'codex', 'off', 'favorites']);
        await chip('off');
        expect(names()).toEqual(['noisy']);
        (root.querySelector('.oc-chip[aria-pressed="true"]') as HTMLElement).click();
        await settle();
        await chip('favorites');
        expect(names()).toEqual([]);
        (root.querySelector('.oc-chip[aria-pressed="true"]') as HTMLElement).click();
        await settle();
        await chip('codex');
        expect(names()).toEqual(['progress']);
    });

    test('the context picker offers global, an own-folder account folder group and live projects only', async () => {
        const { root } = await page();
        const options = Array.from(root.querySelectorAll<HTMLOptionElement>('[data-facet="skills-context"] option')).map((o) => o.textContent);
        expect(options).toEqual(['global', 'account folder claude-code-bench (own folder)', 'lab']);
    });
});

describe('an add-on behind the task manager rules', () => {
    test('the detail shows a quiet flag with the changes since its rev, and only on that skill', async () => {
        const { root } = await page();
        await open(root, 'sme');
        const flag = root.querySelector('[data-skill-behind-rules]');
        expect(flag?.textContent).toContain('behind the task manager rules (written for rev 2, now 3)');
        expect(flag?.textContent).toContain('rev 3: add-ons declare guide_rev');
        await open(root, 'noisy');
        expect(root.querySelector('[data-skill-behind-rules]')).toBeNull();
    });
});

describe('the whole card opens the skill', () => {
    test('a click on the card body (grid or list) opens the details; a switch click does not', async () => {
        const { root } = await page();
        const opened = (): string | null => root.querySelector('.catalog-card[aria-current="true"]')?.getAttribute('data-item-id') ?? null;
        expect(opened()).toBeNull();
        (card(root, 'sme').querySelector('.catalog-card__brief') as HTMLElement).click();
        await settle();
        expect(opened()).toBe('sme');
        (card(root, 'noisy').querySelector('[role="switch"]') as HTMLElement).click();
        await settle();
        expect(opened()).toBe('sme');
        (card(root, 'progress').querySelector('.catalog-card__media') as HTMLElement).click();
        await settle();
        expect(opened()).toBe('progress');
    });
});

describe('the switch', () => {
    test('off in the global context writes the user file and the row shows what the server holds', async () => {
        const { root, server } = await page();
        (card(root, 'sme').querySelector('[role="switch"]') as HTMLElement).click();
        await settle();
        expect(puts(server)).toEqual([{ harness: 'claude', file: 'user', skill: 'sme', state: 'off' }]);
        expect(card(root, 'sme').querySelector('[role="switch"]')?.getAttribute('aria-checked')).toBe('false');
    });

    test('a skill on both harnesses writes each: claude to the user file, codex to the user config', async () => {
        const { root, server } = await page();
        (card(root, 'progress').querySelector('[role="switch"]') as HTMLElement).click();
        await settle();
        expect(puts(server)).toEqual([
            { harness: 'claude', file: 'user', skill: 'progress', state: 'off' },
            { harness: 'codex', file: 'user', skill: 'progress', state: 'off' },
        ]);
    });

    test('in a project context the write lands in settings.local.json with that project named', async () => {
        const { root, server } = await page();
        const select = root.querySelector('[data-facet="skills-context"]') as HTMLSelectElement;
        select.value = 'project:/work/lab';
        select.dispatchEvent(new Event('change', { bubbles: true }));
        await settle();
        expect(server.seen.some((s) => s.path.includes('project_path=%2Fwork%2Flab'))).toBe(true);
        (card(root, 'sme').querySelector('[role="switch"]') as HTMLElement).click();
        await settle();
        expect(puts(server)).toEqual([{ harness: 'claude', file: 'local', skill: 'sme', state: 'off', project_path: '/work/lab' }]);
    });

    test('turning a skill back on removes its key when the key lives in the file being written', async () => {
        const { root, server } = await page();
        (card(root, 'noisy').querySelector('[role="switch"]') as HTMLElement).click();
        await settle();
        expect(puts(server)).toEqual([{ harness: 'claude', file: 'user', skill: 'noisy', state: null }]);
    });
});

describe('the detail pane', () => {
    test('a claude skill offers the four states and a change writes the chosen one', async () => {
        const { root, server } = await page();
        await open(root, 'sme');
        const choices = Array.from(root.querySelectorAll('[data-harness="claude"] [data-state-choice]')).map((b) => b.textContent);
        expect(choices).toEqual(['on', 'compact', 'on demand', 'off']);
        (root.querySelector('[data-state-choice="user-invocable-only"]') as HTMLElement).click();
        await settle();
        expect(puts(server)).toEqual([{ harness: 'claude', file: 'user', skill: 'sme', state: 'user-invocable-only' }]);
        expect(root.querySelector('[data-skills-hint]')?.textContent).toContain('next skill call');
    });

    test('codex gets on and off only, says a restart is needed, and a plugin skill says why it has no control', async () => {
        const { root } = await page();
        await open(root, 'progress');
        expect(Array.from(root.querySelectorAll('[data-harness="codex"] [data-state-choice]')).map((b) => b.textContent)).toEqual(['on', 'off']);
        expect(root.querySelector('[data-skill-codex-note]')?.textContent).toContain('restart the session');
        await open(root, 'pluginskill');
        expect(root.querySelector('[data-skill-locked]')?.textContent).toContain('plugin skills switch with the whole plugin');
        expect(root.querySelector('[data-state-choice]')).toBeNull();
        expect(root.querySelector('[data-skill-remove]')).toBeNull();
    });

    test('remove asks first, then sends confirm true; a catalog-managed copy offers the catalog instead', async () => {
        const openCatalogPage = vi.fn();
        const { root, server } = await page(fakeServer(), { openCatalogPage });
        await open(root, 'noisy');
        (root.querySelector('[data-skill-remove]') as HTMLElement).click();
        await settle();
        expect(server.seen.some((s) => s.method === 'DELETE')).toBe(false);
        (root.querySelector('[data-skill-remove-confirm]') as HTMLElement).click();
        await settle();
        const del = server.seen.find((s) => s.method === 'DELETE')!;
        expect(del.path).toBe('/skills/locations/personal-claude%3Anoisy');
        expect(del.body).toEqual({ confirm: true });

        await open(root, 'sme');
        expect(root.querySelector('[data-skill-remove]')).toBeNull();
        (root.querySelector('[data-skill-open-catalog]') as HTMLElement).click();
        expect(openCatalogPage).toHaveBeenCalledTimes(1);
        expect(root.querySelector('[data-skill-origin]')?.textContent).toContain('acme/sme 1.2.0');
    });

    test('a refused remove shows the server sentence and keeps the skill', async () => {
        const server = fakeServer();
        const base = server.fetcher as unknown as (p: string, i?: RequestInit) => Promise<unknown>;
        const { ApiError } = await import('../../opscenter/api/auth.svelte');
        const fetcher = (async (path: string, init?: RequestInit) => {
            if (init?.method === 'DELETE') {
                throw new ApiError('x', 409, null, { detail: { code: 'target_unsafe', detail: 'that folder name is not safe to move' } });
            }
            return base(path, init);
        }) as never;
        const { root } = await page({ ...server, fetcher });
        await open(root, 'noisy');
        (root.querySelector('[data-skill-remove]') as HTMLElement).click();
        await settle();
        (root.querySelector('[data-skill-remove-confirm]') as HTMLElement).click();
        await settle();
        expect(root.querySelector('[data-mgr-error]')?.textContent).toContain('not safe to move');
        expect(card(root, 'noisy')).not.toBeNull();
    });
});

describe('live refresh and words', () => {
    test('a skills.changed frame re-reads the list', async () => {
        const { root, server } = await page();
        const reads = (): number => server.seen.filter((s) => s.path.startsWith('/skills?') || s.path === '/skills').length;
        const before = reads();
        expect(onChanged).not.toBeNull();
        onChanged!();
        await settle();
        expect(reads()).toBe(before + 1);
        expect(root.querySelectorAll('[data-item-id]').length).toBe(5);
    });

    test('no visible string is a bare catalog key', async () => {
        const { root } = await page();
        await open(root, 'progress');
        expect(root.textContent).not.toMatch(/\bskills\.(page|detail|loc|state|mark|harness)\./);
    });
});
