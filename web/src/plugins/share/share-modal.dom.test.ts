/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

import { openModal } from '../../lib/modal';

const wire = vi.hoisted(() => ({
    rows: [] as Array<Record<string, unknown>>,
    all: [] as Array<Record<string, unknown>>,
    revokedAll: 0,
    relayAvailable: true,
    mintError: null as unknown,
    minted: {
        id: 'lnk_1',
        url: 'https://relay.carnivore.ai/s/lnk_1#v2.kZ3nQ7pXv1LbT8sA2dY6wR0mJ4hC5gU9eF-K_iOq1zM',
        expires_at: '2026-09-22T11:00:00Z',
    },
}));

const MINTED_URL = wire.minted.url;

vi.mock('./share-api', async (importOriginal) => {
    const actual = await importOriginal<typeof import('./share-api')>();
    return {
        ...actual,
        listShares: async () => ({ links: wire.rows, relay_available: wire.relayAvailable }),
        mintShare: async () => {
            if (wire.mintError) throw wire.mintError;
            return wire.minted;
        },
        revokeShare: async () => undefined,
        listAllShares: async () => wire.all,
        revokeAllShares: async () => {
            const ended = wire.all.map((r) => String(r.id));
            wire.revokedAll += 1;
            wire.all = [];
            wire.rows = [];
            return ended;
        },
    };
});

const { default: ShareModal } = await import('./ShareModal.svelte');

const LIVE_ROW = {
    id: 'lnk_1',
    session_id: 'ses_1',
    label: 'demo',
    created_at: '2026-09-22T10:00:00Z',
    expires_at: '2026-09-22T11:00:00Z',
};

async function settle(): Promise<void> {
    for (let i = 0; i < 10; i += 1) await Promise.resolve();
}

/** The overlay currently in the document, or null. */
function overlay(): HTMLElement | null {
    return document.querySelector('.modal-overlay');
}

function el<T extends Element>(selector: string): T {
    const found = overlay()?.querySelector<T>(selector);
    if (!found) throw new Error(`the dialog carries no ${selector}`);
    return found;
}

/** Press a key on the overlay, the way a user in the dialog would. */
function press(key: string): void {
    overlay()?.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
}

function openPanel(): Promise<null> {
    return openModal<null, Record<string, unknown>>(ShareModal as never, {
        sessionId: 'ses_1',
    });
}

async function mint(): Promise<void> {
    el<HTMLButtonElement>('[data-share-create]').click();
    await settle();
}

function stubCopyCompat(ok: boolean): { calls: string[] } {
    const calls: string[] = [];
    (globalThis as { CopyCompat?: unknown }).CopyCompat = {
        copyText(text: string) {
            calls.push(text);
            return Promise.resolve({ ok, method: ok ? 'exec' : 'manual' });
        },
    };
    return { calls };
}

beforeEach(() => {
    wire.rows = [];
    wire.all = [];
    wire.revokedAll = 0;
    wire.relayAvailable = true;
    wire.mintError = null;
});

afterEach(() => {
    document.body.innerHTML = '';
    delete (globalThis as { CopyCompat?: unknown }).CopyCompat;
});

const LIVE_ROW_WITH_URL = { ...LIVE_ROW, url: MINTED_URL };

describe('the active row shows the live link and copies it', () => {
    test('reopened with a live link, the row carries the url and a copy icon', async () => {
        wire.rows = [LIVE_ROW_WITH_URL];
        const closed = openPanel();
        await settle();
        const row = el('[data-share-row]');
        const input = row.querySelector<HTMLInputElement>('[data-share-url]');
        expect(input?.value).toBe(MINTED_URL);
        expect(input?.readOnly).toBe(true);
        const button = row.querySelector<HTMLButtonElement>('[data-share-copy]')!;
        expect(button.getAttribute('aria-label')).toBe('copy link');
        expect(button.getAttribute('title')).toBeNull();
        expect(button.querySelector('svg')).not.toBeNull();
        expect(overlay()!.textContent).not.toContain('not shown again');
        press('Escape');
        await closed;
    });

    test('it hands the exact url to CopyCompat synchronously, then reads copied', async () => {
        wire.rows = [LIVE_ROW_WITH_URL];
        const stub = stubCopyCompat(true);
        const closed = openPanel();
        await settle();

        el<HTMLButtonElement>('[data-share-copy]').click();
        expect(stub.calls).toEqual([MINTED_URL]);

        await settle();
        expect(el('[data-share-copy]').textContent!.trim()).toBe('copied');
        expect(el('[data-share-copy]').getAttribute('aria-label')).toBe('copied');
        press('Escape');
        await closed;
    });

    test('a refused copy selects the url, says how to copy by hand, never says copied', async () => {
        wire.rows = [LIVE_ROW_WITH_URL];
        stubCopyCompat(false);
        const closed = openPanel();
        await settle();

        el<HTMLButtonElement>('[data-share-copy]').click();
        await settle();

        expect(el('.share-notice').textContent).toContain(
            'select the link and copy it by hand',
        );
        expect(el('[data-share-copy]').getAttribute('aria-label')).toBe('copy link');
        const input = el<HTMLInputElement>('[data-share-url]');
        expect(input.value).toBe(MINTED_URL);
        expect(document.activeElement).toBe(input);
        expect(input.selectionStart).toBe(0);
        expect(input.selectionEnd).toBe(MINTED_URL.length);
        press('Escape');
        await closed;
    });

    test('a row the list names no url for shows the just-minted url of the same link', async () => {
        wire.rows = [LIVE_ROW];
        const closed = openPanel();
        await settle();
        expect(overlay()!.querySelector('[data-share-url]')).toBeNull();
        await mint();
        expect(el<HTMLInputElement>('[data-share-url]').value).toBe(MINTED_URL);
        press('Escape');
        await closed;
    });
});

describe('one live link per session, and the commit button says so', () => {
    test('with no link it says create, under the singular heading', async () => {
        const closed = openPanel();
        await settle();
        expect(el('.share-active').textContent!.trim()).toBe('active link');
        expect(overlay()!.querySelectorAll('[data-share-row]')).toHaveLength(0);
        expect(el('[data-share-create]').textContent!.trim()).toBe('create link');
        press('Escape');
        await closed;
    });

    test('one row renders, and the button becomes replace with its warning', async () => {
        wire.rows = [LIVE_ROW];
        const closed = openPanel();
        await settle();

        expect(el('.share-active').textContent!.trim()).toBe('active link');
        const rows = overlay()!.querySelectorAll('[data-share-row]');
        expect(rows).toHaveLength(1);
        expect(rows[0]!.textContent).toContain('demo');
        expect(rows[0]!.textContent).toContain('expires 2026-09-22T11:00:00Z');

        expect(el('[data-share-create]').textContent!.trim()).toBe('replace link');
        expect(overlay()!.textContent).toContain('creating a new link ends the current one.');
        press('Escape');
        await closed;
    });
});

// ---- the stylesheet contract ----------------------------------------

const repoRoot = path.resolve(process.cwd(), '..');

function definedClasses(source: string): Set<string> {
    const clean = source.replace(/\/\*[\s\S]*?\*\//g, '');
    const out = new Set<string>();
    const rule = /([^{}]+)\{[^{}]*\}/g;
    let match: RegExpExecArray | null;
    while ((match = rule.exec(clean)) !== null) {
        const selector = match[1]!.trim();
        if (selector.startsWith('@')) continue;
        for (const hit of selector.matchAll(/\.(-?[_a-zA-Z][\w-]*)/g)) out.add(hit[1]!);
    }
    return out;
}

describe('every button in the dialog wears a class the stylesheet defines', () => {
    const defined = definedClasses(
        ['client/css/styles.css', 'web/src/lib/base/elements.css']
            .map((file) => fs.readFileSync(path.join(repoRoot, file), 'utf8'))
            .join('\n'),
    );

    test('the extractor read a real stylesheet and tells classes apart', () => {
        expect(defined.size).toBeGreaterThan(200);
        expect(defined.has('modal-btn')).toBe(true);
        expect(defined.has('modal-btn-primary')).toBe(true);
        expect(defined.has('modal-btn-danger')).toBe(true);
        expect(defined.has('btn-primary')).toBe(false);
        expect(defined.has('btn-secondary')).toBe(false);
    });

    test('all five of them, with a link live and a url on screen', async () => {
        wire.rows = [LIVE_ROW];
        stubCopyCompat(true);
        const closed = openPanel();
        await settle();
        await mint();

        const buttons = [...overlay()!.querySelectorAll('button')];
        expect(buttons).toHaveLength(5);
        for (const button of buttons) {
            const classes = [...button.classList];
            expect(
                button.hasAttribute('data-btn') || classes.some((name) => defined.has(name)),
                `button "${button.textContent!.trim()}" carries no class any rule in ` +
                    `styles.css or the base layer defines: [${classes.join(' ') || 'no class at all'}]`,
            ).toBe(true);
        }
        press('Escape');
        await closed;
    });
});

describe('the owner is told what leaves the mac, without a promise', () => {
    test('the scrubbing line is always there and claims no guarantee', async () => {
        const closed = openPanel();
        await settle();
        const line = el('[data-share-scrubbed]').textContent!;
        expect(line).toContain('scrubbed for credentials on your computer');
        expect(line).toContain('the relay cannot read it');
        expect(line).not.toContain('again on the relay');
        expect(line).toContain('not a guarantee');
        press('Escape');
        await closed;
    });

    test('a link made on the v1 fallback is never described as end to end encrypted', async () => {
        wire.rows = [{ ...LIVE_ROW, url: 'https://relay.carnivore.ai/s/lnk_1#plainV1Token' }];
        const closed = openPanel();
        await settle();
        const line = el('[data-share-scrubbed]').textContent!;
        expect(line).toContain('not encrypted end to end');
        expect(line).not.toContain('the relay cannot read it');
        press('Escape');
        await closed;
    });

    test('the known limit of scrubbing is always stated under it', async () => {
        const closed = openPanel();
        await settle();
        expect(el('[data-share-scrub-limit]').textContent!.trim()).toBe(
            'scrubbing covers printed output. text typed or redrawn inside an interactive ' +
                'prompt, including claude code and codex, can still reach viewers, so keep ' +
                'secrets out of prompts while sharing.',
        );
        press('Escape');
        await closed;
    });

    test('the panel says every link opens on the relay', async () => {
        const closed = openPanel();
        await settle();
        expect(el('[data-share-relay]').textContent).toContain('opens on the relay');
        expect(overlay()!.textContent).not.toContain('relay publishing is off');
        press('Escape');
        await closed;
    });
});

describe('the relay is the only way a link works', () => {
    const UNAVAILABLE = 'relay unavailable. sharing needs the relay; try again shortly.';

    test('with the relay up, create is enabled and nothing warns', async () => {
        const closed = openPanel();
        await settle();
        expect(el<HTMLButtonElement>('[data-share-create]').disabled).toBe(false);
        expect(overlay()!.querySelector('[data-share-relay-unavailable]')).toBeNull();
        press('Escape');
        await closed;
    });

    test('when the list says the relay is down, create is disabled and says why', async () => {
        wire.relayAvailable = false;
        const closed = openPanel();
        await settle();
        expect(el<HTMLButtonElement>('[data-share-create]').disabled).toBe(true);
        expect(el('[data-share-relay-unavailable]').textContent!.trim()).toBe(UNAVAILABLE);
        press('Escape');
        await closed;
    });

    test('create comes back on its own once the relay reconnects', async () => {
        vi.useFakeTimers();
        try {
            wire.relayAvailable = false;
            const closed = openPanel();
            await settle();
            expect(el<HTMLButtonElement>('[data-share-create]').disabled).toBe(true);
            wire.relayAvailable = true;
            await vi.advanceTimersByTimeAsync(5000);
            await settle();
            expect(el<HTMLButtonElement>('[data-share-create]').disabled).toBe(false);
            expect(overlay()!.querySelector('[data-share-relay-unavailable]')).toBeNull();
            press('Escape');
            await closed;
        } finally {
            vi.useRealTimers();
        }
    });

    test('a 503 relay_unavailable from the mint disables create and shows no link', async () => {
        const { ApiError } = await import('../../opscenter/api/auth.svelte');
        wire.mintError = new ApiError('relay', 503, null, {
            detail: { code: 'relay_unavailable', reason: 'the relay publisher is not connected' },
        });
        const closed = openPanel();
        await settle();
        await mint();
        expect(overlay()!.querySelector('[data-share-url]')).toBeNull();
        expect(el<HTMLButtonElement>('[data-share-create]').disabled).toBe(true);
        expect(el('[data-share-relay-unavailable]').textContent!.trim()).toBe(UNAVAILABLE);
        expect(overlay()!.textContent).not.toContain('the link could not be created');
        press('Escape');
        await closed;
    });
});

describe('revoke every link on the install', () => {
    test('no line is drawn while nothing is live', async () => {
        const closed = openPanel();
        await settle();
        expect(overlay()!.querySelector('[data-share-all]')).toBeNull();
        press('Escape');
        await closed;
    });

    test('it counts the whole install and needs two presses to end every link', async () => {
        wire.rows = [LIVE_ROW_WITH_URL];
        wire.all = [LIVE_ROW_WITH_URL, { ...LIVE_ROW, id: 'lnk_2', session_id: 'ses_2' }];
        const closed = openPanel();
        await settle();
        expect(el('[data-share-all]').textContent).toContain('2 live links on this install');
        const button = el<HTMLButtonElement>('[data-share-revoke-all]');
        button.click();
        await settle();
        expect(wire.revokedAll).toBe(0);
        expect(button.dataset.armed).toBe('true');
        button.click();
        await settle();
        expect(wire.revokedAll).toBe(1);
        expect(overlay()!.querySelector('[data-share-all]')).toBeNull();
        expect(overlay()!.textContent).toContain('2 links revoked');
        press('Escape');
        await closed;
    });

    test('an armed button disarms itself after a few seconds', async () => {
        vi.useFakeTimers();
        try {
            wire.all = [LIVE_ROW];
            const closed = openPanel();
            await vi.advanceTimersByTimeAsync(0);
            await settle();
            const button = el<HTMLButtonElement>('[data-share-revoke-all]');
            button.click();
            await settle();
            expect(button.dataset.armed).toBe('true');
            await vi.advanceTimersByTimeAsync(4100);
            await settle();
            expect(button.dataset.armed).toBe('false');
            expect(wire.revokedAll).toBe(0);
            press('Escape');
            await closed;
        } finally {
            vi.useRealTimers();
        }
    });
});
