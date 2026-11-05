/* and writes nothing */
import { bridge, isSaved } from '../../zone-shell/preference-field';
import { legacyGlobal } from '../../legacy-globals';
import type { Translate } from '../../sessions/types';
import { RAIL_SPECS } from '../../session-rail/rail-model';
import { railStores } from '../../session-rail/rail-store.svelte';
import { widgetBars, type WriteResult } from '../../widget-bars/bar-settings.svelte';
import { closeToast, showToast } from '../undo-toast';
import { undoOps, type BarOp } from './settings-model';

export type Pick = () => { ops: BarOp[]; text: string };

const LANDED: readonly WriteResult[] = ['committed', 'replayed', 'unchanged'];
const RESET_FIELDS: readonly string[] = ['widget_bars', RAIL_SPECS.side.field, RAIL_SPECS.bottom.field];

const prefsLayer = (): { discardLocal?(field: string): void } | undefined => legacyGlobal<{ discardLocal?(field: string): void }>('Preferences');

let queue: Promise<unknown> = Promise.resolve();
const waiting = new Map<string, Pick>();

function enqueue(work: () => Promise<void>): Promise<void> {
    const task = queue.then(work).catch((error: unknown) => {
        console.warn('[widget bars settings] a write failed', error);
    });
    queue = task;
    return task;
}

function run(op: BarOp): Promise<WriteResult> {
    return op.kind === 'together' ? widgetBars.setTogether(op.value) : widgetBars.set(op.edge, op.patch);
}

async function runAll(ops: readonly BarOp[]): Promise<{ landed: number; stopped: WriteResult | null }> {
    let landed = 0;
    for (const op of ops) {
        const result = await run(op);
        if (!LANDED.includes(result)) return { landed, stopped: result };
        landed += 1;
    }
    return { landed, stopped: null };
}

const surfaceOf = (t: Translate): string => t('widgets.page.title');

function stoppedToast(result: WriteResult, retry: () => void, t: Translate): void {
    if (result === 'conflict') showToast({ kind: 'failed', text: t('widgets.settings.toast.conflict'), surface: surfaceOf(t) });
    else showToast({ kind: 'failed', text: t('widgets.page.toast.failed'), surface: surfaceOf(t), undo: { label: t('widgets.page.toast.retry'), run: () => { closeToast(); retry(); } } });
}

function savedToast(text: string, undo: () => void, t: Translate): void {
    showToast({ kind: 'saved', text, surface: surfaceOf(t), undo: { label: t('widgets.page.toast.undo'), run: () => { closeToast(); undo(); } }, ms: 8000 });
}

const undoneToast = (t: Translate): void => showToast({ kind: 'undone', text: t('widgets.page.toast.undone'), surface: surfaceOf(t), ms: 2000 });

function undoPick(back: readonly BarOp[], t: Translate): Promise<void> {
    return enqueue(async () => {
        const { landed, stopped } = await runAll(back);
        if (stopped === null) undoneToast(t);
        else if (landed > 0) showToast({ kind: 'failed', text: t('widgets.settings.toast.undo_partial'), surface: surfaceOf(t) });
        else stoppedToast(stopped, () => void undoPick(back, t), t);
    });
}

async function runPick(pick: Pick, t: Translate): Promise<void> {
    const { ops, text } = pick();
    if (ops.length === 0) return;
    const prior = widgetBars.stored;
    const { stopped } = await runAll(ops);
    if (stopped !== null) return stoppedToast(stopped, () => void applyPick(pickKeyOf(pick), pick, t), t);
    savedToast(text, () => void undoPick(undoOps(prior, ops), t), t);
}

const keys = new WeakMap<Pick, string>();
const pickKeyOf = (pick: Pick): string => keys.get(pick) ?? '';

export function applyPick(key: string, pick: Pick, t: Translate): Promise<void> {
    keys.set(pick, key);
    const alreadyWaiting = waiting.has(key);
    waiting.set(key, pick);
    if (alreadyWaiting) return queue as Promise<void>;
    return enqueue(async () => {
        const next = waiting.get(key);
        waiting.delete(key);
        if (next) await runPick(next, t);
    });
}

function snapshotReset(): Record<string, unknown> {
    const found = bridge();
    return Object.fromEntries(RESET_FIELDS.map((field) => {
        const raw = found?.read(field, () => null) ?? null;
        return [field, raw === null ? null : JSON.parse(JSON.stringify(raw))];
    }));
}

function undoReset(before: Record<string, unknown>, t: Translate): Promise<void> {
    return enqueue(async () => {
        const found = bridge();
        let landed = false;
        try {
            const sent = found ? await found.writeMany(RESET_FIELDS.map((field) => ({ field, value: before[field] ?? null, localWriter: () => {} }))) : null;
            landed = isSaved(sent);
        } catch (error) {
            console.warn('[widget bars settings] undo of reset threw', error);
        }
        if (!landed) for (const field of RESET_FIELDS) prefsLayer()?.discardLocal?.(field);
        widgetBars.reload();
        railStores.side.reload();
        railStores.bottom.reload();
        if (landed) undoneToast(t);
        else stoppedToast('failed', () => void undoReset(before, t), t);
    });
}

export function resetWithUndo(t: Translate): Promise<void> {
    return enqueue(async () => {
        const before = snapshotReset();
        const result = await widgetBars.reset();
        if (result === 'failed' || result === 'local_only') return stoppedToast('failed', () => void resetWithUndo(t), t);
        savedToast(t('widgets.settings.toast.reset'), () => void undoReset(before, t), t);
    });
}
