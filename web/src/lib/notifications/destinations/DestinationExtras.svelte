
<script lang="ts">
    import { t as reactiveT } from '../../i18n/index.svelte';
    import type { Translate } from '../../sessions/types';
    import { Button, Field } from '../../base';
    import Check from '../../../opscenter/ui/Check.svelte';
    import '../../settings-page/panel-kit/panel-kit.css';
    import './destinations.css';
    import type { Destination, ExtrasBody, Kind } from './api';
    import { splitList } from './form-logic';

    interface Props {
        t?: Translate;
        destination: Destination;
        kind: Kind | undefined;
        busy?: boolean;
        onSave: (body: ExtrasBody) => void;
    }
    const { t = reactiveT, destination, kind, busy = false, onSave }: Props = $props();

    // svelte-ignore state_referenced_locally
    const e = destination.extras;
    // svelte-ignore state_referenced_locally
    let away = $state(e.away);
    // svelte-ignore state_referenced_locally
    let quietOn = $state(e.quiet !== null);
    // svelte-ignore state_referenced_locally
    let start = $state(e.quiet?.start ?? '22:00');
    // svelte-ignore state_referenced_locally
    let end = $state(e.quiet?.end ?? '07:00');
    // svelte-ignore state_referenced_locally
    let reminderOn = $state(e.reminder_minutes !== null);
    // svelte-ignore state_referenced_locally
    let minutes = $state(String(e.reminder_minutes ?? 10));
    // svelte-ignore state_referenced_locally
    let projects = $state(e.projects.join(', '));
    // svelte-ignore state_referenced_locally
    let details = $state(e.details);
    // svelte-ignore state_referenced_locally
    let localOnly = $state(destination.scope === 'local' || destination.pinned);

    const detailsAllowed = $derived(kind?.details_allowed === true && kind.sms_like !== true);
    const minutesOk = $derived(!reminderOn || (Number(minutes) >= 1 && Number(minutes) <= 1440 && Number.isInteger(Number(minutes))));

    function body(): ExtrasBody {
        const out: ExtrasBody = {
            away,
            quiet: quietOn ? { start, end } : null,
            reminder_minutes: reminderOn ? Number(minutes) : null,
            projects: splitList(projects),
        };
        if (detailsAllowed) out.details = details;
        if (destination.scope === 'global') out.scope = localOnly ? 'local' : 'global';
        return out;
    }
</script>

<div class="nd-extras" data-notify="extras">
    <Check role="switch" label={t('settings.notify.dest.extras.away')} hint={t('settings.notify.dest.extras.away_hint')} checked={away} disabled={busy} data-notify="extra-away"
        onToggle={(next) => (away = next)} />
    <div class="tm__field">
        <Check role="switch" label={t('settings.notify.dest.extras.quiet')} hint={t('settings.notify.dest.extras.quiet_hint')} checked={quietOn} disabled={busy} data-notify="extra-quiet"
            onToggle={(next) => (quietOn = next)} />
        {#if quietOn}
            <div class="nd-times">
                <label class="tm__field"><span class="oc-key">{t('settings.notify.dest.extras.quiet_start')}</span>
                    <Field type="time" bind:value={start} disabled={busy} data-notify="extra-quiet-start" /></label>
                <label class="tm__field"><span class="oc-key">{t('settings.notify.dest.extras.quiet_end')}</span>
                    <Field type="time" bind:value={end} disabled={busy} data-notify="extra-quiet-end" /></label>
            </div>
        {/if}
    </div>
    <div class="tm__field">
        <Check role="switch" label={t('settings.notify.dest.extras.reminder')} hint={t('settings.notify.dest.extras.reminder_hint')} checked={reminderOn} disabled={busy}
            data-notify="extra-reminder" onToggle={(next) => (reminderOn = next)} />
        {#if reminderOn}
            <label class="tm__field"><span class="oc-key">{t('settings.notify.dest.extras.reminder_minutes')}</span>
                <Field type="number" min="1" max="1440" bind:value={minutes} disabled={busy} data-notify="extra-reminder-minutes" /></label>
        {/if}
    </div>
    <label class="tm__field">
        <span class="oc-key">{t('settings.notify.dest.extras.projects')}</span>
        <Field bind:value={projects} disabled={busy} autocomplete="off" spellcheck={false} placeholder={t('settings.notify.dest.extras.projects_hint')}
            data-notify="extra-projects" />
    </label>
    {#if detailsAllowed}
        <Check role="switch" label={t('settings.notify.dest.extras.details')} hint={t('settings.notify.dest.extras.details_hint')} checked={details} disabled={busy}
            data-notify="extra-details" onToggle={(next) => (details = next)} />
    {/if}
    {#if destination.scope === 'global'}
        <Check label={t('settings.notify.dest.form.local_only')} hint={t('settings.notify.dest.extras.local_hint')} checked={localOnly} disabled={busy} data-notify="extra-local"
            onToggle={(next) => (localOnly = next)} />
    {/if}
    <div class="tm__actions">
        <Button variant="confirm" disabled={busy || !minutesOk} data-notify="extras-save" onclick={() => onSave(body())}>{t('settings.notify.dest.extras.save')}</Button>
    </div>
</div>
