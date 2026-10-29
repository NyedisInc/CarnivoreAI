
<script lang="ts">
    import { listingRows } from '../../opscenter/api/poll.svelte';
    import { MANAGER_KEYS } from '../manager-frame/manager-model';
    import type { SessionListItem, Translate } from '../sessions/types';
    import SessionFace from '../sessions/SessionFace.svelte';
    import type { PeerRow } from './federation-api';

    interface Props {
        peer: PeerRow;
        t: Translate;
        load?: () => Promise<readonly SessionListItem[]>;
        onOpen: (sessionId: string, tmuxName: string) => void;
    }

    const { peer, t, load = () => listingRows<SessionListItem>('list', '/sessions/list'), onOpen }: Props = $props();

    type HostedItem = SessionListItem & { host_key?: string; project_name?: string | null };

    let rows = $state<readonly HostedItem[] | null>(null);
    let failed = $state(false);

    const mine = $derived((rows ?? []).filter((r) => r.host_key === peer.key));
    const linkUp = $derived(peer.state === 'connected');

    $effect(() => {
        void peer.key;
        void peer.state;
        load().then(
            (all) => { rows = all as readonly HostedItem[]; failed = false; },
            () => { rows = []; failed = true; },
        );
    });
</script>

<h3 class="pl-label host-sessions__head">{t('hosts.peer.sessions')}</h3>
{#if rows === null}
    <p class="host-sessions__none" role="status">{t(MANAGER_KEYS.loading)}</p>
{:else if failed}
    <p class="host-sessions__none" role="alert" data-peer-sessions-failed>{t('hosts.peer.sessions_failed')}</p>
{:else if mine.length === 0}
    <p class="host-sessions__none" data-peer-sessions-empty>{t('hosts.peer.sessions_none')}</p>
{:else}
    <ul class="host-sessions" data-peer-sessions>
        {#each mine as r (r.tmux_session ?? r.session?.id)}
            {@const name = r.label || r.tmux_session || ''}
            <li>
                <button type="button" class="host-sessions__row" data-peer-session={r.tmux_session} onclick={() => onOpen(r.session?.id ?? '', r.tmux_session ?? '')}>
                    <SessionFace row={r} transport={linkUp ? 'unknown' : 'disconnected'} {name} nameClass="host-sessions__name" />
                    {#if !linkUp}<span class="host-sessions__down" data-peer-session-down>{t('hosts.peer.sessions_disconnected')}</span>{/if}
                    <span class="host-sessions__project">{r.project_name ?? ''}</span>
                </button>
            </li>
        {/each}
    </ul>
{/if}

<style>
  @layer components {
    .host-sessions__head { margin: 12px 0 4px; }
    .host-sessions__none { margin: 4px 0; color: var(--oc-text-muted); font-size: 12px; }
    .host-sessions { list-style: none; margin: 0; padding: 0; }
    .host-sessions__row {
        display: flex;
        align-items: center;
        gap: 8px;
        width: 100%;
        padding: 6px 0;
        border: 0;
        background: none;
        box-shadow: 0 1px 0 var(--oc-line-faint);
        color: var(--oc-text-primary);
        font-family: var(--font-mono);
        font-size: 12px;
        text-align: left;
        cursor: pointer;
    }
    .host-sessions__row:hover { background: var(--oc-ground-field); }
    .host-sessions__row :global(.host-sessions__name) { flex: 1; overflow-wrap: anywhere; }
    .host-sessions__down { color: var(--oc-coral); font-size: 11px; }
    .host-sessions__project { color: var(--oc-text-muted); font-size: 11px; }
  }
</style>
