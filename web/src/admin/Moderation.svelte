
<script lang="ts">
    import Button from '../lib/base/Button.svelte';
    import ReportsTab from './ReportsTab.svelte';
    import type { CommunityHost } from './community-host.svelte.js';
    import { refusalMessage, seenAtText } from './admin.js';
    import { t } from './text.js';
    import { ADMIN_KEYS } from '../../../client/js/labels/admin.js';

    let { host }: { host: CommunityHost } = $props();

    let tab = $state<'queue' | 'item' | 'reports'>('queue');
    let attempted = $state(false);
    $effect(() => {
        if (attempted || host.loaded || host.busy) return;
        attempted = true;
        void host.load();
    });

    const refusalText = $derived(refusalMessage(host.refusal, t));
    const otherMode = $derived(host.mode === 'instant' ? 'hold_all' : 'instant');

    function modeKey(mode: string): string {
        return mode === 'hold_all' ? ADMIN_KEYS.modModeHoldAll : ADMIN_KEYS.modModeInstant;
    }
</script>

<section class="admin-panel">
    <h2 class="admin-panel__heading">{t(ADMIN_KEYS.modHeading)}</h2>

    {#if refusalText}
        <p class="admin-refusal" role="alert">{refusalText}</p>
    {/if}

    <h3 class="admin-list__name">{t(ADMIN_KEYS.modModeHeading)}</h3>
    <p class="admin-list__meta">{t(ADMIN_KEYS.modModeCurrent, { mode: t(modeKey(host.mode)) })}</p>
    {#if host.pendingMode}
        <p class="admin-note">{t(ADMIN_KEYS.modModeConfirm, { mode: t(modeKey(host.pendingMode)) })}</p>
        <Button variant="confirm" disabled={host.busy}
            onclick={() => void host.confirmMode()}>{t(ADMIN_KEYS.modModeConfirmYes)}</Button>
        <Button onclick={() => host.cancelMode()}>
            {t(ADMIN_KEYS.modModeConfirmNo)}
        </Button>
    {:else}
        <Button onclick={() => host.askMode(otherMode)}>
            {t(ADMIN_KEYS.modModeSwitch, { mode: t(modeKey(otherMode)) })}
        </Button>
    {/if}

    <label class="admin-field" for="mod-reason">{t(ADMIN_KEYS.modReasonLabel)}</label>
    <input id="mod-reason" class="admin-input" type="text" maxlength="200" value={host.reason}
        oninput={(event) => host.setReason(event.currentTarget.value)} />

    <div class="admin-filters">
        <Button aria-pressed={tab === 'queue'}
            onclick={() => (tab = 'queue')}>{t(ADMIN_KEYS.modTabQueue)}</Button>
        <Button aria-pressed={tab === 'item'}
            onclick={() => (tab = 'item')}>{t(ADMIN_KEYS.modTabItem)}</Button>
        <Button aria-pressed={tab === 'reports'}
            onclick={() => (tab = 'reports')}>{t(ADMIN_KEYS.modTabReports)}</Button>
    </div>

    {#if tab === 'reports'}
        <ReportsTab {host} onOpenReviews={() => (tab = 'queue')} />
    {/if}

    {#if tab === 'item'}
        <label class="admin-field" for="mod-comment-item">{t(ADMIN_KEYS.modReviewsItemLabel)}</label>
        <input id="mod-comment-item" class="admin-input" type="text" value={host.commentItem}
            oninput={(event) => host.setCommentItem(event.currentTarget.value)} />
        <Button disabled={host.busy}
            onclick={() => void host.loadItemComments()}>{t(ADMIN_KEYS.modItemLoad)}</Button>
        {#if host.itemRowsLoaded && host.itemRows.length === 0}
            <p class="admin-note">{t(ADMIN_KEYS.modItemEmpty)}</p>
        {:else}
            <ul class="admin-list">
                {#each host.itemRows as row (row.item_id + '/' + row.comment_id)}
                    <li class="admin-list__row">
                        <p class="admin-list__name">{t(ADMIN_KEYS.modKindComment)}: {row.status}</p>
                        <p class="admin-list__meta">
                            {t(ADMIN_KEYS.modRowBy, { author: row.author_handle || row.author_id || '' })}
                        </p>
                        <p class="admin-list__meta">
                            {t(ADMIN_KEYS.modRowWhen, { day: seenAtText(row.created_at) })}
                        </p>
                        <p class="admin-note-text">{row.body}</p>
                        {#if row.status === 'hidden' || row.status === 'held'}
                            <Button variant="confirm" disabled={host.busy}
                                onclick={() => void host.comment('restore', row)}>{t(ADMIN_KEYS.modActionRestore)}</Button>
                        {/if}
                        {#if row.status === 'visible' || row.status === 'held'}
                            <Button variant="danger" disabled={host.busy}
                                onclick={() => void host.comment('hide', row)}>{t(ADMIN_KEYS.modActionHide)}</Button>
                        {/if}
                        <Button variant="danger" disabled={host.busy}
                            onclick={() => void host.comment('delete', row)}>{t(ADMIN_KEYS.modActionDelete)}</Button>
                    </li>
                {/each}
            </ul>
        {/if}
    {/if}

    {#if tab === 'queue'}
    <h3 class="admin-list__name">{t(ADMIN_KEYS.modQueueHeading)}</h3>
    {#if !host.loaded}
        <p class="admin-note">{t(ADMIN_KEYS.loading)}</p>
    {:else if host.comments.length === 0}
        <p class="admin-note">{t(ADMIN_KEYS.modQueueEmpty)}</p>
    {:else}
        <ul class="admin-list">
            {#each host.comments as row (row.item_id + '/' + row.comment_id)}
                <li class="admin-list__row">
                    <p class="admin-list__name">
                        {t(ADMIN_KEYS.modKindComment)}: {row.queue === 'reported'
                            ? t(ADMIN_KEYS.modQueueReported)
                            : t(ADMIN_KEYS.modQueueHeld)}
                    </p>
                    <p class="admin-list__meta">{t(ADMIN_KEYS.modRowItem, { item: row.item_id })}</p>
                    <p class="admin-list__meta">
                        {t(ADMIN_KEYS.modRowBy, { author: row.author_handle || row.author_id || '' })}
                    </p>
                    <p class="admin-list__meta">
                        {t(ADMIN_KEYS.modRowWhen, { day: seenAtText(row.created_at) })}
                    </p>
                    {#if row.reasons && Object.keys(row.reasons).length}
                        <p class="admin-list__meta">
                            {t(ADMIN_KEYS.modQueueReasons, {
                                reasons: Object.entries(row.reasons).map(([k, n]) => `${k} ${n}`).join(', '),
                            })}
                        </p>
                    {/if}
                    <p class="admin-note-text">{row.body}</p>
                    <Button variant="danger" disabled={host.busy}
                        onclick={() => void host.comment('hide', row)}>{t(ADMIN_KEYS.modActionHide)}</Button>
                    <Button disabled={host.busy}
                        onclick={() => void host.comment('restore', row)}>{t(ADMIN_KEYS.modActionRestore)}</Button>
                    <Button variant="danger" disabled={host.busy}
                        onclick={() => void host.comment('delete', row)}>{t(ADMIN_KEYS.modActionDelete)}</Button>
                    <Button disabled={host.busy}
                        onclick={() => void host.comment('dismiss', row)}>{t(ADMIN_KEYS.modActionDismiss)}</Button>
                </li>
            {/each}
        </ul>
    {/if}

    <h3 class="admin-list__name">{t(ADMIN_KEYS.modReviewsHeading)}</h3>
    <label class="admin-field" for="mod-review-item">{t(ADMIN_KEYS.modReviewsItemLabel)}</label>
    <input id="mod-review-item" class="admin-input" type="text" value={host.reviewItem}
        oninput={(event) => host.setReviewItem(event.currentTarget.value)} />
    <Button disabled={host.busy}
        onclick={() => void host.loadReviews()}>{t(ADMIN_KEYS.modReviewsLoad)}</Button>
    {#if host.reviewsLoaded && host.reviews.length === 0}
        <p class="admin-note">{t(ADMIN_KEYS.modReviewsEmpty)}</p>
    {:else}
        <ul class="admin-list">
            {#each host.reviews as row (row.review_ref)}
                <li class="admin-list__row">
                    <p class="admin-list__name">
                        {t(ADMIN_KEYS.modReviewsRow, { stars: row.stars, author: row.author || row.login || '' })}
                        {#if row.status === 'hidden'}({t(ADMIN_KEYS.modReviewsHidden)}){/if}
                    </p>
                    <p class="admin-note-text">{row.text}</p>
                    <Button variant="danger" disabled={host.busy}
                        onclick={() => void host.review('hide', row)}>{t(ADMIN_KEYS.modActionHide)}</Button>
                    <Button disabled={host.busy}
                        onclick={() => void host.review('restore', row)}>{t(ADMIN_KEYS.modActionRestore)}</Button>
                    <Button variant="danger" disabled={host.busy}
                        onclick={() => void host.review('remove', row)}>{t(ADMIN_KEYS.modActionRemove)}</Button>
                </li>
            {/each}
        </ul>
    {/if}
    {/if}
</section>
