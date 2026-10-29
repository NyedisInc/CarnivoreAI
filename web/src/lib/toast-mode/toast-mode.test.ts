import { afterEach, describe, expect, it } from 'vitest';
import { TOAST_MODE_FIELD, asMode, followToastMode, readToastMode, saveToastMode } from './toast-mode';

type G = { PreferenceBridge?: unknown };
type Follower = (value: unknown) => void;

function install(stored: unknown, answer: unknown = { status: 'committed' }) {
    const writes: Array<[string, unknown]> = [];
    const followers: Array<[string, Follower]> = [];
    (globalThis as G).PreferenceBridge = {
        read: (field: string, local: () => unknown) =>
            (field === TOAST_MODE_FIELD && stored !== undefined ? stored : local()),
        write: async (field: string, value: unknown, local: () => void) => {
            local();
            writes.push([field, value]);
            return answer;
        },
        follow: (field: string, apply: Follower) => {
            followers.push([field, apply]);
            return () => followers.splice(0, followers.length);
        },
    };
    return { writes, followers };
}

afterEach(() => {
    delete (globalThis as G).PreferenceBridge;
});

describe('toast style', () => {
    it('reads compact with no bridge on the page', () => {
        expect(readToastMode()).toBe('compact');
    });

    it.each([undefined, null, 'compact', 'loud', true, 1])('reads compact for %s', (stored) => {
        install(stored);
        expect(readToastMode()).toBe('compact');
    });

    it('reads detailed only for a stored detailed', () => {
        install('detailed');
        expect(readToastMode()).toBe('detailed');
    });

    it('saves the field through the bridge', async () => {
        const { writes } = install(undefined);
        expect(await saveToastMode('detailed')).toBeNull();
        expect(writes).toEqual([[TOAST_MODE_FIELD, 'detailed']]);
    });

    it('treats unchanged as saved', async () => {
        install('detailed', { status: 'unchanged' });
        expect(await saveToastMode('detailed')).toBeNull();
    });

    it('returns the reason when the save is refused', async () => {
        install(undefined, { status: 'refused', detail: 'preferences have not been read yet' });
        expect(await saveToastMode('detailed')).toBe('preferences have not been read yet');
    });

    it('says unavailable with no bridge', async () => {
        expect(await saveToastMode('detailed')).toBe('unavailable');
    });

    it('hands a follower a normalised mode, for its own field only', () => {
        const { followers } = install(undefined);
        const seen: string[] = [];
        const stop = followToastMode((mode) => seen.push(mode));
        expect(followers.map(([field]) => field)).toEqual([TOAST_MODE_FIELD]);
        const apply = followers[0]?.[1];
        expect(apply).toBeTypeOf('function');
        apply?.('detailed');
        apply?.('bogus');
        expect(seen).toEqual(['detailed', 'compact']);
        stop();
        expect(followers).toHaveLength(0);
    });

    it('asMode keeps only the exact string', () => {
        expect(asMode('detailed')).toBe('detailed');
        expect(asMode('Detailed')).toBe('compact');
    });
});
