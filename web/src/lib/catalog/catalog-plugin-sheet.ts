import { tick } from 'svelte';
import { openModal } from '../modal';
import { isRuntimeDisabledDetail } from '../plugins-page/install-sheet-model';
import type { StoreCplugRow } from '../plugins/store.svelte';
import type { ProjectRow, Translate } from '../sessions/types';
import type { CardView } from './card';
import type { CatalogHost } from './catalog';
import type { CatalogData } from './catalog-data.svelte';
import InstallSheet from './InstallSheet.svelte';
import type { KeyAction } from './keys';
import { quickAdd } from './quick-add';
import type { InstalledItem, SheetOutcome } from './types';
import { runUpdate } from './update-flow';

export interface CatalogSheetPrefill {
    readonly scope: 'global' | 'project';
    readonly projectPath: string | null;
}

export interface CatalogPluginSheetState {
    readonly card: CardView;
    readonly prefill: CatalogSheetPrefill | null;
}

export interface CatalogProjectOption {
    readonly path: string;
    readonly name: string;
}

export function deriveCatalogRuntimeActive(rows: readonly StoreCplugRow[]): boolean | undefined {
    const sidecars = rows.filter((row) => row.runtime === 'sidecar');
    if (sidecars.length === 0) return undefined;
    const inactive = sidecars.some(
        (row) =>
            (row as { readonly runtime_active?: boolean }).runtime_active === false ||
            isRuntimeDisabledDetail(row.detail),
    );
    return inactive ? false : true;
}

export function catalogProjectOptions(rows: readonly ProjectRow[]): CatalogProjectOption[] {
    return rows.flatMap((r) =>
        r.path || r.root ? [{ path: (r.path || r.root)!, name: r.name || (r.path || r.root)! }] : [],
    );
}

export async function runCatalogPluginUpdateIfDue(args: {
    readonly card: CardView;
    readonly prefill: CatalogSheetPrefill | null;
    readonly host: CatalogHost;
    readonly data: CatalogData;
    readonly t: Translate;
}): Promise<boolean> {
    const { card, prefill, host, data, t } = args;
    const id = card.id;
    if (!id || prefill !== null || card.revoked) return false;
    if (data.stateFor(id).kind !== 'update-available') return false;
    const rows = data.installed[id] ?? [];
    const targetRow = rows.find((r) => r.update_available === true) ?? rows[0];
    if (!targetRow) return false;
    const result = await runUpdate(
        {
            host,
            t,
            name: card.headline ?? card.name ?? id,
            card,
            installed: targetRow,
        },
        () => {
            data.send(id, { kind: 'verify' });
            data.send(id, { kind: 'install' });
        },
    );
    if (result.kind === 'updated') {
        data.send(id, { kind: 'installed' });
        data.setInstalled(id, result.row);
    } else if (result.kind === 'failed') {
        data.send(
            id,
            result.outcome.kind === 'refused'
                ? { kind: 'refused', code: result.outcome.code }
                : { kind: 'refused', code: result.outcome.kind },
        );
    }
    return true;
}

export async function openLegacyInstallSheet(args: {
    readonly card: CardView;
    readonly host: CatalogHost;
    readonly data: CatalogData;
    readonly t: Translate;
    readonly prefill: CatalogSheetPrefill | null;
}): Promise<void> {
    const { card, host, data, t, prefill } = args;
    const id = card.id;
    const answer = (await openModal(InstallSheet as never, {
        card,
        host,
        t,
        prefill,
    } as never)) as SheetOutcome | null;
    if (answer && answer.outcome === 'installed') {
        data.send(id, { kind: 'install' });
        data.send(id, { kind: 'installed' });
        data.setInstalled(id, answer.row);
        return;
    }
    if (answer && answer.outcome === 'refused') {
        data.send(id, { kind: 'refused', code: answer.code ?? '' });
        return;
    }
    data.send(id, { kind: 'dismiss' });
}

export async function runQuickAddForCard(args: {
    readonly card: CardView;
    readonly target: 'global' | 'project';
    readonly projectPath: string | null;
    readonly host: CatalogHost;
    readonly data: CatalogData;
    readonly onSheetRequired: (prefill: CatalogSheetPrefill | null) => Promise<void>;
}): Promise<void> {
    const { card, target, projectPath, host, data, onSheetRequired } = args;
    const id = card.id;
    if (!id) return;
    data.send(id, { kind: 'verify' });
    data.send(id, { kind: 'install' });
    const answer = await quickAdd(host, id, target, projectPath);
    if (answer.outcome === 'installed') {
        data.send(id, { kind: 'installed' });
        data.setInstalled(id, answer.row);
    } else if (answer.outcome === 'refused') {
        data.send(id, { kind: 'refused', code: answer.code });
    } else {
        data.send(id, { kind: 'refused', code: 'sheet_required' });
        data.send(id, { kind: 'verify' });
        await onSheetRequired(answer.prefill);
    }
}

export function applyCatalogLedgerChange(
    data: CatalogData,
    id: string,
    row: InstalledItem | null,
    installId: string | null = null,
): void {
    data.setInstalled(id, row, installId);
    if (!row) {
        if (!(data.installed[id] ?? []).length) data.send(id, { kind: 'uninstalled' });
    } else if (row.update_available !== true) {
        data.send(id, { kind: 'installed' });
    }
}

export async function stepCatalogSelection(args: {
    readonly shown: readonly CardView[];
    readonly shownUntrusted: readonly CardView[];
    readonly selectedId: string | null;
    readonly setSelectedId: (id: string | null) => void;
    readonly step: 1 | -1;
}): Promise<void> {
    const ids = [...args.shown, ...args.shownUntrusted]
        .map((card) => card.id)
        .filter((id): id is string => !!id);
    if (!ids.length) return;
    const at = args.selectedId ? ids.indexOf(args.selectedId) : -1;
    const next = at < 0 ? (args.step === 1 ? 0 : ids.length - 1) : at + args.step;
    if (next < 0 || next >= ids.length) return;
    args.setSelectedId(ids[next] ?? null);
    await tick();
    document.querySelector('.rows__row--on')?.scrollIntoView({ block: 'nearest' });
}

export function dispatchCatalogKeyAction(
    action: KeyAction,
    deps: {
        readonly searchInput: HTMLInputElement | undefined;
        readonly selectedId: string | null;
        readonly moveSelection: (step: 1 | -1) => Promise<void>;
    },
): void {
    if (action === 'search') {
        deps.searchInput?.focus();
    } else if (action === 'next' || action === 'prev') {
        void deps.moveSelection(action === 'next' ? 1 : -1);
    } else if (action === 'open') {
        if (!deps.selectedId) void deps.moveSelection(1);
        else document.querySelector<HTMLElement>('.screen__detail .acts .oc-btn')?.focus();
    } else if (action === 'help') {
        document.querySelector<HTMLButtonElement>('[data-keys-button]')?.click();
    } else {
        const button = document.querySelector<HTMLButtonElement>(`.screen__detail [data-act="${action}"]`);
        if (button && !button.disabled) button.click();
    }
}
