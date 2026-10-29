/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { ApiError } from '../../opscenter/api/auth.svelte';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { Translate } from '../sessions/types';
import { loc } from '../skills-page/skills-fixtures';
import { GLOBAL_CONTEXT_ID, toItems, type ContextChoice } from '../skills-page/skills-model';
import type { Fetcher } from '../skills-page/skills-api';
import type { Inventory } from '../skills-page/skills-types';
import SkillPage from './SkillPage.svelte';

const en = createI18n({ locale: 'en' }) as { t: Translate };
const t: Translate = (key, params) => en.t(key, params);

const FILE = '---\nname: company-research\ndescription: research a company before a sale. say "research acme corp before my call" or "who funded this startup"\n---\n# company-research\n\nuse when the user asks.\n\n## steps\n\n1. restate the goal.\n';
const CONTEXT: ContextChoice = { id: GLOBAL_CONTEXT_ID, kind: 'global', label: 'global', projectPath: null, profile: null };

let mounted: Record<string, unknown> | null = null;
afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
});

async function settle(): Promise<void> {
    for (let i = 0; i < 4; i += 1) {
        for (let j = 0; j < 8; j += 1) await Promise.resolve();
        await tick();
        flushSync();
    }
}

function server(versions: unknown = [], file: string = FILE) {
    const writes: Record<string, unknown>[] = [];
    const fetcher = (async (path: string, init?: { method?: string; body?: string }) => {
        const method = init?.method ?? 'GET';
        if (path.startsWith('/skills/locations/') && path.includes('/skill-md/versions')) return Array.isArray(versions) ? { versions } : versions;
        if (path.startsWith('/skills/locations/') && path.includes('/skill-md') && method === 'GET') {
            return { location_id: 'x', name: 'company-research', body: file, body_truncated: false, size: file.length, sha256: 'sha-disk-now' };
        }
        if (path.startsWith('/skills/locations/') && path.includes('/skill-md') && method === 'PUT') {
            writes.push(JSON.parse(init?.body ?? '{}'));
            throw new ApiError('stale', 409, null, { current_sha256: 'sha-disk-now' });
        }
        if (path.startsWith('/skill-fires/usage')) return { skill: 'company-research', state: 'measured', fired_7d: 3, fired_30d: 9, fired_90d: 21 };
        if (path.includes('/autopsy')) return { skill: 'company-research', days: 30, state: 'measured', fires: 9, spans_measured: 8, tool_calls: 40, tool_errors: 4, interrupts: 1, corrections: 2, corrections_measured: 8 };
        throw new Error(`unexpected ${method} ${path}`);
    }) as unknown as Fetcher;
    return { fetcher, writes };
}

async function show(versions: unknown = [], file: string = FILE) {
    const inventory: Inventory = {
        context: { profile: 'default', group_id: 'cg-1', project_path: null },
        profile_groups: [],
        skills: [{ name: 'company-research', locations: [loc({ name: 'company-research', description: 'research a company before a sale', description_tokens_est: 41 })] }],
        settings_unparseable: [],
        tokens_label: 'est.',
    };
    const item = toItems(inventory, CONTEXT, t)[0]!;
    const actions = { writing: [], writeError: null, removals: {}, health: { ledger: null, census: null, tripwire: {} }, async changeState() {}, async remove() {}, async loadHealth() {}, clearError() {} };
    const s = server(versions, file);
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(SkillPage, { target, props: { item, inventory, context: CONTEXT, actions: actions as never, fetcher: s.fetcher, t, onOpenCatalog: () => {} } });
    await settle();
    return { root: target, ...s };
}

describe('the warez skill page', () => {
    test('is drawn on the shared embedded Page: its title strip names the skill and carries the star and the skull as base buttons', async () => {
        const { root } = await show();
        const page = root.querySelector('.skp > .oc-page.skp-page.oc-page--embedded')!;
        expect(page).not.toBeNull();
        expect(page.querySelector('.oc-titlebar .oc-titlebar__title')?.textContent).toContain('company-research');
        const star = page.querySelector<HTMLElement>('.oc-titlebar__actions [data-act="favorite"]')!;
        expect(star.getAttribute('data-btn')).toBe('quiet');
        expect(star.getAttribute('aria-pressed')).toBe('false');
        const skull = page.querySelector<HTMLElement>('.oc-titlebar__actions [data-act="remove-open"]')!;
        expect(skull.getAttribute('data-btn')).toBe('quiet');
        expect(skull.getAttribute('aria-expanded')).toBe('false');
        expect(page.querySelector('.skp-titlebar')).toBeNull();
        skull.click();
        await settle();
        expect(skull.getAttribute('aria-expanded')).toBe('true');
        expect(page.querySelector('.skp-rmstrip')).not.toBeNull();
    });

    test('renders the brief, the details and the SKILL.md for a skill', async () => {
        const { root } = await show();
        const brief = root.querySelector('[data-skill-brief]')!;
        expect(brief.textContent).toContain('research a company before a sale');
        expect([...brief.querySelectorAll('.skp-phrase')].map((n) => n.textContent)).toEqual(['research acme corp before my call', 'who funded this startup']);
        expect(brief.querySelector('[data-skill-tokens-every-turn]')?.textContent).toBe('41 tokens every turn');
        const details = root.querySelector('[data-skill-details]')!;
        expect([...details.querySelectorAll('[data-group="fired"] .skp-stat__v')].map((n) => n.textContent)).toEqual(['3', '9', '21']);
        expect(details.querySelector('[data-stat="in-all"] .skp-stat__v')?.textContent).not.toBe('-');
        const md = root.querySelector('[data-skill-md-block]')!;
        expect(md.querySelector('[data-skill-frontmatter]')?.textContent).toContain('company-research');
        expect(md.querySelector('.skp-fmt__h1')?.textContent).toBe('company-research');
        expect(md.querySelector('.skp-note')?.textContent).toContain('showing all');
        expect(root.querySelector('[data-skill-inspector] [data-harness="claude"] [data-state-choice="on"]')?.getAttribute('aria-pressed')).toBe('true');
    });

    test('a save on a stale base shows the conflict and does not overwrite', async () => {
        const { root, writes } = await show();
        root.querySelector<HTMLButtonElement>('[data-act="edit"]')!.click();
        await settle();
        const box = root.querySelector<HTMLTextAreaElement>('.skp-edit')!;
        box.value = `${FILE}\nmy edit\n`;
        box.dispatchEvent(new Event('input', { bubbles: true }));
        await settle();
        root.querySelector<HTMLButtonElement>('[data-act="save-version"]')!.click();
        await settle();
        expect(writes).toHaveLength(1);
        expect(writes[0]).toMatchObject({ base_sha256: 'sha-disk-now' });
        expect(root.querySelector('[data-skill-md-conflict]')).not.toBeNull();
        expect(root.querySelector('[data-msg]')).toBeNull();
        expect(root.querySelector<HTMLTextAreaElement>('.skp-edit')?.value).toContain('my edit');
    });

    test('a real-shaped version list (epoch seconds) renders, and a duplicate frontmatter key does not crash', async () => {
        const dup = FILE.replace('---\n#', '---\n#').replace('name: company-research\n', 'name: company-research\ndescription: first\n');
        const { root } = await show([{ id: 7, created_at: 1760745600.12, note: null, sha256: 'a', size: 120, action: 'edit', redacted: false }], dup);
        expect(root.querySelectorAll('[data-skill-frontmatter] dt').length).toBeGreaterThan(2);
        root.querySelector<HTMLButtonElement>('[data-act="versions"]')!.click();
        await settle();
        const row = root.querySelector('[data-skill-md-versions] .skp-ver__t')!.parentElement!;
        expect(row.querySelector('.skp-ver__t')?.textContent).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/);
    });

    test('the versions list shows time in words, line counts and each note beside its own version; the state block carries the effect line', async () => {
        const now = Date.now() / 1000;
        const { root } = await show({
            current: { id: 9, created_at: now - 7300, note: 'added a rule', sha256: 'b', size: 90, lines: 12, action: 'edit' },
            versions: [{ id: 8, created_at: now - 100000, note: null, sha256: 'a', size: 80, lines: 10, action: 'baseline' }],
        });
        root.querySelector<HTMLButtonElement>('[data-act="versions"]')!.click();
        await settle();
        const rows = [...root.querySelectorAll('[data-skill-md-versions] .skp-ver')].map((r) => r.textContent!.replace(/\s+/g, ' ').trim());
        expect(rows[0]).toContain('v2 2 hours ago added a rule 12 lines');
        expect(rows[1]).toContain('v1 yesterday first copy 10 lines');
        expect(root.querySelector('[data-skill-inspector] [data-harness="claude"] [data-skill-eff]')?.textContent).toBe('the model reads its full description every turn');
    });
});
