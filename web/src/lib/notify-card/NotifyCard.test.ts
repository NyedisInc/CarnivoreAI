/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import NotifyCard from './NotifyCard.svelte';
import { KINDS, type NotifyKind } from './contract.gen';
import { setLocale } from '../i18n/index.svelte';
import { cardPictureUrl } from './media';

const fetched = vi.hoisted(() => vi.fn());
vi.mock('../../opscenter/api/auth.svelte', () => ({ authFetchBlob: fetched, API_BASE: '/api/v1' }));

setLocale('en');

interface Fixture { kind: NotifyKind; payload: { acts: [string, string][]; body: string }; card: Record<string, unknown> }
const fixtures = import.meta.glob<Fixture>('../../../../tests/fixtures/notify_cards/*.json', { eager: true, import: 'default' });
const fixture = (kind: string): Fixture => fixtures[`../../../../tests/fixtures/notify_cards/${kind}.json`]!;

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
    for (const c of mounted.splice(0)) await unmount(c);
    document.body.replaceChildren();
});
function draw(props: Record<string, unknown>): HTMLElement {
    mounted.push(mount(NotifyCard, { target: document.body, props }));
    flushSync();
    return [...document.body.querySelectorAll('.nc')].pop() as HTMLElement;
}
const text = (el: HTMLElement) => el.textContent ?? '';

describe('every fixture kind', () => {
    test('there is a fixture for every kind', () => {
        for (const k of KINDS) expect(fixture(k), k).toBeTruthy();
    });

    test.each(KINDS)('%s draws its strip, its text and its action labels', (kind) => {
        const f = fixture(kind);
        const el = draw({ card: f.card, kind, acts: f.payload.acts, body: f.payload.body });
        const card = f.card as { strip: string[] };
        expect(el.dataset.kind).toBe(kind);
        expect(text(el.querySelector('.nc-bar')!)).toContain(card.strip[0]);
        expect(text(el.querySelector('.nc-bar')!)).toContain(card.strip.slice(1).filter(Boolean).join(' . '));
        const labels = [...el.querySelectorAll('.nc-acts [data-act]')].map((b) => b.textContent?.trim());
        expect(labels).toEqual(f.payload.acts.map(([, label]) => label));
        expect(text(el.querySelector('.nc-body')!).length).toBeGreaterThan(8);
        expect(text(el)).not.toMatch(/undefined|NaN|null|notify\.card\./);
    });

    test('specific content: the ask, the options, the command, the host, the sessions', () => {
        const ask = (k: string) => text(draw({ card: { ...fixture(k).card, ...(fixture(k).full ?? {}) }, kind: k, acts: fixture(k).payload.acts }));
        expect(ask('yesno')).toContain('merge exp/argent-widget-engine into master?');
        expect(ask('choice')).toContain('patch the widget engine in place');
        expect(ask('permission')).toContain('cd web && npm run build');
        expect(ask('link')).toContain('carnivore.ai');
        expect(ask('update')).toContain('2.1.301 to 2.1.312');
        expect(ask('swarm')).toContain('riskiest card first');
        expect(ask('finished')).toContain('done in 6 min');
        expect(ask('died')).toContain('exit code 1');
    });
});

describe('corner acceptance defects (S6e)', () => {
    const full = (k: string) => ({ ...fixture(k).card, ...(fixture(k).full ?? {}) });
    test('file: the first page row reads card.head and the type tag stays lowercase', () => {
        const el = draw({ card: full('file'), kind: 'file', acts: fixture('file').payload.acts });
        expect(text(el)).toContain('first page');
        expect(text(el)).toContain('mix v3 notes');
        expect(el.querySelector('.nc-ty')!.textContent).toBe('pdf');
        expect(getComputedStyle(el.querySelector('.nc-ty')!).textTransform).not.toBe('uppercase');
        expect(text(draw({ card: { ...full('file'), head: undefined }, kind: 'file' }))).not.toContain('first page');
    });
    test('a long path breaks only after a slash: a wbr follows each slash and the text is unchanged', () => {
        const path = 'src/core/sessions/resize.py';
        const el = draw({ card: { ...full('finished'), files: [path, 'tests/test_terminal_resize.py'], stats: [[1, 0], [2, 1]], nfiles: 2 }, kind: 'finished' });
        const row = el.querySelector('.nc-frow span')!;
        expect(row.textContent).toBe(path);
        expect(row.querySelectorAll('wbr').length).toBe(3);
        expect([...row.querySelectorAll('wbr')].every((w) => w.previousSibling?.textContent === '/' || w.previousSibling?.previousSibling?.textContent === '/')).toBe(true);
    });
    test('app update: the strip reads "nostromo" with no empty agent and no separator', () => {
        expect(text(draw({ card: full('appupdate'), kind: 'appupdate' }).querySelector('.nc-where')!).trim()).toBe('nostromo');
    });
    test('sign in: the account row carries the provider', () => {
        expect(text(draw({ card: full('signin'), kind: 'signin' }))).toContain('nyedis (claude)');
    });
    test('style comes from the action role: a lone later is secondary, the first contract action is confirm', () => {
        const style = (el: HTMLElement, id: string) => el.querySelector(`[data-act="${id}"]`)!.getAttribute('data-btn');
        expect(style(draw({ card: full('update'), kind: 'update', acts: [['later', 'later']] }), 'later')).toBe('secondary');
        const both = draw({ card: full('update'), kind: 'update' });
        expect([style(both, 'restart_agents'), style(both, 'later')]).toEqual(['confirm', 'secondary']);
    });
});

describe('clipping, empty and settled', () => {
    test('huge: 200 command lines clip at 12 lines with "open to read all"', () => {
        const f = fixture('permission');
        const cmd = Array.from({ length: 200 }, (_, i) => `./scripts/check-step-${i}.sh && \\`);
        const el = draw({ card: { ...f.card, cmd }, kind: 'permission', acts: f.payload.acts });
        expect(el.querySelector('.nc-clip')!.hasAttribute('data-clipped')).toBe(true);
        expect(text(el)).toContain('open to read all (200 lines)');
        expect((el.querySelector('.nc-clip') as HTMLElement).style.getPropertyValue('--lines')).toBe('12');
    });

    test('a short command is not clipped', () => {
        const f = fixture('permission');
        const el = draw({ card: f.card, kind: 'permission', acts: f.payload.acts });
        expect(el.querySelector('[data-clipped]')).toBeNull();
        expect(text(el)).not.toContain('open to read all');
    });

    test('empty: nothing to open, no buttons', () => {
        const el = draw({ card: null });
        expect(text(el)).toContain('nothing to open');
        expect(text(el)).toContain('no open notification');
        expect(el.querySelector('.nc-acts')).toBeNull();
    });

    test('settled: the answer replaces the body and the buttons', () => {
        const f = fixture('permission');
        const el = draw({ card: { ...f.card, answered: 'computer' }, kind: 'permission', acts: f.payload.acts });
        expect(el.hasAttribute('data-answered')).toBe(true);
        expect(text(el)).toContain('answered on the computer');
        expect(el.querySelector('.nc-acts')).toBeNull();
        expect(text(el.querySelector('.nc-bar')!)).toContain('answered');
    });
});

describe('the buttons', () => {
    test('a plain action calls onact with its id', () => {
        const f = fixture('permission');
        const onact = vi.fn();
        const el = draw({ card: f.card, kind: 'permission', acts: f.payload.acts, onact });
        (el.querySelector('[data-act="opt.2"]') as HTMLElement).click();
        expect(onact).toHaveBeenCalledWith('opt.2');
    });

    test('a reply action opens a text box and sends the typed text', () => {
        const f = fixture('yesno');
        const onact = vi.fn();
        const el = draw({ card: f.card, kind: 'yesno', acts: f.payload.acts, onact });
        (el.querySelector('[data-act="reply"]') as HTMLElement).click();
        flushSync();
        const input = el.querySelector('.nc-reply input') as HTMLInputElement;
        input.value = 'not yet';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        flushSync();
        el.querySelector('.nc-reply form, form.nc-reply')!.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
        expect(onact).toHaveBeenCalledWith('reply', 'not yet');
    });

    test('the corner window (no typing) leaves out the reply action and shows the close x', () => {
        const f = fixture('yesno');
        const onclose = vi.fn();
        const el = draw({ card: f.card, kind: 'yesno', acts: f.payload.acts, typing: false, onclose });
        expect([...el.querySelectorAll('[data-act]')].map((b) => (b as HTMLElement).dataset.act)).toEqual(['yes', 'no']);
        (el.querySelector('.nc-bar button') as HTMLElement).click();
        expect(onclose).toHaveBeenCalled();
    });
});

describe('permission deny style', () => {
    test('deny is the danger button, allow stays the confirming one', () => {
        const f = fixture('permission');
        const el = draw({ card: f.card, kind: 'permission', acts: f.payload.acts });
        expect(el.querySelector('[data-act="opt.2"]')?.getAttribute('data-btn')).toBe('danger');
        expect(el.querySelector('[data-act="opt.1"]')?.getAttribute('data-btn')).toBe('confirm');
    });
});

describe('fields the server fills (S2b, S8) and real media (S5b)', () => {
    const f = (k: string) => fixture(k);

    test('finished: per-file +added -removed counts; an unknown count draws nothing', () => {
        const el = draw({ card: { ...f('finished').card, stats: [[18, 4], [9, 2], []] }, kind: 'finished', acts: f('finished').payload.acts });
        const deltas = [...el.querySelectorAll('.nc-delta')].map((d) => d.textContent);
        expect(deltas).toEqual(['+18 -4', '+9 -2']);
        expect(el.querySelectorAll('.nc-frow').length).toBe(3);
        expect(text(draw({ card: { ...f('finished').card, stats: undefined }, kind: 'finished' }))).not.toMatch(/\+\d/);
    });

    test('file: page count with its size, one page singular, absent draws size only', () => {
        const base = f('file').card;
        const line = (c: Record<string, unknown>) => text(draw({ card: c, kind: 'file' }).querySelector('.nc-file')!);
        expect(line({ ...base, bytes: 219136, pages: 3 })).toContain('214 KB, 3 pages');
        expect(line({ ...base, bytes: 219136, pages: 1 })).toContain('214 KB, 1 page');
        expect(line({ ...base, bytes: 219136, pages: undefined })).not.toMatch(/page/);
    });

    test('swarm: a position with a side reads "who on computer"; without one just who', () => {
        const base = f('swarm').card;
        const el = draw({ card: { ...base, positions: [['Home', 'smallest first', 'studio'], ['Api-Docs', 'riskiest first']] }, kind: 'swarm' });
        expect([...el.querySelectorAll('.nc-pos b')].map((b) => b.textContent)).toEqual(['home on studio', 'api-docs']);
    });

    test.each([
        ['computer', 'answered on the computer', 'from this computer'],
        ['phone', 'already answered from this phone', 'from your phone'],
        ['auto', 'answered automatically', 'from an automatic rule'],
        ['elsewhere', 'answered somewhere else', 'from another device'],
    ])('settle where %s', (where, line, from) => {
        const el = draw({ card: { ...f('permission').card, answered: where }, kind: 'permission' });
        expect(text(el)).toContain(line);
        expect(text(el)).toContain(from);
    });

    test('image: an owner route is fetched with auth and drawn from an object URL; an error brings the placeholder back', async () => {
        fetched.mockResolvedValue(new Blob(['x'], { type: 'image/png' }));
        URL.createObjectURL = vi.fn(() => 'blob:picture');
        URL.revokeObjectURL = vi.fn();
        const path = '/api/v1/notifications/media/' + 'a'.repeat(32);
        const el = draw({ card: f('image').card, kind: 'image', mediaUrl: path });
        expect(el.querySelector('.nc-art')).not.toBeNull();
        await vi.waitFor(() => expect(el.querySelector('.nc-media img')).not.toBeNull());
        expect(fetched).toHaveBeenCalledWith(path.slice('/api/v1'.length));
        expect(el.querySelector('.nc-media img')!.getAttribute('src')).toBe('blob:picture');
        el.querySelector('.nc-media img')!.dispatchEvent(new Event('error'));
        flushSync();
        expect(el.querySelector('.nc-media img')).toBeNull();
        expect(el.querySelector('.nc-art')).not.toBeNull();
    });

    test('a failed fetch keeps the placeholder', async () => {
        fetched.mockRejectedValue(new Error('401'));
        const el = draw({ card: f('image').card, kind: 'image', mediaUrl: '/api/v1/notifications/media/' + 'c'.repeat(32) });
        await vi.waitFor(() => expect(fetched).toHaveBeenCalled());
        expect(el.querySelector('.nc-media img')).toBeNull();
        expect(el.querySelector('.nc-art')).not.toBeNull();
    });

    test('video poster and file first page draw as pictures; no url keeps the placeholder', () => {
        expect(draw({ card: f('video').card, kind: 'video', mediaUrl: '/p.png' }).querySelector('.nc-media img')).not.toBeNull();
        expect(draw({ card: f('file').card, kind: 'file', mediaUrl: '/p.png' }).querySelector('.nc-pv img')).not.toBeNull();
        expect(draw({ card: f('file').card, kind: 'file' }).querySelector('.nc-pv img')).toBeNull();
    });

    test('cardPictureUrl: image bytes, video poster, file poster only when flagged, bad id nothing', () => {
        const id = 'b'.repeat(32);
        expect(cardPictureUrl('image', { id })).toBe('/api/v1/notifications/media/' + id);
        expect(cardPictureUrl('video', { id })).toBe('/api/v1/notifications/media/' + id + '/poster');
        expect(cardPictureUrl('file', { id }, true)).toBe('/api/v1/notifications/media/' + id + '/poster');
        expect(cardPictureUrl('file', { id })).toBeUndefined();
        expect(cardPictureUrl('image', { id: '../x' })).toBeUndefined();
        expect(cardPictureUrl('died', { id })).toBeUndefined();
    });
});
