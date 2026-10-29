/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { mount, unmount } from 'svelte';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';

installPopoverPolyfill();

const { openCatalogScreen } = vi.hoisted(() => ({ openCatalogScreen: vi.fn(() => true) }));
vi.mock('../catalog/screen-host', () => ({
    openCatalogScreen: (...args: unknown[]) => openCatalogScreen(...(args as [])),
}));

// EVERYTHING THE MOCK FACTORY TOUCHES MUST BE `vi.hoisted`, INCLUDING THE
// runs.
const { authFetchCalls, authFetchAnswers, FakeApiError } = vi.hoisted(() => {
    class FakeApiError extends Error {
        readonly status: number;
        readonly code: string | null;
        readonly payload: unknown;
        constructor(message: string, status: number, code: string | null, payload: unknown) {
            super(message);
            this.name = 'ApiError';
            this.status = status;
            this.code = code;
            this.payload = payload;
        }
    }
    return {
        authFetchCalls: [] as Array<{ path: string; method: string; body: unknown }>,
        authFetchAnswers: [] as unknown[],
        FakeApiError,
    };
});

vi.mock('../../opscenter/api/auth.svelte', () => ({
    ApiError: FakeApiError,
    authFetch: (path: string, init: RequestInit = {}) => {
        authFetchCalls.push({
            path,
            method: (init.method ?? 'GET').toUpperCase(),
            body: typeof init.body === 'string' ? JSON.parse(init.body) : null,
        });
        const answer = authFetchAnswers.shift();
        if (answer instanceof Error) return Promise.reject(answer);
        return Promise.resolve(answer ?? {});
    },
}));

import ThemeInspector from './ThemeInspector.svelte';
import { previewPalette } from './preview-palette';
import { i18n } from '../i18n/index.svelte';
import { scrollToRatings } from '../catalog/item-feedback';
import type { ThemeManifest } from '../../opscenter/api';

const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

function manifest(overrides: Partial<ThemeManifest> = {}): ThemeManifest {
    return {
        id: 'matrix',
        name: 'Matrix',
        description: 'green rain',
        author: null,
        version: '1.0',
        cssVars: {},
        xterm: {},
        source: 'builtin',
        feedbackItemId: null,
        publisher: null,
        ...overrides,
    };
}

let apiCalls: Array<{ name: string; args: unknown[] }> = [];
let ratingsAnswer: unknown = {
    item_id: null, count: 0, average: 0,
    histogram: { '1': 0, '2': 0, '3': 0, '4': 0, '5': 0 }, reviews: [],
};
let sessionAnswer: unknown = { signed_in: false, login: null, provider: null };

function plantWindowApi(): void {
    (window as unknown as { API: Record<string, unknown> }).API = {
        getCatalogItemRatings: (itemId: string) => {
            apiCalls.push({ name: 'getCatalogItemRatings', args: [itemId] });
            return Promise.resolve(ratingsAnswer);
        },
        getCatalogSession: () => {
            apiCalls.push({ name: 'getCatalogSession', args: [] });
            return Promise.resolve(sessionAnswer);
        },
    };
}

let handle: Record<string, unknown> | null = null;

function paintInspector(m: ThemeManifest): void {
    const target = document.createElement('div');
    document.body.appendChild(target);
    handle = mount(ThemeInspector, {
        target,
        props: {
            manifest: m,
            palette: previewPalette(m),
            active: false,
            starred: false,
            onapply: () => {},
            onstar: () => {},
        } as never,
    }) as never;
}

function paintFeedback(m: ThemeManifest): void {
    paintInspector(m);
}

function openNote(): void {
    (document.querySelector('[data-theme-note-open]') as HTMLButtonElement).click();
}

function settle(): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, 0));
}

beforeEach(() => {
    apiCalls = [];
    authFetchCalls.length = 0;
    authFetchAnswers.length = 0;
    ratingsAnswer = {
        item_id: null, count: 0, average: 0,
        histogram: { '1': 0, '2': 0, '3': 0, '4': 0, '5': 0 }, reviews: [],
    };
    sessionAnswer = { signed_in: false, login: null, provider: null };
});

afterEach(() => {
    if (handle) unmount(handle as never);
    handle = null;
    document.body.innerHTML = '';
    delete (window as unknown as { API?: unknown }).API;
});

describe('the star glyph', () => {
    test('the favorite button carries the bigger-glyph class', () => {
        plantWindowApi();
        paintInspector(manifest());
        const glyph = document.querySelector('[data-theme-star] .tins-star-glyph');
        expect(glyph).not.toBeNull();
        expect(glyph?.textContent).toBe('☆');
    });
});

describe('the developer row', () => {
    test('a catalog publisher opens the in-app profile and never links github', () => {
        plantWindowApi();
        paintInspector(manifest({ source: 'user', publisher: 'example-owner', author: null }));
        expect(document.querySelector('.isum-facts .alink [data-btn]')?.textContent).toContain('example-owner');
        expect(document.querySelector('.isum-facts a')).toBeNull();
    });

    test('a hostile handle prints as plain text, no control, no link', () => {
        plantWindowApi();
        paintInspector(manifest({ source: 'user', publisher: 'evil.com/x', author: null }));
        expect(document.querySelector('.isum-facts a')).toBeNull();
        expect(document.querySelector('.isum-facts .alink [data-btn]')).toBeNull();
        expect(document.body.textContent).toContain('evil.com/x');
    });

    test('no publisher falls back to the manifest author', () => {
        plantWindowApi();
        paintInspector(manifest({ source: 'builtin', publisher: null, author: 'NYX-9' }));
        expect(document.querySelector('.isum-facts a')).toBeNull();
        expect(document.body.textContent).toContain('NYX-9');
    });

    test('neither reads "not set"', () => {
        plantWindowApi();
        paintInspector(manifest({ source: 'user', publisher: null, author: null }));
        expect(document.body.textContent).toContain(t('themes.page.fact.unset'));
    });
});

describe('a hand-made theme opens no connection at all', () => {
    test('the unrateable sentence shows, and the api recorder saw NOTHING', async () => {
        plantWindowApi();
        paintFeedback(manifest({ source: 'user', feedbackItemId: null, publisher: null }));
        await settle();
        expect(document.body.textContent).toContain(t('themes.page.feedback.unrateable'));
        expect(document.querySelector('.tnf-heading')).toBeNull();
        expect(apiCalls).toEqual([]);
    });
});

describe('a bundled theme reads the reserved allowlist id', () => {
    test('the ratings read is asked for bundled/<id>, not the bare id', async () => {
        plantWindowApi();
        paintFeedback(manifest({ id: 'matrix', source: 'builtin', feedbackItemId: 'bundled/matrix' }));
        await settle();
        const asked = apiCalls.filter((c) => c.name === 'getCatalogItemRatings').map((c) => c.args[0]);
        expect(asked).toEqual(['bundled/matrix']);
    });
});

describe('a catalog-installed theme reads its own item id', () => {
    test('the ratings read is asked for the ledger item id', async () => {
        plantWindowApi();
        paintFeedback(manifest({
            id: 'matrix-x', source: 'user', feedbackItemId: 'example-owner/matrix-x', publisher: 'example-owner',
        }));
        await settle();
        const asked = apiCalls.filter((c) => c.name === 'getCatalogItemRatings').map((c) => c.args[0]);
        expect(asked).toEqual(['example-owner/matrix-x']);
    });
});

describe('signed out', () => {
    test('the send control is disabled and the sign-in button is offered', async () => {
        sessionAnswer = { signed_in: false, login: null, provider: null };
        plantWindowApi();
        paintFeedback(manifest({ source: 'builtin', feedbackItemId: 'bundled/matrix' }));
        await settle();
        openNote();
        await settle();
        const send = [...document.querySelectorAll('button')]
            .find((b) => (b.textContent ?? '').trim() === t('themes.page.note.send')) as HTMLButtonElement;
        expect(send.disabled).toBe(true);
        const signin = [...document.querySelectorAll('button')]
            .find((b) => (b.textContent ?? '').trim() === t('themes.page.note.signin')) as HTMLButtonElement;
        expect(signin).toBeDefined();
        signin.click();
        expect(openCatalogScreen).toHaveBeenCalled();
    });
});

describe('sending a note', () => {
    test('posts the text and shows the sent sentence', async () => {
        sessionAnswer = { signed_in: true, login: 'example-owner', provider: 'github' };
        plantWindowApi();
        authFetchAnswers.push({ item_id: 'bundled/matrix', created_at: '2026-09-22T00:00:00Z' });
        paintFeedback(manifest({ source: 'builtin', feedbackItemId: 'bundled/matrix' }));
        await settle();
        openNote();
        await settle();

        const box = document.querySelector('.tnf-box') as HTMLTextAreaElement;
        box.value = 'the reds clash on ansi 3';
        box.dispatchEvent(new Event('input', { bubbles: true }));
        await settle();

        const send = [...document.querySelectorAll('button')]
            .find((b) => (b.textContent ?? '').trim() === t('themes.page.note.send')) as HTMLButtonElement;
        expect(send.disabled).toBe(false);
        send.click();
        await settle();

        expect(authFetchCalls).toHaveLength(1);
        expect(authFetchCalls[0]?.method).toBe('POST');
        expect(authFetchCalls[0]?.path).toBe('/catalog/items/bundled%2Fmatrix/note');
        expect(authFetchCalls[0]?.body).toEqual({ text: 'the reds clash on ansi 3' });
        expect(document.body.textContent).toContain(t('themes.page.note.sent'));
        expect(box.value).toBe('');
    });

    test('a 429 from the host shows the shared refusal sentence', async () => {
        sessionAnswer = { signed_in: true, login: 'example-owner', provider: 'github' };
        plantWindowApi();
        authFetchAnswers.push(
            new FakeApiError('the server answered 429', 429, null, { detail: { code: 'rate_limited' } }),
        );
        paintFeedback(manifest({ source: 'builtin', feedbackItemId: 'bundled/matrix' }));
        await settle();
        openNote();
        await settle();

        const box = document.querySelector('.tnf-box') as HTMLTextAreaElement;
        box.value = 'please add a lighter accent';
        box.dispatchEvent(new Event('input', { bubbles: true }));
        await settle();

        const send = [...document.querySelectorAll('button')]
            .find((b) => (b.textContent ?? '').trim() === t('themes.page.note.send')) as HTMLButtonElement;
        send.click();
        await settle();

        expect(document.body.textContent).toContain(
            t('themes.page.note.failed', { reason: t('skill.refused.rate_limited') }),
        );
        expect(box.value).toBe('please add a lighter accent');
    });
});

describe('the rating summary and the merged comments', () => {
    const rated = {
        item_id: 'bundled/matrix', count: 1, average: 4,
        histogram: { '1': 0, '2': 0, '3': 0, '4': 1, '5': 0 },
        reviews: [{
            login: 'bob', stars: 4, text: 'nice greens', updated_at: 1790993383,
            author: 'bob', publisher: false, review_ref: 'r1',
        }],
    };

    test('the summary shows stars and a count that scrolls to the RATINGS section', async () => {
        ratingsAnswer = rated;
        plantWindowApi();
        const scroll = vi.fn();
        (Element.prototype as unknown as { scrollIntoView: unknown }).scrollIntoView = scroll;
        paintInspector(manifest({ feedbackItemId: 'bundled/matrix' }));
        await settle();
        const link = document.querySelector('[data-ratings-link]') as HTMLButtonElement;
        expect(link.textContent?.trim()).toBe(t('skill.rating.count', { count: 1 }));
        expect(document.querySelector('.isum [data-rating-stars]')).not.toBeNull();
        link.click();
        expect(scroll).toHaveBeenCalledWith(expect.objectContaining({ block: 'start' }));
        expect(document.getElementById('tfb-ratings')).not.toBeNull();
        expect(scrollToRatings()).toBe(true);
    });

    test('a rating with words is a comment: stars, author and a real date', async () => {
        ratingsAnswer = rated;
        plantWindowApi();
        paintInspector(manifest({ feedbackItemId: 'bundled/matrix' }));
        await settle();
        const row = document.querySelector('.thr__item') as HTMLElement;
        expect(row.textContent).toContain('nice greens');
        expect(row.textContent).toContain('bob');
        expect(row.querySelector('[data-rating-stars]')).not.toBeNull();
        expect(row.textContent).toContain('2026-');
        expect(document.body.textContent).not.toContain('1,790,993,383');
        expect(document.body.textContent).not.toContain('a catalog member');
    });
});
