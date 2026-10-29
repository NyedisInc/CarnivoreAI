import { afterEach, describe, expect, test } from 'vitest';
import { browserCatalogHost } from './catalog';

function plant(viewedId: string | null, sessions: Record<string, unknown>): string[] {
    const asked: string[] = [];
    const g = globalThis as Record<string, unknown>;
    if (!('window' in g)) g.window = {};
    const w = g.window as Record<string, unknown>;
    w.TerminalController = { _sessionId: () => viewedId };
    w.API = {
        getSession: (id: string) => {
            asked.push(id);
            return Promise.resolve(sessions[id] ?? null);
        },
    };
    return asked;
}

afterEach(() => {
    delete (globalThis as Record<string, unknown>).window;
});

describe('currentProjectPath through the host', () => {
    test('answers the working dir of the session on screen, not another', async () => {
        const asked = plant('ses_b', {
            ses_a: { session: { working_dir: '/p/first' } },
            ses_b: { session: { working_dir: '/p/second' } },
        });
        expect(await browserCatalogHost().currentProjectPath()).toBe('/p/second');
        expect(asked).toEqual(['ses_b']);
    });

    test('is null when no session is on screen', async () => {
        const asked = plant(null, {});
        expect(await browserCatalogHost().currentProjectPath()).toBeNull();
        expect(asked).toEqual([]);
    });
});
