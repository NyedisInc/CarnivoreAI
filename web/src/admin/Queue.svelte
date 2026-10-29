
<script lang="ts">
    import { loadOnce } from './load-once.svelte.js';
    import Button from '../lib/base/Button.svelte';
    import Field from '../lib/base/Field.svelte';
    import type { AdminHost } from './admin-host.svelte.js';
    import { t } from './text.js';
    import SubmissionDetail from './SubmissionDetail.svelte';
    import Tabs, { panelAttrs } from '../opscenter/ui/Tabs.svelte';
    import { isLegacyPending } from './admin.js';
    import { QUEUE_STAGES, queueStageOf, statusWord } from './queue-stage.js';
    import { ADMIN_KEYS } from '../../../client/js/labels/admin.js';

    let { host }: { host: AdminHost } = $props();

    let openId = $state('');

    const counts = $derived.by(() => {
        const out: Record<string, number> = { submitted: 0, in_review: 0, approved: 0, rejected: 0 };
        for (const row of host.submissions) {
            const stage = queueStageOf(row);
            out[stage] = (out[stage] ?? 0) + 1;
        }
        return out;
    });
    const rows = $derived(host.submissions.filter((row) => queueStageOf(row) === host.queueStatus));
    const tabs = $derived(QUEUE_STAGES.map((stage) => ({ id: stage.id, label: t(stage.key), badge: host.queueLoaded ? counts[stage.id] : null })));

    loadOnce(() => !host.queueLoaded && !host.busy, () => host.loadQueue(host.queueStatus));
</script>

<section class="admin-panel">
    <h2 class="admin-panel__heading">{t(ADMIN_KEYS.queueHeading)}</h2>

    
    <Tabs {tabs} active={host.queueStatus} onSelect={(id) => host.selectQueueStage(id)} label={t(ADMIN_KEYS.queueTabsLabel)} idBase="queue" />

    <div class="admin-queue" {...panelAttrs('queue', host.queueStatus)}>
    {#if !host.queueLoaded}
        <p class="admin-note">{t(ADMIN_KEYS.loading)}</p>
    {:else if rows.length === 0}
        <p class="admin-note">{t(ADMIN_KEYS.queueEmpty)}</p>
    {:else}
        <ul class="admin-list">
            {#each rows as row (row.submission_id)}
                {@const word = statusWord(row)}
                <li class="admin-list__row">
                    <div class="admin-queue__head">
                    <p class="admin-list__name">
                        {row.name || row.submission_id}
                    </p>
                    <span class="admin-badge">{t(ADMIN_KEYS.queueKind, { kind: row.kind || 'skill' })}</span>
                    {#if row.media_only}
                        <span class="admin-badge">
                            {t(ADMIN_KEYS.queueRowHeroImage, { item: row.item_id || row.name || '' })}
                        </span>
                    {/if}
                    <span class="admin-state admin-state--{word.tone}">{t(word.key)}</span>
                    </div>
                    <div class="admin-queue__meta">
                    {#if row.file_count !== undefined}
                        <span class="admin-list__meta">{t(ADMIN_KEYS.queueRowFiles, { count: row.file_count })}</span>
                    {/if}
                    {#if row.gate_outcome === 'passed_with_mentions'}
                        <p class="admin-list__meta">{t(ADMIN_KEYS.queueChipMentions)}</p>
                    {/if}
                    <p class="admin-list__meta">
                        {t(ADMIN_KEYS.queueRowBy, {
                            author: row.submitted_by_login || row.handle || '',
                        })}
                    </p>
                    <p class="admin-list__meta">
                        {t(ADMIN_KEYS.queueRowVersion, { version: row.version || '' })}
                    </p>
                    {#if row.handle_status === 'pending'}
                        <p class="admin-list__meta">
                            {t(ADMIN_KEYS.queueRowHandlePending, { handle: row.handle || '' })}
                        </p>
                    {/if}
                    {#if row.new_version}
                        <p class="admin-list__meta">
                            {t(
                                row.prior_submitter_match
                                    ? ADMIN_KEYS.queueRowSameSubmitter
                                    : ADMIN_KEYS.queueRowNewSubmitter,
                            )}
                        </p>
                    {/if}
                    </div>
                    <Button
                        onclick={() => (openId = openId === row.submission_id ? '' : row.submission_id)}
                    >
                        {t(openId === row.submission_id ? ADMIN_KEYS.detailClose : ADMIN_KEYS.detailOpen)}
                    </Button>
                    {#if !isLegacyPending(row)}
                        
                    {:else if host.rejecting === row.submission_id}
                        <label class="admin-field" for={'reason-' + row.submission_id}>
                            {t(ADMIN_KEYS.queueRejectLabel)}
                        </label>
                        <Field
                            id={'reason-' + row.submission_id} data-admin-grow
                            maxlength={500}
                            value={host.rejectReason}
                            oninput={(event) =>
                                host.setRejectReason(event.currentTarget.value)}
                        />
                        <Button variant="danger"
                            onclick={() => void host.confirmReject()}
                        >
                            {t(ADMIN_KEYS.queueRejectConfirm)}
                        </Button>
                        <Button
                            onclick={() => host.cancelReject()}
                        >
                            {t(ADMIN_KEYS.queueRejectCancel)}
                        </Button>
                    {:else}
                        <Button variant="confirm"
                            onclick={() => void host.approve(row.submission_id)}
                        >
                            {t(ADMIN_KEYS.queueActionApprove)}
                        </Button>
                        <Button variant="danger"
                            onclick={() => host.beginReject(row.submission_id)}
                        >
                            {t(ADMIN_KEYS.queueActionReject)}
                        </Button>
                    {/if}
                    {#if openId === row.submission_id}
                        <SubmissionDetail {host} {row} />
                    {/if}
                </li>
            {/each}
        </ul>
    {/if}
    </div>
</section>
