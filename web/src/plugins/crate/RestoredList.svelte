
<script lang="ts">
    import { openModal, stampLabel, t as reactiveT, type Translate } from '../sdk';
    import { Button, Card, List, ListRow, State } from '../sdk/ui';
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

<Card title={t('cplug.crate.restored.label')} data-crt-restored>
    {#snippet children()}
        {#if restored && restored.length === 0}
            <State kind="empty" inline title={t('cplug.crate.restored.empty')} data-crt-restored-empty />
        {/if}
        <List label={t('cplug.crate.restored.label')}>
            {#snippet children()}
                {#each restored ?? [] as row (row.importId)}
                    {#snippet actions()}
                        <Button size="sm" variant="danger" data-crt-undo={row.importId} disabled={busy}
                            aria-label={t('cplug.crate.restored.undo_label', { name: nameOf(row) })} onclick={() => void undo(row)}>{t('cplug.crate.restored.undo')}</Button>
                    {/snippet}
                    <ListRow wrap data-crt-restored-row={row.importId} data-crt-restored-state={row.state} primary={nameOf(row)}
                        secondary={row.state === 'undone'
                            ? t('cplug.crate.restored.undone', { when: row.undoneAt ? stampLabel(row.undoneAt) : '' })
                            : [row.finishedAt ? stampLabel(row.finishedAt) : '', t('cplug.crate.restored.counts', { sessions: row.sessions, files: row.files ?? 0 })].filter(Boolean).join(' ')}
                        actions={row.state === 'done' || row.state === 'done_with_warnings' ? actions : undefined} />
                {/each}
            {/snippet}
        </List>
    {/snippet}
</Card>
