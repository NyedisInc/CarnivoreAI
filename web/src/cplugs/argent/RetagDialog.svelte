
<script lang="ts">
    import { t as reactiveT, authFetch, failureReason, formatMicros, type Translate } from '../sdk';
    import { Button, Field, Select, State } from '../sdk/ui';

    interface Props { t?: Translate; fetcher?: typeof authFetch }
    const { t = reactiveT, fetcher = authFetch }: Props = $props();
    interface Choice { value: string; label: string }

    let open = $state(false);
    let sessions = $state<Choice[]>([]);
    let items = $state<Choice[]>([]);
    let session = $state('');
    let item = $state('');
    let since = $state('');
    let until = $state('');
    let reason = $state('');
    let busy = $state(false);
    let problem = $state('');
    let said = $state('');

    function instant(local: string): string {
        const moment = new Date(local);
        return local && !Number.isNaN(moment.getTime()) ? moment.toISOString() : '';
    }
    const ready = $derived(Boolean(session && item && instant(since) && instant(until) && reason.trim().length >= 3));

    async function show(): Promise<void> {
        open = true;
        problem = said = '';
        try {
            const [listed, found] = await Promise.all([fetcher<unknown>('/sessions/list'), fetcher<{ items?: { id: string; kind: string; title: string }[] }>('/argent/work-items')]);
            const rows = (Array.isArray(listed) ? listed : []) as { session?: { id?: string }; label?: string | null; tmux_session?: string | null; host_key?: string }[];
            sessions = rows.filter((r) => r.session?.id && (!r.host_key || r.host_key === 'local')).map((r) => ({ value: String(r.session?.id), label: r.label || r.tmux_session || String(r.session?.id) }));
            items = (found?.items ?? []).map((i) => ({ value: i.id, label: `${i.kind}: ${i.title}` }));
        } catch (error) {
            problem = failureReason(error);
        }
    }

    /* a refusal is shown in plain words by its code */
    async function send(): Promise<void> {
        busy = true;
        problem = said = '';
        try {
            const done = await fetcher<{ moved_micros?: number | null }>('/argent/retag', {
                method: 'POST', body: JSON.stringify({ session_id: session, since: instant(since), until: instant(until), work_item_id: item, reason: reason.trim() }),
            });
            said = t('argent.retag.done', { amount: formatMicros(done?.moved_micros ?? null) });
            reason = '';
        } catch (error) {
            const code = (error as { payload?: { detail?: { code?: string } } }).payload?.detail?.code ?? '';
            problem = ['bad_range', 'range_too_long', 'bad_reason', 'blocked_secret', 'not_own_session'].includes(code) ? t(`argent.retag.err.${code}`) : failureReason(error);
        } finally {
            busy = false;
        }
    }
</script>

<div data-argent="retag">
    {#if !open}
        <div class="tm__actions"><Button size="sm" data-argent="retag-open" onclick={() => void show()}>{t('argent.retag.open')}</Button></div>
    {:else}
        <p class="tm__sub">{t('argent.retag.heading')}</p>
        <Select label={t('argent.retag.session')} bind:value={session} options={[{ value: '', label: '-' }, ...sessions]} disabled={busy} data-argent="retag-session" />
        <Field label={t('argent.retag.since')} type="datetime-local" bind:value={since} disabled={busy} data-argent="retag-since" />
        <Field label={t('argent.retag.until')} type="datetime-local" bind:value={until} disabled={busy} data-argent="retag-until" help={t('argent.retag.range_hint')} />
        <Select label={t('argent.retag.item')} bind:value={item} options={[{ value: '', label: '-' }, ...items]} disabled={busy} data-argent="retag-item" />
        <Field label={t('argent.retag.reason')} bind:value={reason} maxlength={200} disabled={busy} spellcheck={false} autocomplete="off" data-argent="retag-reason" />
        <div class="tm__actions">
            <Button size="sm" variant="confirm" disabled={busy || !ready} data-argent="retag-send" onclick={() => void send()}>{t('argent.retag.send')}</Button>
            <Button size="sm" disabled={busy} data-argent="retag-close" onclick={() => { open = false; }}>{t('argent.retag.cancel')}</Button>
        </div>
        {#if said}<p class="tm__sub" role="status" data-argent="retag-said">{said}</p>{/if}
        {#if problem}<State kind="error" inline title={problem} data-argent="retag-problem" />{/if}
    {/if}
</div>
