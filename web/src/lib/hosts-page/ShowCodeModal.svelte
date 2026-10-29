
<script lang="ts">
    import { t as reactiveT } from '../i18n/index.svelte';
    import ModalShell from '../launchpad/ModalShell.svelte';
    import type { Translate } from '../sessions/types';
    import { createFederationApi, type FederationApi, type PairCode, type PendingPair } from './federation-api';
    import PairSas from './PairSas.svelte';

    interface Props {
        fed?: FederationApi;
        t?: Translate;
        pollMs?: number;
        close: (value: null) => void;
    }

    const { fed, t = reactiveT, pollMs = 2000, close }: Props = $props();
    // svelte-ignore state_referenced_locally
    const calls: FederationApi = fed ?? createFederationApi();

    let offer = $state<PairCode | null>(null);
    let busy = $state(false);
    let error = $state('');

    async function make(): Promise<void> {
        busy = true;
        error = '';
        try {
            offer = await calls.beginCode();
        } catch (err) {
            offer = null;
            error = t('hosts.code.failed', { reason: err instanceof Error ? err.message : '' });
        } finally {
            busy = false;
        }
    }

    $effect(() => {
        void make();
    });

    let waiting = $state<PendingPair | null>(null);
    let answered = $state(false);

    async function poll(): Promise<void> {
        if (!offer) return;
        try {
            const mine = (await calls.pending()).find((p) => p.nonce === offer?.nonce) ?? null;
            if (mine === null && answered) close(null);
            waiting = mine;
        } catch {
        }
    }

    $effect(() => {
        const timer = setInterval(() => void poll(), pollMs);
        return () => clearInterval(timer);
    });

    async function answer(match: boolean): Promise<void> {
        if (!waiting || busy) return;
        busy = true;
        error = '';
        try {
            if (match) {
                answered = true;
                const done = await calls.confirmPending(waiting.nonce);
                if (done.state === 'active') close(null);
            } else {
                await calls.cancelPending(waiting.nonce);
                waiting = null;
                close(null);
            }
        } catch (err) {
            error = t('hosts.sas.failed', { reason: err instanceof Error ? err.message : '' });
        } finally {
            busy = false;
        }
    }
</script>

<ModalShell title={t('hosts.code.title')} overlayClass="text-prompt-modal na-flow" onCancel={() => close(null)}>
    {#snippet head()}
        <div class="text-prompt-modal__head">
            <span class="text-prompt-modal__verb">&raquo; {t('hosts.code.title')}</span>
            <button type="button" class="modal-close" aria-label={t('modal.close')} onclick={() => close(null)}>&times;</button>
        </div>
    {/snippet}
    {#if waiting}
        <PairSas {t} sas={waiting.sas} label={waiting.label} fid={waiting.fid} lead={t('hosts.sas.this_mac_lead')} />
        {#if answered}
            <p class="modal-description" role="status" data-fed-sas-waiting>{t('hosts.sas.waiting')}</p>
        {/if}
    {:else if offer}
        <div class="modal-input-group">
            <span class="modal-label">{t('hosts.code.nonce_label')}</span>
            <code class="fed-code" data-fed-code-nonce>{offer.nonce}</code>
        </div>
        <div class="modal-input-group">
            <span class="modal-label">{t('hosts.code.code_label')}</span>
            <code class="fed-code" data-fed-code-value>{offer.code}</code>
        </div>
        <p class="modal-description">{t('hosts.code.lead', { minutes: Math.round(offer.expires_in / 60) })}</p>
    {:else if busy}
        <p class="modal-description" role="status">{t('hosts.code.busy')}</p>
    {/if}
    {#if error}
        <p class="modal-description" role="alert" data-fed-code-error style="color: var(--oc-coral);">{error}</p>
    {/if}
    {#snippet footer()}
        {#if waiting}
            <button class="modal-btn modal-btn-danger" disabled={busy} data-fed-sas-differ onclick={() => void answer(false)}>{t('hosts.sas.differ')}</button>
            <button class="modal-btn modal-btn-confirm" disabled={busy || answered} data-fed-sas-match onclick={() => void answer(true)}>{t('hosts.sas.match')}</button>
        {:else}
            <button class="modal-btn modal-btn-secondary" disabled={busy} data-fed-code-new onclick={() => void make()}>{t('hosts.code.new')}</button>
            <button class="modal-btn modal-btn-confirm" onclick={() => close(null)}>{t('hosts.code.done')}</button>
        {/if}
    {/snippet}
</ModalShell>

<style>
  @layer components {
    .fed-code {
        display: block;
        padding: 6px 8px;
        background: var(--oc-ground-field);
        border: 1px solid var(--oc-line-panel);
        border-radius: var(--oc-radius-sm);
        color: var(--oc-text-bright);
        font-family: var(--font-mono);
        font-size: var(--oc-fs-title);
        letter-spacing: 0.12em;
        overflow-wrap: anywhere;
        user-select: all;
    }
  }
</style>
