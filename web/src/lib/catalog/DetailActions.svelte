<!-- the reading pane -->
<script lang="ts">
    import { BROWSE_KEYS } from '../../../../client/js/labels/skill-browse.js';
    import { SKILL_KEYS, refusalMessage } from '../../../../client/js/labels/skill.js';
    import { openModal, openModalCount } from '../modal';
    import type { Translate } from '../sessions/types';
    import AutoUpdateSwitch from './AutoUpdateSwitch.svelte';
    import DriftFacts from './DriftFacts.svelte';
    import ConfirmSheet from './ConfirmSheet.svelte';
    import AddSplit from './AddSplit.svelte';
    import type { AddProject } from './add-projects';
    import { tryItem } from './try-flow';
    import type { CardView } from './card';
    import type { CatalogHost } from './catalog';
    import { isBusy, refusalCodeOf, type InstallState } from './install-actions';
    import {
        canWrite,
        ledgerFailure,
        restoreSheet,
        revisionOf,
        uninstallSheet,
    } from './installed-actions';
    import { acceptNewText, runUpdate, type UpdateContext, type UpdateResult } from './update-flow';
    import type { InstalledItem } from './types';

    interface Props {
        files?: number | null;
        card: CardView;
        installed: InstalledItem | null;
        rowState: InstallState;
        host: CatalogHost;
        t: Translate;
        onInstall: () => void;
        onLedgerChange: (id: string, row: InstalledItem | null, installId?: string | null) => void;
        onAdd?: ((target: 'global' | 'project', projectPath?: string) => void) | null;
        projects?: readonly AddProject[];
        copies?: readonly InstalledItem[];
    }

    const { card, installed, rowState, host, t, onInstall, onLedgerChange, files = null, onAdd = null, projects = [], copies = [] }: Props = $props();

    let refusal = $state<string | null>(null);
    let unsupported = $state(false);
    let stale = $state(false);
    let working = $state<'update' | 'uninstall' | 'auto' | 'restore' | 'fork' | null>(null);

    const writable = $derived(canWrite(installed));
    const busy = $derived(working !== null || isBusy(rowState));
    const name = $derived(card.headline || card.id || '');

    function blocked(): boolean {
        return busy || openModalCount() > 0;
    }

    function clearOutcome(): void {
        refusal = null;
        unsupported = false;
        stale = false;
    }

    function applyOutcome(id: string, outcome: ReturnType<typeof ledgerFailure>): void {
        if (outcome.kind === 'stale') {
            stale = true;
            if (outcome.row) onLedgerChange(id, outcome.row);
            return;
        }
        if (outcome.kind === 'unsupported') {
            unsupported = true;
            return;
        }
        refusal = outcome.kind === 'refused' ? outcome.code : '';
    }

    function paintUpdate(id: string, result: UpdateResult): void {
        if (result.kind === 'updated') onLedgerChange(id, result.row);
        else if (result.kind === 'failed') applyOutcome(id, result.outcome);
    }

    function updateContext(): UpdateContext {
        return { host, t, name, card, installed };
    }

    async function applyUpdate(): Promise<void> {
        const id = card.id || '';
        if (!installed?.install_id || revisionOf(installed) === null) return;
        if (blocked()) return;
        try {
            paintUpdate(id, await runUpdate(updateContext(), () => {
                clearOutcome();
                working = 'update';
            }));
        } finally {
            working = null;
        }
    }

    async function uninstall(): Promise<void> {
        const id = card.id || '';
        const installId = installed && installed.install_id;
        if (!installId) return;
        if (blocked()) return;
        const agreed = await openModal(
            ConfirmSheet as never,
            uninstallSheet(name, installed, t) as never,
        );
        if (!agreed) return;
        clearOutcome();
        working = 'uninstall';
        try {
            await host.uninstall(installId);
            onLedgerChange(id, null, installId);
        } catch (error) {
            applyOutcome(id, ledgerFailure(error));
        } finally {
            working = null;
        }
    }

    async function restore(): Promise<void> {
        const id = card.id || '';
        const revision = revisionOf(installed);
        const installId = installed && installed.install_id;
        if (!installId || revision === null || !host.restoreInstalled) return;
        if (blocked()) return;
        const agreed = await openModal(
            ConfirmSheet as never,
            restoreSheet(name, installed?.version ?? null, t) as never,
        );
        if (!agreed) return;
        clearOutcome();
        working = 'restore';
        try {
            onLedgerChange(id, await host.restoreInstalled(installId, { expected_revision: revision }));
        } catch (error) {
            if (refusalCodeOf(error) === 'consent_required') {
                const restoreId = host.restoreInstalled;
                paintUpdate(id, await acceptNewText(updateContext(), revision, error, (sent) => restoreId(installId, sent)));
            } else {
                applyOutcome(id, ledgerFailure(error));
            }
        } finally {
            working = null;
        }
    }

    async function setFork(next: boolean): Promise<void> {
        const id = card.id || '';
        const installId = installed && installed.install_id;
        if (!installId || !host.setFork) return;
        if (blocked()) return;
        clearOutcome();
        working = 'fork';
        try {
            onLedgerChange(id, await host.setFork(installId, next));
        } catch (error) {
            applyOutcome(id, ledgerFailure(error));
        } finally {
            working = null;
        }
    }

    async function setAuto(next: boolean): Promise<void> {
        const id = card.id || '';
        const revision = revisionOf(installed);
        const installId = installed && installed.install_id;
        if (!installId || revision === null) return;
        if (blocked()) return;
        clearOutcome();
        working = 'auto';
        try {
            const sent = { auto_update: next, expected_revision: revision };
            onLedgerChange(id, await host.patchInstalled(installId, sent));
        } catch (error) {
            applyOutcome(id, ledgerFailure(error));
        } finally {
            working = null;
        }
    }

    async function dropIntoSession(): Promise<void> {
        const id = card.id || '';
        if (blocked()) return;
        clearOutcome();
        const result = await tryItem({ host, t, card, name, files });
        if (result.kind === 'failed') applyOutcome(id, ledgerFailure(result.error));
    }
</script>

<div class="acts">
    <div class="acts__row">
        {#if card.untrusted}
            
            <span class="acts__state">{t(SKILL_KEYS.cardUntrusted)}</span>
        {:else}
            {#if rowState.kind === 'installed' || rowState.kind === 'update-available'}
                {#if rowState.kind === 'update-available'}
                    <button
                        type="button"
                        class="modal-btn modal-btn-confirm warez-act"
                        data-act="update"
                        disabled={!writable || busy}
                        onclick={() => void applyUpdate()}
                    >{working === 'update'
                        ? t(SKILL_KEYS.updateWorking)
                        : t(SKILL_KEYS.actionUpdate)}</button>
                {/if}
                {#if card.kind !== 'theme' && card.kind !== 'mod'}
                    
                    <button
                        type="button"
                        class="modal-btn modal-btn-secondary warez-act"
                        data-act="install-other"
                        disabled={busy}
                        onclick={onInstall}
                    >{t(SKILL_KEYS.actionInstall)}</button>
                {/if}
                <button
                    type="button"
                    class="modal-btn modal-btn-danger warez-act"
                    data-act="uninstall"
                    disabled={!writable || busy}
                    onclick={() => void uninstall()}
                >{working === 'uninstall'
                    ? t(SKILL_KEYS.uninstallWorking)
                    : t(SKILL_KEYS.actionUninstall)}</button>
            {:else if rowState.kind === 'refused'}
                <button type="button" class="modal-btn modal-btn-secondary warez-act" disabled={busy} onclick={onInstall}>
                    {t(SKILL_KEYS.actionRetry)}
                </button>
            {:else if rowState.kind === 'verifying' || rowState.kind === 'installing'}
                <span class="acts__state">
                    {rowState.kind === 'verifying'
                        ? t(SKILL_KEYS.stateVerifying)
                        : t(SKILL_KEYS.stateInstalling)}
                </span>
            {:else if onAdd}
                
                <AddSplit
                    {projects}
                    installedAt={copies.flatMap((row) => (row.scope === 'project' && row.project_path ? [row.project_path] : []))}
                    haveGlobal={copies.some((row) => row.scope !== 'project')}
                    haveAnyProject={copies.some((row) => row.scope === 'project')}
                    {onAdd}
                    {t}
                    act="install"
                    caret={card.kind !== 'theme' && card.kind !== 'mod'}
                />
            {:else}
                <button
                    type="button"
                    class="modal-btn modal-btn-confirm warez-act"
                    data-act="install"
                    disabled={busy}
                    onclick={onInstall}
                >{t(SKILL_KEYS.actionInstall)}</button>
            {/if}
            <button
                type="button"
                class="modal-btn modal-btn-secondary warez-act"
                data-act="try"
                disabled={busy}
                onclick={() => void dropIntoSession()}
            >{t(BROWSE_KEYS.tryAction)}</button>
        {/if}
    </div>

    {#if rowState.kind === 'refused'}
        <p class="acts__refusal" role="alert">{refusalMessage(rowState.code, t)}</p>
    {/if}
    {#if refusal !== null}
        <p class="acts__refusal" role="alert">{refusalMessage(refusal, t)}</p>
    {/if}
    {#if unsupported}
        <p class="acts__refusal" role="alert">{t(SKILL_KEYS.refusedUnsupported)}</p>
    {/if}
    {#if stale}
        
        <p class="acts__note" role="status">{t(SKILL_KEYS.updateStale)}</p>
    {/if}

    {#if installed && installed.drift}
        <!-- and the three -->
        <DriftFacts {installed} {t} />
        <div class="acts__row" data-acts="drift">
            {#if installed.drift.state === 'drifted'}
                
                <button
                    type="button"
                    class="oc-btn oc-btn--confirm"
                    data-act="restore"
                    disabled={!writable || busy || !host.restoreInstalled}
                    onclick={() => void restore()}
                >{working === 'restore' ? t(BROWSE_KEYS.driftRestoreWorking) : t(BROWSE_KEYS.driftRestore)}</button>
            {/if}
            {#if installed.drift.state === 'drifted' || installed.drift.state === 'missing'}
                <button
                    type="button"
                    class="oc-btn oc-btn--danger"
                    data-act="drift-uninstall"
                    disabled={!writable || busy}
                    onclick={() => void uninstall()}
                >{t(BROWSE_KEYS.driftUninstall)}</button>
            {/if}
            {#if installed.drift.state === 'drifted' || installed.forked}
                <button
                    type="button"
                    class="oc-btn"
                    data-act="fork"
                    disabled={!writable || busy || !host.setFork}
                    onclick={() => void setFork(!installed?.forked)}
                >{installed.forked ? t(BROWSE_KEYS.driftForkClear) : t(BROWSE_KEYS.driftForkMark)}</button>
            {/if}
        </div>
    {/if}

    {#if installed}
        <AutoUpdateSwitch
            {installed}
            {t}
            working={working === 'auto'}
            {busy}
            onToggle={(next) => void setAuto(next)}
        />
    {/if}
</div>

<style>
    .acts {
        display: flex;
        flex-direction: column;
        gap: 8px;
    }

    .acts__row {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 8px;
    }

    .acts__state {
        color: var(--cat-attention);
        font-family: var(--cat-mono);
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }








    .acts__refusal {
        margin: 0;
        padding: 6px 8px;
        border-left: 2px solid var(--cat-failure);
        background: var(--cat-failure-wash);
        color: var(--cat-text);
        font-size: 12px;
        line-height: 1.45;
    }

    .acts__note {
        margin: 0;
        color: var(--cat-muted);
        font-size: 11px;
        line-height: 1.45;
    }

</style>
