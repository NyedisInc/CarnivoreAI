
<script lang="ts">
    import { t as reactiveT } from '../../i18n/index.svelte';
    import type { Translate } from '../../sessions/types';
    import { Button } from '../../base';
    import Check from '../../../opscenter/ui/Check.svelte';
    import '../../settings-page/panel-kit/panel-kit.css';
    import './destinations.css';
    import { isRateLimited, testDestination, type Destination, type ExtrasBody, type Fetcher, type Kind } from './api';
    import { failureKey } from './form-logic';
    import DestinationExtras from './DestinationExtras.svelte';

    interface Props {
        t?: Translate;
        destination: Destination;
        kind: Kind | undefined;
        busy?: boolean;
        fetcher?: Fetcher;
        onToggle: (enabled: boolean) => void;
        onEdit: () => void;
        onDelete: () => void;
        onExtras: (body: ExtrasBody) => void;
        onPin: () => void;
        onReset: () => void;
    }
    const { t = reactiveT, destination, kind, busy = false, fetcher, onToggle, onEdit, onDelete, onExtras, onPin, onReset }: Props = $props();

    type TestState = { state: 'idle' } | { state: 'sending' } | { state: 'ok' } | { state: 'failed'; text: string };
    let test = $state<TestState>({ state: 'idle' });
    let confirming = $state(false);
    let extrasOpen = $state(false);

    const status = $derived(destination.status);
    const isLocal = $derived(destination.scope === 'local' || destination.pinned);
    const managedElsewhere = $derived(kind?.virtual === true);
    const when = (ts: number): string => new Date(ts * 1000).toLocaleString();

    async function runTest(): Promise<void> {
        test = { state: 'sending' };
        try {
            const answer = await testDestination(destination.id, fetcher);
            test = answer.ok ? { state: 'ok' } : { state: 'failed', text: answer.failure ? t(failureKey(answer.failure)) : t('settings.notify.dest.test.failed') };
        } catch (error) {
            test = { state: 'failed', text: isRateLimited(error) ? t('settings.notify.dest.test.wait') : t('settings.notify.dest.test.failed') };
        }
    }
</script>

<div class="tm__srv" class:tm__srv--off={!destination.enabled} data-notify-dest={destination.id}>
    <div class="tm__srv-head">
        <span class="tm__srv-name" data-notify="name">{destination.name}</span>
        <span class="tm__sub" data-notify="kind-name">{kind ? t(kind.label_key) : destination.kind}</span>
        {#if isLocal}<span class="nd-badge" data-notify="local-badge">{t('settings.notify.dest.local')}</span>{/if}
        <Check role="switch" label={t('settings.notify.dest.enabled')} checked={destination.enabled} disabled={busy} data-notify="toggle" onToggle={onToggle} />
        <span class="tm__srv-tools">
            <Button disabled={busy || test.state === 'sending'} data-notify="test" onclick={() => void runTest()}>{t(test.state === 'sending' ? 'settings.notify.dest.test.sending' : 'settings.notify.dest.test.button')}</Button>
            <Button disabled={busy} aria-expanded={extrasOpen} data-notify="extras-toggle" onclick={() => (extrasOpen = !extrasOpen)}>{t('settings.notify.dest.extras.button')}</Button>
            {#if !managedElsewhere}<Button disabled={busy} data-notify="edit" onclick={onEdit}>{t('settings.notify.dest.edit')}</Button>{/if}
            {#if destination.pinned}
                <Button disabled={busy} data-notify="reset" onclick={onReset}>{t('settings.notify.dest.reset')}</Button>
            {:else if destination.scope === 'global'}
                <Button disabled={busy} data-notify="pin" onclick={onPin}>{t('settings.notify.dest.pin')}</Button>
            {/if}
            {#if !managedElsewhere}<Button variant="danger" disabled={busy} data-notify="delete" onclick={() => (confirming = true)}>{t('settings.notify.dest.delete')}</Button>{/if}
        </span>
    </div>
    {#if kind}
        <p class="tm__sub" data-notify="secrets-state">
            {#each kind.secret_fields as field (field.name)}
                <span class="nd-secret">{t(`settings.notify.field.${field.name}`)}: {t(destination.secrets[field.name]?.set ? 'settings.notify.dest.secret_set' : 'settings.notify.dest.secret_unset')}</span>
            {/each}
        </p>
    {/if}
    <p class="nd-status" data-notify="status">
        {#if !status}
            <span class="tm__sub">{t('settings.notify.dest.status.never')}</span>
        {:else}
            {#if status.last_ok_ts}<span class="tm__note">{t('settings.notify.dest.status.ok', { when: when(status.last_ok_ts) })}</span>{/if}
            {#if status.last_failure}<span class="tm__problem">{t('settings.notify.dest.status.failed', { why: t(failureKey(status.last_failure)) })}</span>{/if}
            {#if status.disabled_reason}<span class="tm__problem" data-notify="disabled-reason">{t('settings.notify.dest.status.disabled', { reason: status.disabled_reason })}</span>{/if}
        {/if}
    </p>
    {#if test.state === 'ok'}<p class="tm__note" role="status" data-notify="test-result" data-state="ok">{t('settings.notify.dest.test.ok')}</p>{/if}
    {#if test.state === 'failed'}<p class="tm__problem" role="alert" data-notify="test-result" data-state="failed">{test.text}</p>{/if}
    {#if extrasOpen}
        <DestinationExtras {t} {destination} {kind} {busy} onSave={(body) => onExtras(body)} />
    {/if}
    {#if confirming}
        <div class="tm__warn" role="alert" data-notify="delete-warning">
            <p>{t('settings.notify.dest.delete_warning', { name: destination.name })}</p>
            <div class="tm__actions">
                <Button data-notify="delete-cancel" onclick={() => (confirming = false)}>{t('settings.notify.dest.form.cancel')}</Button>
                <Button variant="danger" disabled={busy} data-notify="delete-confirm" onclick={() => { confirming = false; onDelete(); }}>{t('settings.notify.dest.delete_confirm')}</Button>
            </div>
        </div>
    {/if}
</div>
