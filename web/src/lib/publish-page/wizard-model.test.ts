import { describe, expect, it } from 'vitest';
import type { ActionResult } from './actions';
import { heroSvg, type HeroColors } from './hero-art';
import { checkHeroImage } from './hero-check';
import { rasterLadder, type Encoder } from './hero-raster';
import type { HeldReason } from './keys';
import type { Limits, Rules } from './types';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { defaultVersion, heldCall, heldParams, heldReason, heldReasons, needsRecheck, refusalKey, runSend, type HeldContext } from './wizard-model';

const NOW = Date.parse('2026-10-24T12:00:00Z');
const LIMITS: Limits = {
    per_day: 5, used_today: 0, new_account: false, new_account_per_day: 1, new_account_days: 7, open_max: 3, open_now: 0,
    cooldown_until: '', strikes: 0, strikes_max: 3, appeals_max: 2, media_per_day: 5, media_used_today: 0,
};
const RULES: Rules = { kinds: ['skills', 'themes', 'mods', 'plugins'].map((kind) => ({ kind, open: true })), caps: {} };
const BASE: HeldContext = {
    signedIn: true, registered: true, kind: 'skill', rules: RULES, limits: LIMITS, checked: { version: '1.0.1', canSend: true },
    version: '1.0.1', sentVersions: ['1.0.0'], wantsImage: true, now: NOW,
};

const BREAK: Record<string, (c: HeldContext) => HeldContext> = {
    signed_out: (c) => ({ ...c, signedIn: false }),
    need_handle: (c) => ({ ...c, registered: false }),
    kind_closed: (c) => ({ ...c, rules: { kinds: [{ kind: 'skills', open: false }], caps: {} } }),
    cooldown: (c) => ({ ...c, limits: { ...(c.limits as Limits), cooldown_until: '2026-11-11T17:46:40Z' } }),
    day_limit: (c) => ({ ...c, limits: { ...(c.limits as Limits), used_today: 5 } }),
    open_limit: (c) => ({ ...c, limits: { ...(c.limits as Limits), open_now: 3 } }),
    not_checked: (c) => ({ ...c, checked: null }),
    folder_refused: (c) => ({ ...c, checked: c.checked && { ...c.checked, canSend: false } }),
    version_changed: (c) => ({ ...c, version: '1.0.9' }),
    version_exists: (c) => ({ ...c, sentVersions: [...c.sentVersions, c.version] }),
};
const ORDER = Object.keys(BREAK);

describe('the version a field starts with (D11)', () => {
    it('takes the declared version only when it is above the highest sent', () => {
        expect(defaultVersion('1.2.0', ['1.0.0', '1.1.0'])).toBe('1.2.0');
        expect(defaultVersion('1.1.0', ['1.0.0', '1.1.0'])).toBe('1.1.1');
        expect(defaultVersion('1.0.0', ['1.0.0', '1.1.0'])).toBe('1.1.1');
        expect(defaultVersion('', ['1.9.0', '1.10.0'])).toBe('1.10.1');
        expect(defaultVersion('2.0.0', [])).toBe('2.0.0');
        expect(defaultVersion('', [])).toBe('1.0.0');
    });
});

describe('why a send is held (D27)', () => {
    it('is not held when nothing applies', () => {
        expect(heldReasons(BASE)).toEqual([]);
        expect(heldReason(BASE)).toBeNull();
    });
    it('names the earlier reason of every pair that can coexist', () => {
        for (let i = 0; i < ORDER.length; i++) {
            for (let j = i + 1; j < ORDER.length; j++) {
                const [a, b] = [ORDER[i] as string, ORDER[j] as string];
                if (a === 'not_checked' && (b === 'folder_refused' || b === 'version_changed')) continue;
                const both = (BREAK[b] as (c: HeldContext) => HeldContext)((BREAK[a] as (c: HeldContext) => HeldContext)(BASE));
                expect(heldReason(both), `${a} + ${b}`).toBe(a as HeldReason);
            }
        }
    });
    it('gives each reason alone', () => {
        for (const reason of ORDER) expect(heldReason((BREAK[reason] as (c: HeldContext) => HeldContext)(BASE)), reason).toBe(reason);
    });
    it('keeps the image limit as a note that does not stop the item', () => {
        const full = { ...BASE, limits: { ...LIMITS, media_used_today: 5 } };
        expect(heldReasons(full)).toEqual([{ reason: 'image_limit', blocks: false }]);
        expect(heldReason(full)).toBeNull();
        expect(heldReasons((BREAK.not_checked as (c: HeldContext) => HeldContext)(full)).map((h) => h.reason)).toEqual(['image_limit', 'not_checked']);
        expect(heldReasons({ ...full, wantsImage: false })).toEqual([]);
    });
    it('holds a new account on its own lower daily cap', () => {
        const fresh = { ...BASE, limits: { ...LIMITS, new_account: true, used_today: 1 } };
        expect(heldReason(fresh)).toBe('day_limit');
    });
    it('does not hold on an answer it never got', () => {
        expect(heldReason({ ...BASE, limits: null, rules: null, registered: null })).toBeNull();
    });
});

describe('what a hosted refusal reads as (D27)', () => {
    it('maps each code to its key and leaves an unknown code to the send failure line', () => {
        for (const code of ['kind_closed', 'name_taken', 'name_pending', 'version_exists', 'kind_mismatch', 'rate_limited', 'open_limit', 'cooldown', 'folder_refused', 'folder_changed']) {
            expect(refusalKey(code)).toBe(`publish.page.held.${code}`);
        }
        expect(refusalKey('something_new')).toBeNull();
        expect(refusalKey('')).toBeNull();
    });
    it('sends only folder_changed back to "check it again"', () => {
        expect(needsRecheck('folder_changed')).toBe(true);
        expect(needsRecheck('version_exists')).toBe(false);
    });
});

function png(w: number, h: number): Uint8Array {
    const bytes = new Uint8Array(33);
    bytes.set([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a], 0);
    bytes.set([0x49, 0x48, 0x44, 0x52], 12);
    const view = new DataView(bytes.buffer);
    view.setUint32(16, w);
    view.setUint32(20, h);
    return bytes;
}

describe('an own image (D14, validate_media.py)', () => {
    it('passes a 1536x1024 png of 400 KiB', () => {
        expect(checkHeroImage(png(1536, 1024), 400 * 1024)).toEqual({ ok: true, type: 'png', w: 1536, h: 1024 });
    });
    it('refuses each way with its key', () => {
        expect(checkHeroImage(png(1536, 1024), 513 * 1024)).toMatchObject({ ok: false, key: 'skill.publish.hero.too_big' });
        expect(checkHeroImage(png(1000, 400), 1000)).toMatchObject({ ok: false, key: 'skill.publish.card_image.too_small' });
        expect(checkHeroImage(png(1200, 1200), 1000)).toMatchObject({ ok: false, key: 'skill.publish.card_image.bad_shape' });
        expect(checkHeroImage(png(6000, 3500), 1000)).toMatchObject({ ok: false, key: 'skill.publish.card_image.too_many_px' });
        expect(checkHeroImage(new Uint8Array([1, 2, 3, 4]), 4)).toMatchObject({ ok: false, key: 'skill.publish.refused.bad_image' });
    });
});

const SENT: ActionResult<{ submission_id?: string }> = { ok: true, value: { submission_id: 'ab' } };
const REFUSED: ActionResult<{ submission_id?: string }> = { ok: false, code: 'name_taken', text: 'no', detail: '' };

describe('the send sequence (D14)', () => {
    it('sends, then makes the image, then sends the image', async () => {
        const calls: string[] = [];
        const outcome = await runSend({
            image: 'made',
            send: async () => { calls.push('send'); return SENT; },
            imageBase64: async () => { calls.push('make'); return 'AAAA'; },
            media: async (b64) => { calls.push(`media:${b64}`); return { ok: true, value: null }; },
            onHero: (state) => calls.push(`hero:${state}`),
        });
        expect(calls).toEqual(['send', 'hero:making', 'make', 'media:AAAA']);
        expect(outcome).toEqual({ sent: SENT, hero: 'sent' });
    });
    it('leaves the send done when the image call fails', async () => {
        const outcome = await runSend({ image: 'own', send: async () => SENT, imageBase64: async () => 'AAAA', media: async () => ({ ok: false, code: 'bad_image', text: 'x', detail: '' }) });
        expect(outcome.sent.ok).toBe(true);
        expect(outcome.hero).toBe('failed');
    });
    it('leaves the send done when the image cannot be made', async () => {
        const gone = await runSend({ image: 'made', send: async () => SENT, imageBase64: async () => null, media: async () => ({ ok: true, value: null }) });
        expect(gone).toEqual({ sent: SENT, hero: 'failed' });
        const threw = await runSend({ image: 'made', send: async () => SENT, imageBase64: async () => { throw new Error('canvas'); }, media: async () => ({ ok: true, value: null }) });
        expect(threw.hero).toBe('failed');
    });
    it('sends no image after a refused send or with no image planned', async () => {
        let media = 0;
        const plan = { imageBase64: async () => 'AAAA', media: async () => { media++; return { ok: true as const, value: null }; } };
        expect(await runSend({ ...plan, image: 'made', send: async () => REFUSED })).toEqual({ sent: REFUSED, hero: 'none' });
        expect(await runSend({ ...plan, image: 'none', send: async () => SENT })).toEqual({ sent: SENT, hero: 'none' });
        expect(media).toBe(0);
    });
});

function encoder(table: Record<string, { type: string; size: number } | null>, asked: string[]): Encoder {
    return async (w, h, type) => {
        const key = `${type}:${w}x${h}`;
        asked.push(key);
        const answer = table[key];
        return answer ? new Blob([new Uint8Array(answer.size)], { type: answer.type }) : null;
    };
}
const KIB = 1024;

describe('the raster ladder (D14)', () => {
    it('takes the png when it fits', async () => {
        const asked: string[] = [];
        const made = await rasterLadder(encoder({ 'image/png:1536x1024': { type: 'image/png', size: 300 * KIB } }, asked));
        expect(made).toMatchObject({ type: 'image/png', width: 1536, height: 1024 });
        expect(asked).toEqual(['image/png:1536x1024']);
    });
    it('tries webp when the png is too big, and takes a real webp that fits', async () => {
        const made = await rasterLadder(encoder({
            'image/png:1536x1024': { type: 'image/png', size: 600 * KIB },
            'image/webp:1536x1024': { type: 'image/webp', size: 200 * KIB },
        }, []));
        expect(made).toMatchObject({ type: 'image/webp', width: 1536, height: 1024 });
    });
    it('refuses a "webp" that is really a png and goes on to the small png', async () => {
        const asked: string[] = [];
        const made = await rasterLadder(encoder({
            'image/png:1536x1024': { type: 'image/png', size: 600 * KIB },
            'image/webp:1536x1024': { type: 'image/png', size: 100 * KIB },
            'image/png:1200x800': { type: 'image/png', size: 400 * KIB },
        }, asked));
        expect(made).toMatchObject({ type: 'image/png', width: 1200, height: 800 });
        expect(asked).toEqual(['image/png:1536x1024', 'image/webp:1536x1024', 'image/png:1200x800']);
    });
    it('ends in nothing when all three are too big or unavailable', async () => {
        const big = { type: 'image/png', size: 600 * KIB };
        expect(await rasterLadder(encoder({ 'image/png:1536x1024': big, 'image/webp:1536x1024': { type: 'image/webp', size: 600 * KIB }, 'image/png:1200x800': big }, []))).toBeNull();
        expect(await rasterLadder(encoder({}, []))).toBeNull();
    });
});

describe('the made-for-you art', () => {
    const colors: HeroColors = { ground: 'rgb(2, 22, 30)', kind: 'rgb(150, 114, 254)', line: 'rgb(31, 46, 48)' };
    it('draws the same bytes for the same seed and others for another', () => {
        expect(heroSvg('notes@skill', 'skill', colors)).toBe(heroSvg('notes@skill', 'skill', colors));
        expect(heroSvg('notes@skill', 'skill', colors)).not.toBe(heroSvg('other@skill', 'skill', colors));
        for (const kind of ['theme', 'mod', 'plugin', 'cplug']) expect(heroSvg(`x@${kind}`, kind, colors)).toContain('<svg');
    });
    it('uses only the colors it was given', () => {
        expect(heroSvg('notes@skill', 'skill', colors)).not.toMatch(/#[0-9a-f]{3,8}\b/i);
    });
});

describe('the held lines read right with real values (X5-20, X5-21)', () => {
    const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
    const say = (key: string, params: Record<string, string | number>): string => i18n.t(...heldCall(key, params));
    const limits = { per_day: 1, new_account: false, new_account_per_day: 1, new_account_days: 7, open_now: 1, open_max: 3 } as unknown as Limits;

    it('says one as a word and plural nouns', () => {
        const p = heldParams(limits, 'skill', '', 'skills');
        expect(say('publish.page.held.day_limit', p)).toContain("today's one.");
        expect(say('publish.page.held.open_limit', p)).toBe('one of your items is already open. send waits until it is decided.');
        expect(say('publish.page.held.open_limit', { ...p, open: 3 })).toContain('3 of your items are already open');
        expect(say('publish.page.held.kind_closed', p)).toBe('the catalog is not taking skills yet.');
    });

    it('a cooldown with no date reads its dateless sentence', () => {
        const p = heldParams(limits, 'skill', '', 'skills');
        expect(say('publish.page.held.cooldown', p)).not.toMatch(/on \.$/);
        expect(say('publish.page.held.cooldown', { ...p, date: '5 nov' })).toContain('on 5 nov.');
    });
});
