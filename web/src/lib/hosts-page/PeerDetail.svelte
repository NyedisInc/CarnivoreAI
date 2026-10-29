
<script lang="ts">
    import { MANAGER_KEYS } from '../manager-frame/manager-model';
    import { openModal } from '../modal';
    import type { Translate } from '../sessions/types';
    import FedConfirmModal from './FedConfirmModal.svelte';
    import type { FederationApi, GrantRow, PeerRow } from './federation-api';
    import { peerStateHelp } from './hosts-adapter';
    import PeerSessions from './PeerSessions.svelte';
    import PeerState from './PeerState.svelte';

    interface Props {
        peer: PeerRow;
        fed: FederationApi;
        t: Translate;
        onChanged: () => void;
        onOpen: (sessionId: string, tmuxName: string) => void;
    }

    const { peer, fed, t, onChanged, onOpen }: Props = $props();

    let grants = $state<readonly GrantRow[] | null>(null);
    let notice = $state<{ text: string; error: boolean } | null>(null);
    let busy = $state(false);

    async function loadGrants(): Promise<void> {
        try {
            grants = (await fed.grants()).filter((g) => g.peer_install_id === peer.peer_install_id);
        } catch (err) {
            grants = [];
            notice = { text: t('hosts.peer.action_failed', { reason: err instanceof Error ? err.message : '' }), error: true };
        }
    }

    $effect(() => {
        void peer.peer_install_id;
        void loadGrants();
    });

    async function act(title: string, body: string, confirmLabel: string, run: () => Promise<void>, done: string): Promise<void> {
        if (busy) return;
        const yes = await openModal<true, { title: string; body: string; confirmLabel: string; t: Translate }>(FedConfirmModal, { title, body, confirmLabel, t });
        if (!yes) return;
        busy = true;
        try {
            await run();
            notice = { text: done, error: false };
            onChanged();
            await loadGrants();
        } catch (err) {
            notice = { text: t('hosts.peer.action_failed', { reason: err instanceof Error ? err.message : '' }), error: true };
        } finally {
            busy = false;
        }
    }

    const revoke = (grant: GrantRow): Promise<void> =>
        act(t('hosts.revoke.title', { name: peer.label }), t('hosts.revoke.body', { name: peer.label }), t('hosts.revoke.confirm'),
            () => fed.revoke(grant.grant_id), t('hosts.revoke.done', { name: peer.label }));

    const unpair = (): Promise<void> =>
        act(t('hosts.unpair.title', { name: peer.label }), t('hosts.unpair.body', { name: peer.label }), t('hosts.unpair.confirm'),
            () => fed.unpair(peer.key), t('hosts.unpair.done', { name: peer.label }));
</script>

<dl class="mgr-facts">
    <dt>{t('hosts.peer.fact.state')}</dt>
    <dd><PeerState state={peer.state} {t} /></dd>
    <dt>{t('hosts.peer.fact.fid')}</dt>
    <dd data-peer-fid>{peer.fid}</dd>
    {#if peer.protocol !== null}
        <dt>{t('hosts.peer.fact.protocol')}</dt>
        <dd>{peer.protocol}</dd>
    {/if}
    <dt>{t('hosts.peer.fact.dialer')}</dt>
    <dd>{peer.initiator ? t('hosts.peer.dialer.this') : t('hosts.peer.dialer.that')}</dd>
</dl>
<p class="host-detail__notice" data-peer-help={peer.state}>{peerStateHelp(peer.state, t)}</p>

<PeerSessions {peer} {t} {onOpen} />

<h3 class="pl-label host-peer__head">{t('hosts.peer.grants')}</h3>
{#if grants === null}
    <p class="host-peer__none" role="status">{t(MANAGER_KEYS.loading)}</p>
{:else if grants.length === 0}
    <p class="host-peer__none" data-peer-grants-empty>{t('hosts.peer.grants_none')}</p>
{:else}
    <ul class="host-peer__grants" data-peer-grants>
        {#each grants as grant (grant.grant_id)}
            <li class="host-peer__grant" data-grant-id={grant.grant_id}>
                <span class="host-peer__grant-text">
                    {grant.scopes.join(', ')}
                    <span class="host-peer__grant-meta">
                        {grant.revoked_at
                            ? t('hosts.peer.grant_revoked', { when: grant.revoked_at })
                            : grant.last_seen_at
                              ? t('hosts.peer.grant_seen', { when: grant.last_seen_at })
                              : t('hosts.peer.grant_unseen')}
                    </span>
                </span>
                {#if !grant.revoked_at}
                    <button type="button" class="oc-btn oc-btn--danger" data-peer-revoke disabled={busy} onclick={() => void revoke(grant)}>{t('hosts.revoke.action')}</button>
                {/if}
            </li>
        {/each}
    </ul>
{/if}

<div class="host-peer__actions">
    <button type="button" class="oc-btn oc-btn--danger" data-peer-unpair disabled={busy} onclick={() => void unpair()}>{t('hosts.unpair.action')}</button>
    <span class="host-peer__none">{t('hosts.unpair.hint')}</span>
</div>
{#if notice}
    <p class={notice.error ? 'host-detail__error' : 'host-detail__notice'} role={notice.error ? 'alert' : 'status'} data-peer-notice>{notice.text}</p>
{/if}

<style>
  @layer components {
    .host-detail__notice,
    .host-detail__error {
        margin: 8px 0 0;
        padding: 6px 8px;
        border-left: 2px solid var(--oc-cyan);
        background: var(--oc-ground-field);
        color: var(--oc-text-primary);
        font-size: 12px;
        overflow-wrap: anywhere;
    }
    .host-detail__error { border-left-color: var(--oc-coral); }
    .host-peer__head { margin: 12px 0 4px; }
    .host-peer__none { margin: 4px 0; color: var(--oc-text-muted); font-size: 12px; }
    .host-peer__grants { list-style: none; margin: 0; padding: 0; }
    .host-peer__grant {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        padding: 6px 0;
        box-shadow: 0 1px 0 var(--oc-line-faint);
        font-family: var(--font-mono);
        font-size: 12px;
    }
    .host-peer__grant-meta { display: block; color: var(--oc-text-muted); font-size: 11px; }
    .host-peer__actions { display: flex; align-items: center; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
  }
</style>
