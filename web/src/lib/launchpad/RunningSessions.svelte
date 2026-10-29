<!-- could not -->
<script lang="ts">
    import RunningSessionRow from './RunningSessionRow.svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import {
        RUNNING_SESSION_KEYS,
        listingAttentionDetail,
        runningCountLabel,
        runningCountUnavailableLabel,
    } from '../../../../client/js/labels/running-session.js';
    import { sessionStore } from '../sessions/store.svelte';
    import { browserRunningChrome, type RunningChrome } from './running-chrome';
    import { browserRunningHost, type RunningHost } from './running-host';
    import type { Translate } from '../sessions/types';

    interface Props {
        host?: RunningHost;
        chrome?: RunningChrome;
        nowMs?: number | null;
        t?: Translate;
    }

    let {
        host = browserRunningHost(),
        chrome = browserRunningChrome(),
        nowMs = null,
        t = reactiveT,
    }: Props = $props();

    const rows = $derived(sessionStore.runningSessions);
    const listing = $derived(sessionStore.runningSessionsListing);
    const listingOk = $derived(!listing || listing.ok !== false);

    const sectionVisible = $derived(rows.length > 0 || !listingOk);

    const countText = $derived(
        listingOk
            ? runningCountLabel(rows.length, t)
            : runningCountUnavailableLabel(t),
    );

    $effect(() => {
        chrome.setCount(countText, listingOk);
    });
    $effect(() => {
        chrome.setSectionVisible(sectionVisible);
    });
</script>

{#if !listingOk}
    <div
        class="running-sessions-attention"
        role="status"
        data-listing-ok="0"
        data-listing-reason={listing.reason || 'probe_error'}
    >
        <div class="running-sessions-attention__head">
            {t(RUNNING_SESSION_KEYS.attentionHead)}
        </div>
        <div class="running-sessions-attention__title">
            {t(RUNNING_SESSION_KEYS.attentionTitle)}
        </div>
        <div class="running-sessions-attention__detail">
            {listingAttentionDetail(listing, t)}
        </div>
        <div class="running-sessions-attention__note">
            {t(RUNNING_SESSION_KEYS.attentionNote)}
        </div>
    </div>
{/if}


{#each rows as row (row.name)}
    <RunningSessionRow {row} {host} {nowMs} {t} />
{/each}
