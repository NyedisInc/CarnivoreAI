/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { mount, unmount } from 'svelte';

import RatingControl from './RatingControl.svelte';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { CatalogHost } from './catalog';
import type { ItemRatingWrite, RatingWriteBody } from './types';

const i18n = createI18n({ locale: 'en' }) as {
    t(key: string, params?: Record<string, unknown> | null): string;
};
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

const SAVED: ItemRatingWrite = {
    item_id: 'example-owner/sme',
    count: 3,
    average: 4.67,
    histogram: { '1': 0, '2': 0, '3': 0, '4': 1, '5': 2 },
    your_stars: 5,
};

interface Recorder {
    host: CatalogHost;
    rated: Array<{ itemId: string; body: RatingWriteBody }>;
    removed: string[];
    written: number;
}

function hostFor(answer: ItemRatingWrite | Error): Recorder {
    const refuse = () => Promise.reject(new Error('the test never calls this'));
    const settle = () =>
        answer instanceof Error ? Promise.reject(answer) : Promise.resolve(answer);
    const recorder: Recorder = {
        host: null as never, rated: [], removed: [], written: 0,
    };
    recorder.host = {
        rateItem: (itemId: string, body: RatingWriteBody) => {
            recorder.rated.push({ itemId, body });
            return settle();
        },
        removeRating: (itemId: string) => {
            recorder.removed.push(itemId);
            return settle();
        },
        itemRatings: refuse,
        listItems: refuse,
        refreshIndex: refuse,
        listInstalled: refuse,
        previewInstall: refuse,
        install: refuse,
        uninstall: refuse,
        item: refuse,
        patchInstalled: refuse,
        applyUpdate: refuse,
        runningSessions: () => [],
        oneShot: refuse,
        listProjects: () => Promise.resolve([]),
        currentProjectPath: () => Promise.resolve(null),
    } as unknown as CatalogHost;
    return recorder;
}

let panel: Record<string, unknown> | null = null;

function paint(recorder: Recorder, signedIn = true, extra: Record<string, unknown> = {}): void {
    const target = document.createElement('div');
    document.body.appendChild(target);
    panel = mount(RatingControl, {
        target,
        props: {
            itemId: 'example-owner/sme',
            host: recorder.host,
            t,
            signedIn,
            onWritten: () => { recorder.written += 1; },
            ...extra,
        } as never,
    }) as never;
}

/** Let every microtask settle. */
function settle(): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, 0));
}

function stars(): HTMLButtonElement[] {
    return [...document.querySelectorAll<HTMLButtonElement>('.rate__star')];
}

function acts(): HTMLButtonElement[] {
    return [...document.querySelectorAll<HTMLButtonElement>('.rate__link')];
}

afterEach(() => {
    if (panel) unmount(panel as never);
    panel = null;
    document.body.innerHTML = '';
});

describe('signed out', () => {
    test('every control is disabled and the reason is on screen', async () => {
        const recorder = hostFor(SAVED);
        paint(recorder, false);
        await settle();
        expect(stars()).toHaveLength(5);
        expect(stars().every((star) => star.disabled)).toBe(true);
        expect(acts().every((act) => act.disabled)).toBe(true);
        expect(document.body.textContent).toContain(i18n.t('skill.rating.signed_out'));
    });

    test('NEGATIVE CONTROL: pressing a disabled star sends NOTHING', async () => {
        const recorder = hostFor(SAVED);
        paint(recorder, false);
        await settle();
        stars()[4]?.click();
        acts()[0]?.click();
        await settle();
        expect(recorder.rated).toEqual([]);
    });
});

describe('picking a rating and saving it', () => {
    test('it sends exactly the stars that were pressed', async () => {
        const recorder = hostFor(SAVED);
        paint(recorder);
        await settle();
        stars()[3]?.click();
        await settle();
        expect(recorder.rated).toHaveLength(1);
        expect(recorder.rated[0]?.body.stars).toBe(4);
        expect(recorder.rated[0]?.itemId).toBe('example-owner/sme');
    });

    test('NEGATIVE CONTROL: with no recorded rating there is no comment or remove link and nothing is sent', async () => {
        const recorder = hostFor(SAVED);
        paint(recorder);
        await settle();
        expect(acts()).toHaveLength(0);
        expect(recorder.rated).toEqual([]);
    });

    test('the words are sent with the recorded stars, from the comment box', async () => {
        const recorder = hostFor(SAVED);
        paint(recorder);
        await settle();
        stars()[4]?.click();
        await settle();
        acts()[0]?.click();
        await settle();
        const box = document.querySelector<HTMLTextAreaElement>('.rate__box');
        expect(box).not.toBeNull();
        if (box) {
            box.value = 'it reads well';
            box.dispatchEvent(new Event('input', { bubbles: true }));
        }
        document.querySelector<HTMLButtonElement>('.modal-btn-confirm')?.click();
        await settle();
        expect(recorder.rated).toHaveLength(2);
        expect(recorder.rated[1]?.body.text).toBe('it reads well');
        expect(recorder.rated[1]?.body.stars).toBe(5);
        expect(document.body.textContent).toContain('it reads well');
    });

    test('what the SERVER recorded is what gets shown, not what was pressed', async () => {
        const recorder = hostFor({ ...SAVED, your_stars: 2 });
        paint(recorder);
        await settle();
        stars()[4]?.click();
        await settle();
        expect(stars()[1]?.getAttribute('aria-pressed')).toBe('true');
        expect(stars()[4]?.getAttribute('aria-pressed')).toBe('false');
    });

    test('the caller\'s own review seeds the stars and the words', async () => {
        const recorder = hostFor(SAVED);
        paint(recorder, true, { initialStars: 3, initialText: 'my words' });
        await settle();
        expect(stars()[2]?.getAttribute('aria-pressed')).toBe('true');
        expect(document.body.textContent).toContain('my words');
    });

    test('a landed write tells the block to re-read', async () => {
        const recorder = hostFor(SAVED);
        paint(recorder);
        await settle();
        stars()[4]?.click();
        await settle();
        expect(recorder.written).toBe(1);
    });
});

describe('withdrawing one', () => {
    test('remove is offered once a rating is known, from the read or a write', async () => {
        const recorder = hostFor({ item_id: 'example-owner/sme', count: 2, removed: true });
        paint(recorder, true, { initialStars: 4 });
        await settle();
        expect(acts()[1]?.disabled).toBe(false);
        acts()[1]?.click();
        await settle();
        expect(recorder.removed).toEqual(['example-owner/sme']);
        expect(document.body.textContent).toContain(i18n.t('skill.rating.removed'));
    });

    test('NOTHING TO REMOVE gets its own sentence, not the removal one', async () => {
        const recorder = hostFor({ item_id: 'example-owner/sme', count: 2, removed: false });
        paint(recorder, true, { initialStars: 4 });
        await settle();
        acts()[1]?.click();
        await settle();
        expect(document.body.textContent).toContain(i18n.t('skill.rating.not_removed'));
        expect(document.body.textContent).not.toContain(i18n.t('skill.rating.removed'));
    });
});

describe('when the write does not land', () => {
    test('a NAMED refusal prints its own sentence', async () => {
        const refused = Object.assign(new Error('refused'), {
            status: 429,
            body: { code: 'rate_limited', detail: 'the daily rating limit is reached' },
        });
        const recorder = hostFor(refused);
        paint(recorder);
        await settle();
        stars()[4]?.click();
        await settle();
        expect(document.body.textContent).toContain(
            i18n.t('skill.refused.rate_limited'),
        );
    });

    test('an UNNAMED failure still says the rating was not saved', async () => {
        const recorder = hostFor(new Error('no route to host'));
        paint(recorder);
        await settle();
        stars()[4]?.click();
        await settle();
        expect(document.body.textContent).toContain(
            i18n.t('skill.rating.write.failed', { reason: 'no route to host' }),
        );
    });

    test('and a FAILED write never claims a rating was recorded', async () => {
        // NEGATIVE CONTROL for
        const recorder = hostFor(new Error('down'));
        paint(recorder);
        await settle();
        stars()[4]?.click();
        await settle();
        expect(document.body.textContent).not.toContain(i18n.t('skill.rating.saved'));
        expect(document.querySelector('.rate__mine')).toBeNull();
        expect(recorder.written).toBe(0);
    });
});

describe('an item this account never installed (the install gate, mirrored)', () => {
    test('every star is disabled and the reason is on screen, and nothing is sent', async () => {
        const recorder = hostFor(SAVED);
        paint(recorder, true, { installed: false });
        await settle();
        expect(stars().every((star) => star.disabled)).toBe(true);
        expect(document.body.textContent).toContain(i18n.t('skill.rating.not_installed'));
        stars()[3]?.click();
        await settle();
        expect(recorder.rated).toEqual([]);
    });

    test('an installed item keeps the stars enabled and shows no reason', async () => {
        const recorder = hostFor(SAVED);
        paint(recorder, true, { installed: true });
        await settle();
        expect(stars().some((star) => star.disabled)).toBe(false);
        expect(document.body.textContent).not.toContain(i18n.t('skill.rating.not_installed'));
    });

    test('a 403 install_required from the server prints the same reason', async () => {
        const recorder = hostFor(Object.assign(new Error('x'), { detail: { code: 'install_required' }, status: 403 }));
        paint(recorder);
        await settle();
        stars()[2]?.click();
        await settle();
        expect(document.body.textContent).toContain(i18n.t('skill.refused.install_required'));
    });
});
