
<script lang="ts">
    import Button from '../lib/base/Button.svelte';
    import type { CommunityHost } from './community-host.svelte.js';
    import { seenAtText } from './admin.js';
    import { t } from './text.js';
    import { ADMIN_KEYS } from '../../../client/js/labels/admin.js';

    let { host, onOpenReviews }: { host: CommunityHost; onOpenReviews: () => void } = $props();

    let attempted = $state(false);
    $effect(() => {
        if (attempted || host.reportsLoaded || host.busy) return;
        attempted = true;
        void host.loadReports();
    });

    function reasonText(reasons: Record<string, number>): string {
        return Object.entries(reasons).map(([reason, n]) => `${reason} ${n}`).join(', ');
    }
</script>

<h3 class="admin-list__name">{t(ADMIN_KEYS.modReportsHeading)}</h3>
{#if !host.reportsLoaded}
    <p class="admin-note">{t(ADMIN_KEYS.loading)}</p>
{:else if host.reports.length === 0}
    <p class="admin-note">{t(ADMIN_KEYS.modReportsEmpty)}</p>
{:else}
    <ul class="admin-list">
        {#each host.reports as group (group.kind + '#' + group.item_id + '#' + group.ref)}
            <li class="admin-list__row">
                <p class="admin-list__name">
                    {t(group.kind === 'review' ? ADMIN_KEYS.modReportsKindReview : ADMIN_KEYS.modReportsKindItem)}:
                    {group.item_id}{group.ref ? ' / ' + group.ref : ''}
                </p>
                <p class="admin-list__meta">
                    {t(ADMIN_KEYS.modReportsCount, { count: group.count, reasons: reasonText(group.reasons) })}
                </p>
                <p class="admin-list__meta">
                    {t(ADMIN_KEYS.modReportsSpan, {
                        first: seenAtText(group.first_at), last: seenAtText(group.last_at),
                    })}
                </p>
                <p class="admin-list__meta">
                    {t(ADMIN_KEYS.modReportsBy, { handles: group.reporters.join(', ') })}
                </p>
                {#if group.kind === 'review'}
                    <Button disabled={host.busy}
                        onclick={() => { void host.openReviews(group.item_id); onOpenReviews(); }}>
                        {t(ADMIN_KEYS.modReportsOpenReviews)}
                    </Button>
                {/if}
                <Button disabled={host.busy}
                    onclick={() => void host.dismissReport(group)}>{t(ADMIN_KEYS.modActionDismiss)}</Button>
            </li>
        {/each}
    </ul>
{/if}
