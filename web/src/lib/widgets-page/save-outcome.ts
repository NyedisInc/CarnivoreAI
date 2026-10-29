import { bridge } from '../zone-shell/preference-field';
import { railStores } from '../session-rail/rail-store.svelte';
import { RAIL_EDGES, RAIL_SPECS, type RailEdge } from '../session-rail/rail-model';
import type { RailLayout } from '../session-rail/rail-sections';
import { writtenRails, type RailSnap } from './bar-placement';

interface PreferencesLayer {
    subscribe(listener: (name: string, value: unknown, record: { state?: string }) => void): () => void;
    stateFor(name: string): string;
}

export const SAVE_WAIT_MS = 15000;

export type SaveVerdict = 'none' | 'saved' | 'failed' | 'conflict' | 'unconfirmed';

export async function bounded<T>(work: Promise<T>, ms: number = SAVE_WAIT_MS): Promise<{ value: T } | 'timedOut'> {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const late = new Promise<'timedOut'>((resolve) => {
        timer = setTimeout(() => resolve('timedOut'), ms);
    });
    try {
        return await Promise.race([work.then((value) => ({ value })), late]);
    } finally {
        clearTimeout(timer);
    }
}

export interface SaveResult {
    verdict: SaveVerdict;
    written: RailEdge[];
    before: RailSnap;
    after: RailSnap;
    raw: Record<RailEdge, unknown>;
}

function layer(): PreferencesLayer | null {
    const found = (globalThis as { Preferences?: Partial<PreferencesLayer> }).Preferences;
    return found && typeof found.subscribe === 'function' && typeof found.stateFor === 'function' ? (found as PreferencesLayer) : null;
}

function copy(layout: RailLayout | null): RailLayout | null {
    return layout === null ? null : (JSON.parse(JSON.stringify(layout)) as RailLayout);
}

export function snapshotRails(): RailSnap {
    return { side: copy(railStores.side.stored), bottom: copy(railStores.bottom.stored) };
}

function rawRails(): Record<RailEdge, unknown> {
    const found = bridge();
    const read = (edge: RailEdge): unknown => (found ? (found.read(RAIL_SPECS[edge].field, () => null) ?? null) : null);
    return { side: read('side'), bottom: read('bottom') };
}

interface FieldWatch {
    pending: boolean;
    final: string | null;
}

export async function performContents(run: () => void, waitMs: number = SAVE_WAIT_MS): Promise<SaveResult> {
    const prefs = layer();
    const before = snapshotRails();
    const raw = rawRails();
    const watches = new Map<string, FieldWatch>();
    const field = (edge: RailEdge): string => RAIL_SPECS[edge].field;
    for (const edge of RAIL_EDGES) watches.set(field(edge), { pending: false, final: null });
    let wake: (() => void) | null = null;
    const unsubscribe =
        prefs?.subscribe((name, _value, record) => {
            const watch = watches.get(name);
            if (!watch || !record?.state) return;
            if (record.state === 'pending') watch.pending = true;
            else if (watch.pending && watch.final === null) {
                watch.final = record.state;
                wake?.();
            }
        }) ?? (() => {});
    try {
        run();
        const after = snapshotRails();
        const written = writtenRails(before, after);
        const done = (verdict: SaveVerdict): SaveResult => ({ verdict, written, before, after, raw });
        if (written.length === 0) return done('none');
        const refused = written.filter((edge) => !watches.get(field(edge))?.pending);
        if (refused.length > 0) {
            for (const edge of refused) railStores[edge].reload();
            return done('failed');
        }
        const settled = (): boolean => written.every((edge) => watches.get(field(edge))?.final !== null);
        const landed = settled() || (await bounded(new Promise<void>((resolve) => (wake = () => settled() && resolve())), waitMs)) !== 'timedOut';
        if (!landed) return done('unconfirmed');
        const states = written.map((edge) => watches.get(field(edge))?.final ?? '');
        if (states.some((state) => state === 'failed') || written.some((edge) => prefs?.stateFor(field(edge)) === 'failed')) return done('failed');
        if (states.some((state) => state === 'conflict') || written.some((edge) => prefs?.stateFor(field(edge)) === 'conflict')) return done('conflict');
        return done('saved');
    } finally {
        unsubscribe();
    }
}

export function stillAt(written: readonly RailEdge[], after: RailSnap): boolean {
    return written.every((edge) => JSON.stringify(railStores[edge].stored) === JSON.stringify(after[edge]));
}

export interface ContentsQueue {
    enqueue<T>(job: () => Promise<T> | T): Promise<T>;
}

export function createContentsQueue(): ContentsQueue {
    let tail: Promise<unknown> = Promise.resolve();
    return {
        enqueue<T>(job: () => Promise<T> | T): Promise<T> {
            const next = tail.then(job, job);
            tail = next.catch(() => undefined);
            return next;
        },
    };
}

export const contents: ContentsQueue = createContentsQueue();
