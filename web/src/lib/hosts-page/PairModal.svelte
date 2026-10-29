
<script lang="ts">
    import Button from '../base/Button.svelte';
    import Field from '../base/Field.svelte';
    import IconButton from '../base/IconButton.svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import ModalShell from '../launchpad/ModalShell.svelte';
    import type { Translate } from '../sessions/types';
    import { createFederationApi, errorCode, type DiscoveredMac, type FederationApi, type PairPending, type PeerRow } from './federation-api';
    import PairSas from './PairSas.svelte';

    interface Props {
        fed?: FederationApi;
        t?: Translate;
        found?: DiscoveredMac | null;
        close: (value: PeerRow | null) => void;
    }

    const { fed, t = reactiveT, found = null, close }: Props = $props();
    // svelte-ignore state_referenced_locally
    const calls: FederationApi = fed ?? createFederationApi();

    // svelte-ignore state_referenced_locally
    let target = $state(found ? found.host.replace(/\.$/, '') : '');
    // svelte-ignore state_referenced_locally
    let port = $state(found && found.port !== 22 ? String(found.port) : '');
    let nonce = $state('');
    let code = $state('');
    let needsCode = $state<string | null>(null);
    let busy = $state(false);
    let error = $state('');
    let held = $state<PairPending | null>(null);

    const canSubmit = $derived(
        !busy && target.trim() !== '' && (needsCode === null || (nonce.trim() !== '' && code.trim() !== '')),
    );

    async function submit(): Promise<void> {
        if (!canSubmit) return;
        busy = true;
        error = '';
        const sshPort = port.trim() ? Number.parseInt(port.trim(), 10) : NaN;
        try {
            held = await calls.pair({
                ssh_target: target.trim(),
                ...(Number.isFinite(sshPort) ? { ssh_port: sshPort } : {}),
                ...(found ? { discovered_name: found.name } : {}),
                ...(needsCode !== null ? { typed_nonce: nonce.trim(), typed_code: code.trim() } : {}),
            });
            busy = false;
        } catch (err) {
            busy = false;
            if (errorCode(err) === 'typed_code_required' && needsCode === null) {
                needsCode = err instanceof Error ? err.message : '';
            } else {
                error = t('hosts.pair.failed', { reason: err instanceof Error ? err.message : '' });
            }
        }
    }

    async function answer(match: boolean): Promise<void> {
        if (!held || busy) return;
        busy = true;
        error = '';
        try {
            const done = await calls.confirmPair(held.nonce, match);
            busy = false;
            close(match && 'key' in done ? done : null);
        } catch (err) {
            busy = false;
            error = t('hosts.sas.failed', { reason: err instanceof Error ? err.message : '' });
        }
    }

    function dismiss(): void {
        if (held) void answer(false);
        else close(null);
    }

    function onKey(event: KeyboardEvent): void {
        if (event.key !== 'Enter') return;
        event.preventDefault();
        void submit();
    }
</script>

<ModalShell title={t('hosts.pair.title')} overlayClass="text-prompt-modal na-flow" dismissable={!busy} onCancel={dismiss}>
    {#snippet head()}
        <div class="text-prompt-modal__head">
            <span class="text-prompt-modal__verb">&raquo; {held ? t('hosts.sas.title') : needsCode === null ? t('hosts.pair.title') : t('hosts.pair.code_title')}</span>
            <IconButton label={t('modal.close')} variant="close" icon="close" iconSize={14} data-modal-close disabled={busy} onclick={dismiss} />
        </div>
    {/snippet}
    {#if held}
        <PairSas {t} sas={held.sas} label={held.label} fid={held.fid} lead={t('hosts.sas.lead')} />
        {#if held.peer_owner_confirms}
            <p class="modal-description" data-fed-sas-peer-confirms>{t('hosts.sas.peer_confirms')}</p>
        {/if}
    {:else if needsCode === null}
        <Field
            label={t('hosts.pair.target_label')}
            id="modal-pair-target"
            placeholder={t('hosts.pair.target_placeholder')}
            help={t('hosts.pair.target_hint')}
            autocomplete="off"
            disabled={busy}
            bind:value={target}
            onkeydown={onKey}
        />
        <Field
            label={t('hosts.pair.port_label')}
            id="modal-pair-port"
            inputmode="numeric"
            placeholder={t('hosts.pair.port_placeholder')}
            autocomplete="off"
            disabled={busy}
            bind:value={port}
            onkeydown={onKey}
        />
        {#if found}
            <p class="modal-description" data-fed-pair-hint={found.state}>
                {found.state === 'pinned' ? t('hosts.found.state.pinned') : found.state === 'identity_changed' ? t('hosts.pair.identity_changed') : t('hosts.found.state.new')}
            </p>
        {/if}
    {:else}
        <p class="modal-description" data-fed-pair-reason>{needsCode || t('hosts.pair.code_reason')}</p>
        <Field label={t('hosts.code.nonce_label')} id="modal-pair-nonce" autocomplete="off" disabled={busy} bind:value={nonce} onkeydown={onKey} />
        <Field label={t('hosts.code.code_label')} id="modal-pair-code" help={t('hosts.pair.code_hint')} autocomplete="off" disabled={busy} bind:value={code} onkeydown={onKey} />
    {/if}
    {#if error}
        <p class="modal-description" role="alert" data-fed-pair-error style="color: var(--oc-coral);">{error}</p>
    {/if}
    {#snippet footer()}
        {#if held}
            <Button variant="danger" disabled={busy} data-fed-sas-differ onclick={() => void answer(false)}>{t('hosts.sas.differ')}</Button>
            <Button variant="confirm" disabled={busy} data-fed-sas-match onclick={() => void answer(true)}>{t('hosts.sas.match')}</Button>
        {:else}
            <Button disabled={busy} onclick={() => close(null)}>{t('hosts.fed.cancel')}</Button>
            <Button variant="confirm" disabled={!canSubmit} data-fed-pair-confirm onclick={() => void submit()}>{busy ? t('hosts.pair.busy') : t('hosts.pair.confirm')}</Button>
        {/if}
    {/snippet}
</ModalShell>
