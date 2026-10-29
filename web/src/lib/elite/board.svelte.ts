import { ELITE_KEYS as K } from '../../../../client/js/labels/warez-elite.js';
import type { CardView } from '../catalog/card';
import { latestVersion } from '../catalog/card';
import type { Translate } from '../sessions/types';
import { mmdd } from './callers';
import type { EliteData } from './elite-data.svelte';
import { activeKeys, applyKey, areaNo, censusOf, listFor, nextSort, searchQuery, START, type ActiveKeys, type BoardQuery, type Census, type Source } from './query';

export interface BoardHooks {
    hangup: () => void;
    publish: () => void;
    help: () => void;
    focusCommand: () => void;
}

export interface Echo {
    cmd: string;
    text: string;
}

export interface Board {
    readonly q: BoardQuery;
    readonly items: readonly CardView[];
    readonly census: Census;
    readonly on: ActiveKeys;
    readonly sel: string | null;
    readonly tagged: ReadonlySet<string>;
    readonly taggedBytes: number;
    readonly echo: Echo;
    readonly areaNumber: number;
    run(key: string): boolean;
    command(line: string): void;
    escape(): boolean;
    move(by: number): void;
    select(id: string | null): void;
    selectAt(index: number): void;
    toggleTag(id?: string | null): void;
    untag(ids: Iterable<string>): void;
    clearTags(): number;
    say(text: string, cmd: string): void;
    reset(): void;
}

export function createBoard(data: EliteData, t: Translate, hooks: BoardHooks): Board {
    let q = $state<BoardQuery>({ ...START });
    let sel = $state<string | null>(null);
    let tagged = $state.raw<ReadonlySet<string>>(new Set());
    let echo = $state<Echo>({ cmd: '', text: '' });

    const source = $derived<Source>({ cards: data.cards, items: data.listing, installed: data.installed, installs: data.installs, fresh: data.fresh });
    const items = $derived(listFor(source, q));
    const census = $derived(censusOf(source, q));
    const on = $derived(activeKeys(q));
    const bar = $derived(items.some((c) => c.id === sel) ? sel : (items[0]?.id ?? null));
    const taggedBytes = $derived.by(() => {
        let n = 0;
        for (const item of data.listing) if (item.id && tagged.has(String(item.id))) n += Number(latestVersion(item)?.size ?? 0) || 0;
        return n;
    });

    function say(text: string, cmd: string): void {
        echo = { cmd, text };
    }
    function set(next: BoardQuery): void {
        q = next;
    }
    function selectAt(i: number): void {
        const row = items[Math.max(0, Math.min(items.length - 1, i))];
        if (row?.id) sel = row.id;
    }
    function move(by: number): void {
        if (!items.length) return;
        selectAt(Math.max(0, items.findIndex((c) => c.id === bar)) + by);
    }
    function toggleTag(id?: string | null): void {
        const at = id ?? bar;
        if (!at) return;
        const next = new Set(tagged);
        if (!next.delete(at)) next.add(at);
        tagged = next;
        say(t(K.echoTagged, { n: next.size, count: next.size }), 'tag');
    }

    function untag(ids: Iterable<string>): void {
        const next = new Set(tagged);
        for (const id of ids) next.delete(id);
        tagged = next;
    }
    function clearTags(): number {
        const n = tagged.size;
        tagged = new Set();
        return n;
    }

    async function redial(): Promise<void> {
        const wasOffline = data.offline;
        say(t(wasOffline ? K.echoRedialing : K.echoRefreshing), 'r');
        await data.redial();
        if (data.offline) say(t(K.echoNocarrier), 'r');
        else say(t(wasOffline ? K.echoConnected : K.echoRefreshed, { n: data.files }), 'r');
    }

    function sayFor(key: string): void {
        const n = items.length;
        const text = q.view === 'top' ? t(K.echoTop) : q.view === 'new' ? (data.lastCall ? t(K.echoNew, { n, last: mmdd(Date.parse(data.lastCall)) }) : t(K.echoNewest, { n })) : t(K.echoCount, { n, total: census.total, sort: t(`warez.elite.sort.${q.sort}`) });
        say(text, key);
    }

    function run(key: string): boolean {
        const next = applyKey(q, key);
        if (next) {
            set(next);
            sayFor(key);
            return true;
        }
        if (key === '/') {
            hooks.focusCommand();
            say(t(K.echoSearch), '/');
        } else if (key === 'r') void redial();
        else if (key === 'b') hooks.publish();
        else if (key === '?') hooks.help();
        else if (key === 'g') hooks.hangup();
        else {
            say(t(K.echoUnknown, { key }), key);
            return false;
        }
        return true;
    }

    function search(text: string): void {
        set(searchQuery(q, text));
        say(items.length ? t(K.echoFound, { n: items.length }) : t(K.echoNone, { q: q.q }), `/${q.q}`);
    }

    function command(line: string): void {
        const c = line.trim();
        if (!c) return;
        if (c.length === 1 && /^[a-z/?]$/i.test(c)) {
            run(c.toLowerCase());
            return;
        }
        if (c === 'tag') toggleTag();
        else if (c === 'sort') {
            set({ ...q, sort: nextSort(q.sort), view: null });
            say(t(K.echoSorted, { sort: t(`warez.elite.item.${q.sort}`) }), 'sort');
        } else search(c);
    }

    function escape(): boolean {
        if (!(q.q || q.view || q.state !== 'any' || q.kind !== 'all')) return false;
        run('a');
        return true;
    }

    return {
        get q() { return q; },
        get items() { return items; },
        get census() { return census; },
        get on() { return on; },
        get sel() { return bar; },
        get tagged() { return tagged; },
        get taggedBytes() { return taggedBytes; },
        get echo() { return echo; },
        get areaNumber() { return areaNo(q); },
        run,
        command,
        escape,
        move,
        select: (id) => { sel = id; },
        selectAt,
        toggleTag,
        untag,
        clearTags,
        say,
        reset: () => {
            q = { ...START };
            sel = null;
            tagged = new Set();
        },
    };
}
