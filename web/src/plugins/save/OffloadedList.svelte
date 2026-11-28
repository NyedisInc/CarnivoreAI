
<script lang="ts">
    import { resourcePush, t as reactiveT, type Translate } from '../sdk';
    import { Button, Check, Checkbox } from '../sdk/ui';
    import {
        appendNew, backCount, fetchOffloaded, keepPicked, OFFLOAD_TOPIC, readOffloadSwitch, restoreOffloaded, rowKey, saveOffloadSwitch, startRestoreBatch, stopBatch, stopRestoreBatch,
        type OffloadBatch, type OffloadPage, type OffloadRestoreBatch, type OffloadRestoreItem, type OffloadRow,
    } from './offload-api';
    import type { Fetcher } from './plugin-settings-api';
    import { factsText, nameText, sizeText, whyText } from './offload-text';
    import { errorText } from './settings-api';

    interface Props {
        t?: Translate;
        fetcher?: Fetcher;
        push?: Pick<ReturnType<typeof resourcePush>, 'pushOrPoll'>;
    }
    const { t = reactiveT, fetcher, push = resourcePush() }: Props = $props();

    const STATE_KEYS: Record<OffloadRow['state'], string> = {
        failed: 'cplug.save.offload.state_failed',
        conflict: 'cplug.save.offload.state_conflict',
        restoring: 'cplug.save.offload.state_restoring',
        offloading: 'cplug.save.offload.state_offloading',
        offloaded: 'cplug.save.offload.state_offloaded',
    };
    const POLL_MS = 30000;

    const BATCH_KEYS: Record<OffloadBatch['state'], string> = {
        running: 'cplug.save.offload.batch_running',
        done: 'cplug.save.offload.batch_done',
        stopped: 'cplug.save.offload.batch_stopped',
        failed: 'cplug.save.offload.batch_failed',
    };

    const RESTORE_BATCH_KEYS: Record<OffloadRestoreBatch['state'], string> = {
        running: 'cplug.save.offload.restore_batch_running',
        done: 'cplug.save.offload.restore_batch_done',
        stopped: 'cplug.save.offload.restore_batch_stopped',
    };

    let enabled = $state(false);
    let batch = $state<OffloadBatch | null>(null);
    let restoreBatch = $state<OffloadRestoreBatch | null>(null);
    let picked = $state<readonly string[]>([]);
    let switchKnown = $state(false);
    let rows = $state<readonly OffloadRow[]>([]);
    let totals = $state({ rows: 0, conversations: 0, bytes: 0 });
    let next = $state<string | null>(null);
    let loaded = $state(false);
    let busy = $state(false);
    let restoring = $state<string | null>(null);
    let note = $state('');
    let problem = $state('');
    let generation = 0;

    const firstLoose = $derived(rows.findIndex((r) => r.kind === 'conversation'));
    const restorable = $derived(rows.filter(canRestore));
    const pickedRows = $derived(restorable.filter((r) => picked.includes(rowKey(r))));
    const allPicked = $derived(!next && restorable.length > 0 && pickedRows.length === restorable.length);
    const failedItems = $derived((restoreBatch?.items ?? []).filter((i) => i.status === 'failed'));
    const restoreRunning = $derived(restoreBatch?.state === 'running');

    async function load(): Promise<void> {
        const mine = ++generation;
        try {
            let page: OffloadPage = await fetchOffloaded(null, fetcher);
            let all: readonly OffloadRow[] = page.rows;
            const wanted = Math.max(rows.length, page.rows.length);
            while (page.next_cursor && all.length < wanted) {
                page = await fetchOffloaded(page.next_cursor, fetcher);
                all = appendNew(all, page.rows);
            }
            if (mine !== generation) return;
            enabled = page.enabled;
            batch = page.batch;
            restoreBatch = page.restore_batch;
            switchKnown = true;
            totals = page.totals;
            rows = all;
            picked = keepPicked(picked, all);
            next = page.next_cursor;
            problem = '';
        } catch (error) {
            if (mine === generation) {
                problem = errorText(error);
                await readSwitch(mine);
            }
        } finally {
            if (mine === generation) loaded = true;
        }
    }

    /* cannot be read */
    async function readSwitch(mine: number): Promise<void> {
        try {
            const on = await readOffloadSwitch(fetcher);
            if (mine !== generation) return;
            enabled = on;
            switchKnown = true;
        } catch {
            if (mine === generation) switchKnown = false;
        }
    }

    $effect(() => {
        void load();
        return push.pushOrPoll(() => void load(), POLL_MS, [OFFLOAD_TOPIC]);
    });

    function canRestore(row: OffloadRow): boolean {
        return row.state !== 'restoring' && row.state !== 'offloading';
    }

    async function more(): Promise<void> {
        if (!next || busy) return;
        busy = true;
        try {
            const page = await fetchOffloaded(next, fetcher);
            rows = appendNew(rows, page.rows);
            next = page.next_cursor;
        } catch (error) {
            problem = errorText(error);
        } finally {
            busy = false;
        }
    }

    async function flip(on: boolean): Promise<void> {
        busy = true;
        problem = '';
        note = '';
        try {
            await saveOffloadSwitch(on, fetcher);
            await load();
        } catch (error) {
            problem = errorText(error);
        } finally {
            busy = false;
        }
    }

    async function stop(): Promise<void> {
        if (!batch) return;
        busy = true;
        problem = '';
        try {
            await stopBatch(batch.id, fetcher);
            await load();
        } catch (error) {
            problem = errorText(error);
        } finally {
            busy = false;
        }
    }

    function toggle(row: OffloadRow): void {
        const key = rowKey(row);
        picked = picked.includes(key) ? picked.filter((k) => k !== key) : [...picked, key];
    }

    async function toggleAll(): Promise<void> {
        if (allPicked) {
            picked = [];
            return;
        }
        busy = true;
        try {
            while (next) {
                const page = await fetchOffloaded(next, fetcher);
                rows = appendNew(rows, page.rows);
                next = page.next_cursor;
            }
            picked = rows.filter(canRestore).map(rowKey);
        } catch (error) {
            problem = errorText(error);
        } finally {
            busy = false;
        }
    }

    function itemName(item: OffloadRestoreItem): string {
        const listed = rows.find((r) => (item.kind === 'session' ? r.session_uuid : r.conversation_id) === item.id);
        return listed ? nameText(listed, t) : item.id;
    }

    async function restoreSelected(): Promise<void> {
        if (pickedRows.length === 0) return;
        busy = true;
        problem = '';
        note = '';
        try {
            restoreBatch = await startRestoreBatch(pickedRows, fetcher);
            picked = [];
            await load();
        } catch (error) {
            problem = errorText(error);
        } finally {
            busy = false;
        }
    }

    async function stopRestore(): Promise<void> {
        if (!restoreBatch) return;
        busy = true;
        problem = '';
        try {
            await stopRestoreBatch(restoreBatch.id, fetcher);
            await load();
        } catch (error) {
            problem = errorText(error);
        } finally {
            busy = false;
        }
    }

    async function restore(row: OffloadRow): Promise<void> {
        busy = true;
        restoring = rowKey(row);
        problem = '';
        note = '';
        try {
            const outcomes = await restoreOffloaded(row, fetcher);
            note = t('cplug.save.offload.restored', { name: nameText(row, t), back: backCount(outcomes), count: outcomes.length });
            await load();
        } catch (error) {
            problem = errorText(error);
        } finally {
            busy = false;
            restoring = null;
        }
    }
</script>

<div class="tm__field" data-tm="offload">
    <span class="oc-key">{t('cplug.save.offload.label')}</span>
    <div class="tm__srv-head">
        <span class="tm__srv-name">{t('cplug.save.offload.switch')}</span>
        <span class="tm__srv-tools">
            <Check bare role="switch" label="" ariaLabel={t('cplug.save.offload.switch_aria')} checked={enabled} disabled={busy || !loaded || !switchKnown}
                onToggle={(next) => void flip(next)} data-tm="offload-switch" />
        </span>
    </div>
    <p class="tm__sub" data-tm="offload-switch-hint">{enabled ? t('cplug.save.offload.on_hint') : t('cplug.save.offload.off_hint')}</p>
    {#if batch}
        <div class="tm__srv-head" data-tm="offload-batch" data-state={batch.state}>
            <span class="tm__srv-name">{t('cplug.save.offload.batch_label')}</span>
            <span class="tm__sub" data-tm="offload-batch-progress">
                {t(BATCH_KEYS[batch.state])}: {t('cplug.save.offload.batch_progress', { done: batch.offloaded, planned: batch.planned, skipped: batch.skipped, failed: batch.failed })}
            </span>
            {#if batch.state === 'running'}
                <span class="tm__srv-tools">
                    <Button size="sm" data-tm="offload-batch-stop" disabled={busy} onclick={() => void stop()}>{t('cplug.save.offload.batch_stop')}</Button>
                </span>
            {/if}
        </div>
    {/if}
    {#if restoreBatch}
        <div class="tm__srv-head" data-tm="restore-batch" data-state={restoreBatch.state}>
            <span class="tm__srv-name">{t('cplug.save.offload.restore_batch_label')}</span>
            <span class="tm__sub" data-tm="restore-batch-progress">
                {t(RESTORE_BATCH_KEYS[restoreBatch.state])}: {t('cplug.save.offload.restore_batch_progress', { done: restoreBatch.restored, planned: restoreBatch.planned, failed: restoreBatch.failed })}
            </span>
            {#if restoreRunning}
                <span class="tm__srv-tools">
                    <Button size="sm" data-tm="restore-batch-stop" disabled={busy} onclick={() => void stopRestore()}>{t('cplug.save.offload.restore_batch_stop')}</Button>
                </span>
            {/if}
        </div>
    {/if}
    {#each failedItems as item (item.kind + item.id)}
        <p class="tm__problem" data-tm="restore-batch-why">{t('cplug.save.offload.restore_batch_failed_item', { name: itemName(item), reason: item.detail || item.code })}</p>
    {/each}
    {#if !loaded}
        <p class="tm__sub">{t('cplug.save.offload.loading')}</p>
    {:else if rows.length === 0}
        <p class="tm__sub" data-tm="offload-empty">{t('cplug.save.offload.empty')}</p>
    {:else}
        <p class="tm__sub" data-tm="offload-totals">
            {t('cplug.save.offload.totals', { rows: totals.rows, conversations: totals.conversations, size: sizeText(totals.bytes, t) })}
        </p>
        <div class="tm__srv-head" data-tm="offload-bulk">
            <Checkbox label={t('cplug.save.offload.select_all')} data-tm="offload-select-all" checked={allPicked} indeterminate={pickedRows.length > 0 && !allPicked}
                disabled={busy || restoreRunning || restorable.length === 0} onchange={() => void toggleAll()} />
            <span class="tm__sub" data-tm="offload-picked">{t('cplug.save.offload.selected_count', { count: pickedRows.length })}</span>
            <span class="tm__srv-tools">
                <Button size="sm" data-tm="offload-restore-selected" disabled={busy || restoreRunning || pickedRows.length === 0} onclick={() => void restoreSelected()}>
                    {t('cplug.save.offload.restore_selected')}
                </Button>
            </span>
        </div>
        <p class="tm__sub" data-tm="offload-bulk-hint">{t('cplug.save.offload.restore_batch_hint')}</p>
        <div class="tm__servers">
            {#each rows as row, index (rowKey(row))}
                {#if index === firstLoose}
                    <span class="oc-key" data-tm="offload-loose-heading">{t('cplug.save.offload.no_session')}</span>
                {/if}
                <div class="tm__srv" data-tm="offload-row" data-state={row.state} data-key={row.session_uuid ?? row.conversation_id ?? ''}>
                    <div class="tm__srv-head">
                        <Checkbox data-tm="offload-pick" aria-label={t('cplug.save.offload.select_row_aria', { name: nameText(row, t) })} checked={picked.includes(rowKey(row))}
                            disabled={busy || restoreRunning || !canRestore(row)} onchange={() => toggle(row)} />
                        <span class="tm__srv-name" data-tm="offload-name">{nameText(row, t)}</span>
                        <span class="tm__sub" data-tm="offload-facts">{factsText(row, t)}</span>
                        <span class="tm__sub" data-tm="offload-state">{t(STATE_KEYS[row.state])}</span>
                        <span class="tm__srv-tools">
                            <Button size="sm" data-tm="offload-restore" disabled={busy || row.state === 'restoring'} onclick={() => void restore(row)}>
                                {restoring === rowKey(row) ? t('cplug.save.offload.restoring') : t('cplug.save.offload.restore')}
                            </Button>
                        </span>
                    </div>
                    {#if (row.state === 'conflict' || row.state === 'failed') && whyText(row, t)}
                        <p class="tm__problem" data-tm="offload-why">{whyText(row, t)}</p>
                    {/if}
                </div>
            {/each}
        </div>
        {#if next}
            <Button size="sm" data-tm="offload-more" disabled={busy} onclick={() => void more()}>{t('cplug.save.offload.more')}</Button>
        {/if}
    {/if}
    {#if note}<p class="tm__note" role="status" data-tm="offload-note">{note}</p>{/if}
    {#if problem}<p class="tm__problem" role="alert" data-tm="offload-problem">{problem}</p>{/if}
</div>
