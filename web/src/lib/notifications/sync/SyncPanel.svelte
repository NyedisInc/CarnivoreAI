
<script lang="ts">
    import { onMount } from 'svelte';
    import { t as reactiveT } from '../../i18n/index.svelte';
    import type { Translate } from '../../sessions/types';
    import Check from '../../../opscenter/ui/Check.svelte';
    import '../../settings-page/panel-kit/panel-kit.css';
    import './sync.css';
    import type { Fetcher, SyncPeer } from './api';
    import { peerState, stateKey } from './logic';
    import { attach, setPeer, sync, syncNow } from './store.svelte';

    interface Props {
        t?: Translate;
        fetcher?: Fetcher;
    }
    const { t = reactiveT, fetcher }: Props = $props();

    onMount(() => attach(fetcher));

    const when = (ts: number): string => new Date(ts * 1000).toLocaleString();
    function line(peer: SyncPeer): string {
        const state = peerState(peer);
        if (state === 'synced' && peer.last_exchange_at !== null) return t('settings.notify.sync.state.synced_at', { when: when(peer.last_exchange_at) });
        return t(stateKey(state));
    }
    const bad = (peer: SyncPeer): boolean => ['refused', 'rate_limited', 'error'].includes(peerState(peer));
</script>

<div class="tm" data-sy="panel">
    <p class="tm__sub">{t('settings.notify.sync.intro')}</p>
    <p class="tm__sub" data-sy="trust">{t('settings.notify.sync.trust')}</p>
    {#if sync.problem}<p class="tm__problem" role="alert" data-sy="problem">{sync.problem}</p>{/if}

    {#if !sync.known}
        {#if !sync.problem}<p class="tm__sub" data-sy="loading">{t('settings.notify.sync.loading')}</p>{/if}
    {:else if !sync.body.available}
        <p class="tm__sub" data-sy="unavailable">{t('settings.notify.sync.unavailable')}</p>
    {:else}
        {#if sync.body.peers.length === 0}
            <p class="tm__sub" data-sy="empty">{t('settings.notify.sync.none')}</p>
        {:else}
            <ul class="sy-list" data-sy="peers">
                {#each sync.body.peers as peer (peer.key)}
                    <li class="sy-peer" data-sy-peer={peer.key}>
                        <Check role="switch" label={peer.label} checked={peer.enabled} data-sy="switch"
                            onToggle={(next) => void setPeer(peer.key, next)} />
                        <span class={bad(peer) ? 'sy-state sy-state--bad' : 'sy-state'} data-sy="state" data-sy-state={peerState(peer)}>{line(peer)}</span>
                    </li>
                {/each}
            </ul>
        {/if}
        <div class="sy-actions">
            <button type="button" class="oc-btn" disabled={sync.syncing || sync.body.peers.length === 0} data-sy="now" onclick={() => void syncNow()}>
                {t(sync.syncing ? 'settings.notify.sync.now_busy' : 'settings.notify.sync.now')}
            </button>
        </div>
    {/if}
</div>
