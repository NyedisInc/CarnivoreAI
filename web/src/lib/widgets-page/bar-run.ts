import { bridge } from '../zone-shell/preference-field';
import { zoneItemKey, type ZoneItem } from '../drawer-zone/zone-model';
import { placeInRail, railEnd, railStores } from '../session-rail/rail-store.svelte';
import { RAIL_SPECS, type RailEdge } from '../session-rail/rail-model';
import type { Translate } from '../sessions/types';
import { barActionsFor, restorePlan, type BarAction } from './bar-placement';
import { bounded, contents, performContents, stillAt, type SaveResult } from './save-outcome';
import { closeToast, showToast } from './undo-toast';

export function barName(edge: RailEdge, t: Translate): string {
    return t(edge === 'side' ? 'widgets.page.bars.side' : 'widgets.page.bars.bottom');
}

function heldIn(edge: RailEdge, widget: string): ZoneItem | undefined {
    return railStores[edge].items.find((item) => item.widget === widget);
}

function apply(action: BarAction, widget: string): void {
    if (action.kind === 'take_out') {
        const held = heldIn(action.edge, widget);
        if (held) railStores[action.edge].remove(zoneItemKey(held));
    } else if (action.kind === 'move') {
        const from: RailEdge = action.edge === 'side' ? 'bottom' : 'side';
        const held = heldIn(from, widget);
        placeInRail(action.edge, widget, railEnd(action.edge), undefined, held);
    } else {
        placeInRail(action.edge, widget);
    }
}

function savedText(action: BarAction, name: string, t: Translate): string {
    const key = action.kind === 'add' ? 'added' : action.kind === 'move' ? 'moved' : 'taken_out';
    return t(`widgets.page.bars.${key}`, { widget: name, bar: barName(action.edge, t) });
}

async function writeBack(result: SaveResult): Promise<'landed' | 'failed' | 'unconfirmed'> {
    const found = bridge();
    const plan = restorePlan(result.written, result.before, result.after);
    const sent = found ? await bounded(found.writeMany(plan.map((edge) => ({ field: RAIL_SPECS[edge].field, value: result.raw[edge], localWriter: () => {} })))) : null;
    for (const edge of plan) railStores[edge].reload();
    if (sent === 'timedOut') return 'unconfirmed';
    const answer = sent ? (sent.value as { status?: string } | null) : null;
    return answer?.status === 'committed' || answer?.status === 'unchanged' ? 'landed' : 'failed';
}

function undo(result: SaveResult, t: Translate): void {
    closeToast();
    void contents.enqueue(async () => {
        if (!stillAt(result.written, result.after)) return;
        const landed = await writeBack(result);
        if (landed === 'landed') showToast({ kind: 'undone', text: t('widgets.page.toast.undone'), surface: t('widgets.page.title'), ms: 2000 });
        else showToast({ kind: 'failed', text: t(landed === 'unconfirmed' ? 'widgets.page.bars.not_confirmed' : 'widgets.page.bars.save_failed'), surface: t('widgets.page.title') });
    });
}

export function editBars(run: () => void, text: string, t: Translate, stillValid: () => boolean = () => true): void {
    void contents.enqueue(async () => {
        if (!stillValid()) return;
        const result = await performContents(run);
        if (result.verdict === 'none') return;
        if (result.verdict !== 'saved') {
            showToast({ kind: 'failed', text: t(result.verdict === 'unconfirmed' ? 'widgets.page.bars.not_confirmed' : 'widgets.page.bars.save_failed'), surface: t('widgets.page.title') });
            return;
        }
        const canUndo = bridge() !== null && stillAt(result.written, result.after);
        showToast({
            kind: 'saved',
            text,
            surface: t('widgets.page.title'),
            undo: canUndo ? { label: t('widgets.page.toast.undo'), run: () => undo(result, t) } : undefined,
        });
    });
}

export function pressBar(action: BarAction, widget: string, name: string, t: Translate): void {
    editBars(() => apply(action, widget), savedText(action, name, t), t, () =>
        barActionsFor(widget, railStores.side.items, railStores.bottom.items).actions.some((one) => one.kind === action.kind && one.edge === action.edge),
    );
}
