import { afterEach, describe, expect, test } from 'vitest';

import { browserCatalogHost } from './catalog';
import { latestVersion } from './card';
import { gradeView } from './grade';
import type { CatalogItem } from './types';

const ENTRY = {
    id: 'acme/progress',
    kind: 'skill',
    name: 'progress',
    publisher: 'acme',
    latest: '1.0.0',
    card: { title: 'progress', brief: 'a read only progress report' },
    fm: { description: 'a read only progress report of the current session' },
    versions: [
        {
            v: '1.0.0',
            digest: 'a'.repeat(64),
            grade: {
                grade: 'D',
                checked: 12,
                failed: [
                    {
                        rule: 'description.length',
                        level: 'required',
                        detail: 'description is 1059 characters, over the 1024 the specification allows',
                    },
                ],
                not_graded: ['compatibility.length', 'metadata.shape'],
            },
        },
    ],
};

const ENVELOPE = { index: { serial: 7, as_of: '2026-09-19' }, item: ENTRY };

let asked: string[] = [];

function plant(answer: unknown, reject = false): void {
    const g = globalThis as Record<string, unknown>;
    if (!('window' in g)) g.window = {};
    (g.window as Record<string, unknown>).API = {
        getCatalogItem: (itemId: string) => {
            asked.push(itemId);
            return reject ? Promise.reject(new Error('offline')) : Promise.resolve(answer);
        },
    };
}

afterEach(() => {
    const g = globalThis as Record<string, unknown>;
    delete g.window;
    asked = [];
});

describe('the single-item re-read', () => {
    test('hands the pane the ENTRY, never the envelope around it', async () => {
        plant(ENVELOPE);
        const answer = (await browserCatalogHost().item('acme/progress')) as Record<
            string,
            unknown
        >;
        expect(answer.id).toBe('acme/progress');
        expect(answer.latest).toBe('1.0.0');
        expect(Array.isArray(answer.versions)).toBe(true);
        expect(answer.item).toBeUndefined();
        expect(answer.index).toBeUndefined();
    });

    test('keeps the grade the list already painted', async () => {
        plant(ENVELOPE);
        const answer = await browserCatalogHost().item('acme/progress');
        const version = latestVersion(answer as CatalogItem);
        expect(version).not.toBe(null);
        const view = gradeView(version ? version.grade : null);
        expect(view.shape).toBe('graded');
        expect(view.letter).toBe('D');
        expect(view.checked).toBe(12);
        const failure = view.failed[0];
        expect(failure).toBeDefined();
        expect(failure?.rule).toBe('description.length');
        expect(failure?.level).toBe('required');
        expect(view.notGraded).toEqual(['compatibility.length', 'metadata.shape']);
    });

    test('asks for the id verbatim, since a rewritten id is another item', async () => {
        plant(ENVELOPE);
        await browserCatalogHost().item('acme/progress');
        expect(asked).toEqual(['acme/progress']);
    });

    test('answers NULL for an envelope carrying no entry, never a blank one', async () => {
        plant({ index: { serial: 7 } });
        await expect(browserCatalogHost().item('acme/progress')).resolves.toBe(null);
    });

    test('lets a transport failure through untouched', async () => {
        plant(null, true);
        await expect(browserCatalogHost().item('acme/progress')).rejects.toThrow('offline');
    });
});
