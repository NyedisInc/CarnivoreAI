import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

const world = vi.hoisted(() => {
    type Layout = { sections: { items: { widget: string }[] }[] } | null;
    const store = (edge: string) => ({
        edge,
        stored: null as Layout,
        get items(): { widget: string }[] {
            return this.stored ? this.stored.sections.flatMap((s) => s.items) : [];
        },
        reload: vi.fn(),
        remove: vi.fn(),
        start: vi.fn(),
    });
    return {
        side: store('side'),
        bottom: store('bottom'),
        listeners: new Set<(name: string, value: unknown, record: { state?: string }) => void>(),
        states: {} as Record<string, string>,
        open: [] as string[],
        refuse: false,
        raw: {} as Record<string, unknown>,
        writeMany: vi.fn(),
    };
});

vi.mock('../zone-shell/preference-field', () => ({
    bridge: () => ({ read: (field: string) => world.raw[field] ?? null, writeMany: world.writeMany }),
}));

vi.mock('../session-rail/rail-store.svelte', () => {
    const fieldOf = (edge: string): string => (edge === 'side' ? 'session_rail' : 'session_rail_bottom');
    const begin = (edges: string[]): void => {
        if (world.refuse) return;
        for (const edge of edges) emit(fieldOf(edge), 'pending');
        world.open.push(...edges.map(fieldOf));
    };
    const emit = (field: string, state: string): void => {
        world.states[field] = state;
        for (const listener of [...world.listeners]) listener(field, null, { state });
    };
    const put = (edge: 'side' | 'bottom', widget: string): void => {
        const rail = world[edge];
        const items = [...rail.items, { widget }];
        rail.stored = { sections: [{ items }] };
    };
    const drop = (edge: 'side' | 'bottom', widget: string): void => {
        const rail = world[edge];
        rail.stored = { sections: [{ items: rail.items.filter((item) => item.widget !== widget) }] };
    };
    world.side.remove.mockImplementation((key: string) => {
        drop('side', key);
        begin(['side']);
    });
    world.bottom.remove.mockImplementation((key: string) => {
        drop('bottom', key);
        begin(['bottom']);
    });
    return {
        railStores: { side: world.side, bottom: world.bottom },
        railEnd: () => 0,
        placeInRail: vi.fn((edge: 'side' | 'bottom', widget: string, _end?: unknown, _x?: unknown, held?: unknown) => {
            const other = edge === 'side' ? 'bottom' : 'side';
            if (held) drop(other, widget);
            put(edge, widget);
            begin(held ? [edge, other] : [edge]);
        }),
    };
});

import { pressBar } from './bar-run';
import { SAVE_WAIT_MS } from './save-outcome';
import { closeToast } from './undo-toast';
import { placeInRail } from '../session-rail/rail-store.svelte';

const t = (key: string): string => key;

const cards = new Map<string, Record<string, unknown>>();
const manager = {
    add: vi.fn((card: Record<string, unknown>) => void cards.set(card['id'] as string, card)),
    dismiss: vi.fn((id: string) => void cards.delete(id)),
};

const toast = {
    get live(): Record<string, unknown> | undefined { return [...cards.values()][0]; },
    get kind(): 'none' | 'saved' | 'undone' | 'failed' {
        const card = this.live;
        if (!card) return 'none';
        if (card['alert_severity'] === 'error') return 'failed';
        return card['title'] === 'widgets.page.toast.undone' ? 'undone' : 'saved';
    },
    get text(): string { return String(this.live?.['title'] ?? ''); },
    get undo(): (() => void) | null { const run = this.live?.['on_action']; return typeof run === 'function' ? (run as () => void) : null; },
};

function finish(state: string): void {
    for (const field of world.open.splice(0)) {
        world.states[field] = state;
        for (const listener of [...world.listeners]) listener(field, null, { state });
    }
}

const flush = async (): Promise<void> => { await vi.advanceTimersByTimeAsync(0); };

beforeEach(() => {
    vi.useFakeTimers();
    cards.clear();
    manager.add.mockClear();
    manager.dismiss.mockClear();
    (globalThis as Record<string, unknown>)['ToastManager'] = manager;
    (globalThis as Record<string, unknown>)['Preferences'] = {
        subscribe: (listener: (name: string, value: unknown, record: { state?: string }) => void) => {
            world.listeners.add(listener);
            return () => world.listeners.delete(listener);
        },
        stateFor: (field: string) => world.states[field] ?? '',
    };
    world.side.stored = null;
    world.bottom.stored = null;
    world.states = {};
    world.open = [];
    world.refuse = false;
    world.raw = {};
    world.writeMany.mockReset();
    world.side.reload.mockClear();
    world.bottom.reload.mockClear();
    vi.mocked(placeInRail).mockClear();
    closeToast();
});

afterEach(() => {
    vi.useRealTimers();
    delete (globalThis as Record<string, unknown>)['Preferences'];
    delete (globalThis as Record<string, unknown>)['ToastManager'];
});

describe('a contents write is reported as what it was', () => {
    test('add: a committed save shows the added toast with undo', async () => {
        pressBar({ kind: 'add', edge: 'bottom' }, 'core.notes', 'notes', t);
        await flush();
        expect(toast.kind, 'no toast while the save is in flight').toBe('none');
        finish('committed');
        await flush();
        expect(toast.kind).toBe('saved');
        expect(toast.text).toBe('widgets.page.bars.added');
        expect(toast.undo).not.toBeNull();
    });

    test('409: a lost save is never shown as saved', async () => {
        pressBar({ kind: 'add', edge: 'bottom' }, 'core.notes', 'notes', t);
        await flush();
        finish('conflict');
        await flush();
        expect(toast.kind).toBe('failed');
        expect(toast.text).toBe('widgets.page.bars.save_failed');
        expect(toast.undo).toBeNull();
    });

    test('a failed save is never shown as saved', async () => {
        pressBar({ kind: 'add', edge: 'side' }, 'core.notes', 'notes', t);
        await flush();
        finish('failed');
        await flush();
        expect(toast.kind).toBe('failed');
    });

    test('a refused save (no save ever started) is failed and the rail is re-read', async () => {
        world.refuse = true;
        pressBar({ kind: 'add', edge: 'bottom' }, 'core.notes', 'notes', t);
        await flush();
        expect(toast.kind).toBe('failed');
        expect(world.bottom.reload).toHaveBeenCalledTimes(1);
    });

    test('move: both rails settle, one moved toast', async () => {
        world.side.stored = { sections: [{ items: [{ widget: 'core.notes' }] }] };
        pressBar({ kind: 'move', edge: 'bottom' }, 'core.notes', 'notes', t);
        await flush();
        finish('committed');
        await flush();
        expect(toast.kind).toBe('saved');
        expect(toast.text).toBe('widgets.page.bars.moved');
    });

    test('take out: a committed save shows the took-out toast; a conflict shows the failure', async () => {
        world.bottom.stored = { sections: [{ items: [{ widget: 'core.notes' }] }] };
        pressBar({ kind: 'take_out', edge: 'bottom' }, 'core.notes', 'notes', t);
        await flush();
        finish('committed');
        await flush();
        expect(toast.text).toBe('widgets.page.bars.taken_out');
        closeToast();
        world.bottom.stored = { sections: [{ items: [{ widget: 'core.notes' }] }] };
        pressBar({ kind: 'take_out', edge: 'bottom' }, 'core.notes', 'notes', t);
        await flush();
        finish('conflict');
        await flush();
        expect(toast.kind).toBe('failed');
    });

    test('undo: writes the previous raw value back, and says undone only when that write committed', async () => {
        world.raw['session_rail_bottom'] = null;
        pressBar({ kind: 'add', edge: 'bottom' }, 'core.notes', 'notes', t);
        await flush();
        finish('committed');
        await flush();
        world.writeMany.mockResolvedValueOnce({ status: 'conflict' });
        toast.undo!();
        await flush();
        expect(world.writeMany).toHaveBeenCalledTimes(1);
        expect(world.writeMany.mock.calls[0]![0]).toMatchObject([{ field: 'session_rail_bottom', value: null }]);
        expect(toast.kind, 'a refused undo is not "undone"').toBe('failed');
        pressBar({ kind: 'take_out', edge: 'bottom' }, 'core.notes', 'notes', t);
        await flush();
        finish('committed');
        await flush();
        world.writeMany.mockResolvedValueOnce({ status: 'committed' });
        toast.undo!();
        await flush();
        expect(toast.kind).toBe('undone');
    });
});

describe('the toast is a card on the one ToastManager (T-6)', () => {
    test('a confirmed save posts one local card with an undo action; the undo retires it; a new toast replaces the old', async () => {
        pressBar({ kind: 'add', edge: 'bottom' }, 'core.notes', 'notes', t);
        await flush();
        finish('committed');
        await flush();
        expect(manager.add).toHaveBeenCalledTimes(1);
        expect(manager.add.mock.calls[0]![0]).toMatchObject({
            session_id: null, kind: 'WidgetsBars', title: 'widgets.page.bars.added', local: true, action_label: 'widgets.page.toast.undo', session_label: 'widgets.page.title',
        });
        expect(typeof manager.add.mock.calls[0]![0]['on_action']).toBe('function');
        const first = manager.add.mock.calls[0]![0]['id'] as string;
        world.writeMany.mockResolvedValueOnce({ status: 'committed' });
        toast.undo!();
        await flush();
        expect(manager.dismiss, 'the old card went before the next').toHaveBeenCalledWith(first, { syncToServer: false });
        expect(cards.size).toBe(1);
        expect(toast.kind).toBe('undone');
        await vi.advanceTimersByTimeAsync(2000);
        expect(cards.size, 'the undone card leaves after 2 s').toBe(0);
    });

    test('with no ToastManager loaded nothing is raised and nothing throws', async () => {
        delete (globalThis as Record<string, unknown>)['ToastManager'];
        pressBar({ kind: 'add', edge: 'bottom' }, 'core.notes', 'notes', t);
        await flush();
        finish('committed');
        await flush();
        expect(manager.add).not.toHaveBeenCalled();
    });
});

describe('undo only restores what this press wrote', () => {
    test('a rail changed by someone else since the press is left alone: undo writes nothing', async () => {
        world.raw['session_rail_bottom'] = null;
        pressBar({ kind: 'add', edge: 'bottom' }, 'core.notes', 'notes', t);
        await flush();
        finish('committed');
        await flush();
        world.bottom.stored = { sections: [{ items: [{ widget: 'core.notes' }, { widget: 'core.files' }] }] };
        toast.undo!();
        await flush();
        expect(world.writeMany, 'the guard stops the write').not.toHaveBeenCalled();
    });
});

describe('a hung save never stalls the page (V5)', () => {
    test('a never-settling save ends not confirmed, and the next press still runs', async () => {
        pressBar({ kind: 'add', edge: 'bottom' }, 'core.notes', 'notes', t);
        pressBar({ kind: 'add', edge: 'side' }, 'core.files', 'files', t);
        await flush();
        expect(vi.mocked(placeInRail), 'the second press waits its turn').toHaveBeenCalledTimes(1);
        await vi.advanceTimersByTimeAsync(SAVE_WAIT_MS);
        expect(vi.mocked(placeInRail), 'after the bound the second press runs').toHaveBeenCalledTimes(2);
        expect(toast.kind).not.toBe('saved');
        finish('committed');
        await flush();
    });

    test('the first press reads "not confirmed", never saved, and the save is not cancelled', async () => {
        pressBar({ kind: 'add', edge: 'bottom' }, 'core.notes', 'notes', t);
        await flush();
        await vi.advanceTimersByTimeAsync(SAVE_WAIT_MS);
        expect(toast.kind).toBe('failed');
        expect(toast.text).toBe('widgets.page.bars.not_confirmed');
        expect(toast.undo).toBeNull();
        expect(world.open, 'the in-flight save is left running').toEqual(['session_rail_bottom']);
    });

    test('a hung undo write ends not confirmed and frees the queue', async () => {
        pressBar({ kind: 'add', edge: 'bottom' }, 'core.notes', 'notes', t);
        await flush();
        finish('committed');
        await flush();
        world.writeMany.mockReturnValueOnce(new Promise(() => {}));
        toast.undo!();
        await vi.advanceTimersByTimeAsync(SAVE_WAIT_MS);
        expect(toast.kind).toBe('failed');
        expect(toast.text).toBe('widgets.page.bars.not_confirmed');
    });
});
