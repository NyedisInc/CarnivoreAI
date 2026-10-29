
<script lang="ts">
    import { t as reactiveT } from '../i18n/index.svelte';
    import ModalShell from '../launchpad/ModalShell.svelte';
    import type { Translate } from '../sessions/types';
    import { createHostsApi, type HostRow, type HostsApi } from './hosts-adapter';

    interface Props {
        api?: HostsApi;
        t?: Translate;
        initial?: { label?: string; ssh_target?: string };
        close: (value: HostRow | null) => void;
    }

    const { api, t = reactiveT, initial, close }: Props = $props();
    // svelte-ignore state_referenced_locally
    const calls: HostsApi = api ?? createHostsApi();

    // svelte-ignore state_referenced_locally
    let label = $state(initial?.label ?? '');
    // svelte-ignore state_referenced_locally
    let sshTarget = $state(initial?.ssh_target ?? '');
    let sshPort = $state('');
    let socket = $state('');
    let busy = $state(false);
    let error = $state('');
    let labelEl: HTMLInputElement | null = $state(null);

    $effect(() => {
        const timer = setTimeout(() => labelEl?.focus(), 100);
        return () => clearTimeout(timer);
    });

    const canSubmit = $derived(!busy && label.trim() !== '' && sshTarget.trim() !== '');

    async function submit(): Promise<void> {
        if (!canSubmit || busy) return;
        busy = true;
        error = '';
        const port = sshPort.trim() ? Number.parseInt(sshPort.trim(), 10) : null;
        try {
            const row = await calls.add({
                label: label.trim(),
                ssh_target: sshTarget.trim(),
                ssh_port: Number.isFinite(port) ? port : null,
                socket: socket.trim() || null,
            });
            busy = false;
            close(row);
        } catch (err) {
            busy = false;
            error = t('hosts.add.failed', { reason: err instanceof Error ? err.message : '' });
        }
    }

    function onKey(event: KeyboardEvent): void {
        if (event.key !== 'Enter') return;
        event.preventDefault();
        void submit();
    }
</script>

<ModalShell title={t('hosts.add.title')} overlayClass="text-prompt-modal na-flow" dismissable={!busy} onCancel={() => close(null)}>
    {#snippet head()}
        <div class="text-prompt-modal__head">
            <span class="text-prompt-modal__verb">&raquo; {t('hosts.add.title')}</span>
            <button type="button" class="modal-close" aria-label={t('modal.close')}
                disabled={busy} onclick={() => close(null)}>&times;</button>
        </div>
    {/snippet}
    <div class="modal-input-group">
        <label class="modal-label" for="modal-host-label">{t('hosts.add.label_label')}</label>
        <input
            type="text"
            class="modal-input"
            id="modal-host-label"
            placeholder={t('hosts.add.label_placeholder')}
            autocomplete="off"
            disabled={busy}
            bind:this={labelEl}
            bind:value={label}
            onkeydown={onKey}
        />
    </div>
    <div class="modal-input-group">
        <label class="modal-label" for="modal-host-target">{t('hosts.add.target_label')}</label>
        <input
            type="text"
            class="modal-input"
            id="modal-host-target"
            placeholder={t('hosts.add.target_placeholder')}
            autocomplete="off"
            disabled={busy}
            bind:value={sshTarget}
            onkeydown={onKey}
        />
        <div class="modal-description">{t('hosts.add.target_hint')}</div>
    </div>
    <div class="modal-input-group">
        <label class="modal-label" for="modal-host-port">{t('hosts.add.port_label')}</label>
        <input
            type="text"
            inputmode="numeric"
            class="modal-input"
            id="modal-host-port"
            placeholder={t('hosts.add.port_placeholder')}
            autocomplete="off"
            disabled={busy}
            bind:value={sshPort}
            onkeydown={onKey}
        />
    </div>
    <div class="modal-input-group">
        <label class="modal-label" for="modal-host-socket">{t('hosts.add.socket_label')}</label>
        <input
            type="text"
            class="modal-input"
            id="modal-host-socket"
            placeholder={t('hosts.add.socket_placeholder')}
            autocomplete="off"
            disabled={busy}
            bind:value={socket}
            onkeydown={onKey}
        />
        <div class="modal-description">{t('hosts.add.socket_hint')}</div>
    </div>
    {#if error}
        <p class="modal-description" role="alert" data-host-add-error style="color: var(--oc-coral);">{error}</p>
    {/if}
    {#snippet footer()}
        <button class="modal-btn modal-btn-secondary" disabled={busy} onclick={() => close(null)}
            >{t('hosts.add.cancel')}</button
        >
        <button class="modal-btn modal-btn-confirm" disabled={!canSubmit} data-host-add-confirm onclick={() => void submit()}
            >{busy ? t('hosts.add.busy') : t('hosts.add.confirm')}</button
        >
    {/snippet}
</ModalShell>
