import { afterEach, describe, expect, it, vi } from 'vitest';
import { BOOST_CAP, createRanker, initials, notePick, prunePicks, boost, type PickStore } from './palette-rank';
import { commitChip, parseQuery, passesChips, rankText } from './palette-query';
import { createDeepRunner, DEEP_DEBOUNCE_MS } from './palette-deep';
import type { DeepSearchApi } from '../deepsearch/deepsearch-api';

const item = (title: string, id = title) => ({ id, title });
const rank = (titles: string[], q: string, store: PickStore = {}) => createRanker(() => store).rank(titles.map((x) => item(x)), q).map((i) => i.title);

describe('ranking', () => {
    it('each tier beats the next: exact, prefix, word start or initials, contains, in order, typo', () => {
        expect(rank(['xapix', 'axpxi', 'my api', 'apis', 'api'], 'api')).toEqual(['api', 'apis', 'my api', 'xapix', 'axpxi']);
        expect(rank(['Cv-Misc UI', 'cmux'], 'cmu')).toEqual(['cmux', 'Cv-Misc UI']);
        expect(initials('Cv-Misc UI')).toBe('cmu');
    });
    it('uses one typo only when nothing better exists', () => {
        expect(rank(['gateway', 'other'], 'gatewya')).toEqual(['gateway']);
        expect(rank(['getaway', 'gate'], 'gate')).toEqual(['gate']);
    });
    it('a learned pick wins inside its tier', () => {
        const store: PickStore = {};
        notePick(store, 'api-gateway', 'api', Date.now());
        expect(rank(['api-docs', 'api-gateway'], 'api', store)[0]).toBe('api-gateway');
    });
    it('frecency is capped, so a habit never beats a better tier', () => {
        const now = Date.now();
        const store: PickStore = { 'my api': { queries: [], opens: Array.from({ length: 50 }, (_, i) => now - i * 3600_000) } };
        expect(boost(store['my api']!.opens, now)).toBe(BOOST_CAP);
        expect(rank(['my api', 'apis'], 'ap', store)).toEqual(['apis', 'my api']);
    });
    it('keeps a stable order: shorter name, then id', () => {
        expect(rank(['abc-2', 'abc-1', 'abc'], 'ab')).toEqual(['abc', 'abc-1', 'abc-2']);
    });
    it('opens within 10 minutes count once, and memory prunes to what exists', () => {
        const store: PickStore = {};
        const now = Date.now();
        notePick(store, 'a', 'x', now);
        notePick(store, 'a', 'y', now + 60_000);
        expect(store.a!.opens.length).toBe(1);
        expect(store.a!.queries).toEqual(['y', 'x']);
        expect(Object.keys(prunePicks({ ...store, gone: { queries: [], opens: [now] } }, new Set(['a'])))).toEqual(['a']);
    });
    it('ranks 2,000 items in under 5 ms per keystroke', () => {
        const items = Array.from({ length: 2000 }, (_, i) => item(`session-${i}-carnivore api worker ${i % 97}`, `s${i}`));
        const ranker = createRanker(() => ({}));
        ranker.rank(items, 'c');
        const start = performance.now();
        const typed = ['ca', 'car', 'carn', 'carni', 'carniv'];
        for (const q of typed) ranker.rank(items, q);
        expect((performance.now() - start) / typed.length).toBeLessThan(5);
    });
});

describe('grammar', () => {
    const known = { host: ['studio', 'this computer'], project: ['carnivore', 'api'], state: ['waiting', 'idle'] };
    it('reads the mode character', () => {
        expect(parseQuery('>restart').mode).toBe('actions');
        expect(parseQuery('?token refresh')).toMatchObject({ mode: 'deep', text: 'token refresh' });
        expect(parseQuery('auth').mode).toBe('go');
    });
    it('turns a known token into a chip and chips stack', () => {
        const first = commitChip('api @st', known)!;
        expect(first).toEqual({ chip: { kind: 'host', value: 'studio' }, rest: 'api ' });
        const second = commitChip(first.rest + '#carn', known)!;
        expect(second.chip).toEqual({ kind: 'project', value: 'carnivore' });
        expect(passesChips({ host: 'studio', project: 'carnivore', states: ['waiting'] }, [first.chip, second.chip, { kind: 'state', value: 'waiting' }])).toBe(true);
        expect(passesChips({ host: 'studio', project: 'api' }, [first.chip, second.chip])).toBe(false);
    });
    it('a sigil only counts at the start of a word, and an unknown token stays text', () => {
        expect(parseQuery('foo#bar').pending).toBeNull();
        expect(commitChip('#hotfix', known)).toBeNull();
        expect(rankText(parseQuery('api #car'))).toBe('api');
    });
});

describe('conversation search', () => {
    afterEach(() => vi.useRealTimers());
    it('sends one request 250 ms after typing stops, none under 3 characters, and cancels on close', async () => {
        vi.useFakeTimers();
        const search = vi.fn((_q: string, _o: number, signal: AbortSignal) => new Promise<{ groups: [] }>((resolve) => {
            signal.addEventListener('abort', () => resolve({ groups: [] }));
        }));
        const api = { search } as unknown as DeepSearchApi;
        const results = vi.fn();
        const runner = createDeepRunner(results, api);
        runner.query('to');
        runner.query('tok');
        runner.query('token');
        vi.advanceTimersByTime(DEEP_DEBOUNCE_MS - 1);
        expect(search).not.toHaveBeenCalled();
        vi.advanceTimersByTime(1);
        expect(search).toHaveBeenCalledTimes(1);
        expect(search.mock.calls[0]![0]).toBe('token');
        const signal = search.mock.calls[0]![2];
        runner.cancel();
        expect(signal.aborted).toBe(true);
    });
});
