
<script lang="ts">
    import Button from '../base/Button.svelte';
    import Field from '../base/Field.svelte';
    import IconButton from '../base/IconButton.svelte';
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

    $effect(() => {
        const timer = setTimeout(() => document.getElementById('modal-host-label')?.focus(), 100);
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
            <IconButton label={t('modal.close')} variant="close" icon="close" iconSize={14} data-modal-close
                disabled={busy} onclick={() => close(null)} />
        </div>
    {/snippet}
    <Field
        label={t('hosts.add.label_label')}
        id="modal-host-label"
        placeholder={t('hosts.add.label_placeholder')}
        autocomplete="off"
        disabled={busy}
        bind:value={label}
        onkeydown={onKey}
    />
    <Field
        label={t('hosts.add.target_label')}
        id="modal-host-target"
        placeholder={t('hosts.add.target_placeholder')}
        help={t('hosts.add.target_hint')}
        autocomplete="off"
        disabled={busy}
        bind:value={sshTarget}
        onkeydown={onKey}
    />
    <Field
        label={t('hosts.add.port_label')}
        id="modal-host-port"
        inputmode="numeric"
        placeholder={t('hosts.add.port_placeholder')}
        autocomplete="off"
        disabled={busy}
        bind:value={sshPort}
        onkeydown={onKey}
    />
    <Field
        label={t('hosts.add.socket_label')}
        id="modal-host-socket"
        placeholder={t('hosts.add.socket_placeholder')}
        help={t('hosts.add.socket_hint')}
        autocomplete="off"
        disabled={busy}
        bind:value={socket}
        onkeydown={onKey}
    />
    {#if error}
        <p class="modal-description" role="alert" data-host-add-error style="color: var(--oc-coral);">{error}</p>
    {/if}
    {#snippet footer()}
        <Button disabled={busy} onclick={() => close(null)}>{t('hosts.add.cancel')}</Button>
        <Button variant="confirm" disabled={!canSubmit} data-host-add-confirm onclick={() => void submit()}>{busy ? t('hosts.add.busy') : t('hosts.add.confirm')}</Button>
    {/snippet}
</ModalShell>
