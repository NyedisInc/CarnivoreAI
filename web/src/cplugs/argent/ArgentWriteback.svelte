
<script lang="ts">
    import { onDestroy } from 'svelte';
    import { t as reactiveT, authFetch, resourcePush, failureReason, type Translate } from '../sdk';
    import { Button, Field, State } from '../sdk/ui';

    interface Row { id: number; item_title: string; session_name: string; commits: number; body: string }
    interface Props { t?: Translate; fetcher?: typeof authFetch; pollMs?: number }
    const { t = reactiveT, fetcher = authFetch, pollMs = 30000 }: Props = $props();

    let rows = $state<Row[]>([]);
    let drafts = $state<Record<number, string>>({});
    let busy = $state(false);
    let problem = $state('');

    async function load(): Promise<void> {
        try {
            const body = await fetcher<{ items?: Row[] }>('/argent/writeback/review');
            rows = Array.isArray(body?.items) ? body.items : [];
            const next: Record<number, string> = {};
            for (const row of rows) next[row.id] = drafts[row.id] !== undefined && drafts[row.id] !== row.body ? drafts[row.id] : row.body;
            drafts = next;
        } catch (error) {
            problem = failureReason(error);
        }
    }
    void load();
    onDestroy(resourcePush().pushOrPoll(() => void load(), pollMs, ['argent_writeback']));

    async function act(row: Row, action: 'approve' | 'edit' | 'discard'): Promise<void> {
        busy = true;
        problem = '';
        try {
            const changed = (drafts[row.id] ?? row.body) !== row.body;
            if (action === 'edit' || (action === 'approve' && changed)) {
                await fetcher<unknown>(`/argent/writeback/${row.id}/edit`, { method: 'POST', body: JSON.stringify({ body: drafts[row.id] }) });
            }
            if (action !== 'edit') await fetcher<unknown>(`/argent/writeback/${row.id}/${action}`, { method: 'POST' });
            await load();
        } catch (error) {
            const code = (error as { payload?: { detail?: { code?: string } } }).payload?.detail?.code;
            problem = code === 'blocked_secret' ? t('argent.writeback.blocked_secret') : failureReason(error);
        } finally {
            busy = false;
        }
    }
</script>

{#if rows.length}
    <div data-argent="writeback">
        <p class="tm__sub">{t('argent.writeback.heading')}</p>
        {#each rows as row (row.id)}
            <p class="tm__sub" data-argent="writeback-row">{t('argent.writeback.row', { item: row.item_title, session: row.session_name, commits: String(row.commits) })}</p>
            <Field label={t('argent.writeback.body')} multiline rows={4} bind:value={drafts[row.id]} disabled={busy} spellcheck={false} data-argent="writeback-body" />
            <div class="tm__actions">
                <Button size="sm" variant="confirm" disabled={busy} data-argent="writeback-approve" onclick={() => void act(row, 'approve')}>{t('argent.writeback.approve')}</Button>
                <Button size="sm" disabled={busy || (drafts[row.id] ?? row.body) === row.body} data-argent="writeback-edit" onclick={() => void act(row, 'edit')}>{t('argent.writeback.save')}</Button>
                <Button size="sm" variant="danger" disabled={busy} data-argent="writeback-discard" onclick={() => void act(row, 'discard')}>{t('argent.writeback.discard')}</Button>
            </div>
        {/each}
        {#if problem}<State kind="error" inline title={problem} data-argent="writeback-problem" />{/if}
    </div>
{/if}
