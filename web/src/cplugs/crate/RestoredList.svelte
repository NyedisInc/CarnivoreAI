
<script lang="ts">
    import { openModal, stampLabel, t as reactiveT, type Translate } from '../sdk';
    import type { Fetcher } from './crate-api';
    import UndoDialog from './UndoDialog.svelte';
    import type { RestoredImport } from './undo-api';

    interface Props {
        restored: readonly RestoredImport[] | null;
        busy?: boolean;
        onChange: () => void;
        t?: Translate;
        fetcher?: Fetcher;
    }
    const { restored, busy = false, onChange, t = reactiveT, fetcher }: Props = $props();

    function nameOf(row: RestoredImport): string {
        return row.projectName ?? row.importId;
    }

    async function undo(row: RestoredImport): Promise<void> {
        const done = await openModal<boolean, Record<string, unknown>>(UndoDialog as never, { importId: row.importId, name: nameOf(row), t, fetcher });
        if (done) onChange();
    }
</script>

<section class="crt-region" data-crt-restored>
    <span class="pl-label">{t('cplug.crate.restored.label')}</span>
    {#if restored && restored.length === 0}
        <p class="tm__sub" data-crt-restored-empty>{t('cplug.crate.restored.empty')}</p>
    {/if}
    {#each restored ?? [] as row (row.importId)}
        <div class="crt-row crt-row--line" data-crt-restored-row={row.importId} data-crt-restored-state={row.state}>
            <span class="crt-row__name">{nameOf(row)}</span>
            <span class="crt-row__meta">
                {#if row.state === 'undone'}
                    {t('cplug.crate.restored.undone', { when: row.undoneAt ? stampLabel(row.undoneAt) : '' })}
                {:else}
                    {#if row.finishedAt}{stampLabel(row.finishedAt)}{/if}
                    {t('cplug.crate.restored.counts', { sessions: row.sessions, files: row.files ?? 0 })}
                {/if}
            </span>
            <span class="crt-row__acts">
                {#if row.state === 'done' || row.state === 'done_with_warnings'}
                    <button type="button" class="oc-btn oc-btn--sm" data-crt-undo={row.importId} disabled={busy}
                        aria-label={t('cplug.crate.restored.undo_label', { name: nameOf(row) })} onclick={() => void undo(row)}>{t('cplug.crate.restored.undo')}</button>
                {/if}
            </span>
        </div>
    {/each}
</section>
