
<script lang="ts">
    import { onMount } from 'svelte';
    import { t as reactiveT, authFetch, failureReason, type Translate } from '../sdk';
    import { Button, Select, State, Switch } from '../sdk/ui';

    interface Props { t?: Translate; fetcher?: typeof authFetch }
    const { t = reactiveT, fetcher = authFetch }: Props = $props();
    interface Choice { value: string; label: string }

    let ask = $state(false);
    let connected = $state(true);
    let open = $state(false);
    let sessions = $state<Choice[]>([]);
    let items = $state<Choice[]>([]);
    let session = $state('');
    let item = $state('');
    let busy = $state(false);
    let problem = $state('');
    let said = $state('');

    onMount(async () => {
        try {
            const state = await fetcher<{ ask_every_time?: boolean; connected?: boolean }>('/argent/classifier');
            ask = Boolean(state?.ask_every_time);
            connected = state?.connected !== false;
        } catch (error) { problem = failureReason(error); }
        const named = /\?session=([^&#]+)$/.exec(typeof window === 'undefined' ? '' : window.location.hash)?.[1];
        if (named) {
            let tmux = named;
            try { tmux = decodeURIComponent(named); } catch {  }
            await show(tmux);
        }
    });

    async function setAsk(next: boolean): Promise<void> {
        const before = ask;
        ask = next;
        problem = '';
        try { await fetcher('/argent/classifier', { method: 'PUT', body: JSON.stringify({ ask_every_time: next }) }); } catch (error) { ask = before; problem = failureReason(error); }
    }

    async function show(preselect = ''): Promise<void> {
        open = true;
        problem = said = '';
        try {
            const [listed, found] = await Promise.all([fetcher<unknown>('/sessions/list'), fetcher<{ items?: { id: string; kind: string; title: string }[] }>('/argent/work-items')]);
            const rows = (Array.isArray(listed) ? listed : []) as { session?: { id?: string }; label?: string | null; tmux_session?: string | null; host_key?: string }[];
            const local = rows.filter((r) => r.session?.id && (!r.host_key || r.host_key === 'local'));
            sessions = local.map((r) => ({ value: String(r.session?.id), label: r.label || r.tmux_session || String(r.session?.id) }));
            const chosen = preselect ? local.find((r) => r.tmux_session === preselect) : undefined;
            if (chosen) session = String(chosen.session?.id);
            items = (found?.items ?? []).map((i) => ({ value: i.id, label: `${i.kind}: ${i.title}` }));
        } catch (error) {
            problem = failureReason(error);
        }
    }

    async function send(): Promise<void> {
        busy = true;
        problem = said = '';
        try {
            await fetcher(`/argent/sessions/${encodeURIComponent(session)}/context`, { method: 'PUT', body: JSON.stringify({ work_item_id: item, source: 'picker' }) });
            said = t('argent.classifier.done');
        } catch (error) {
            problem = failureReason(error);
        } finally {
            busy = false;
        }
    }
</script>

<div data-argent="classifier">
    <Switch label={t('argent.classifier.ask')} hint={t('argent.classifier.ask_hint')} bind:checked={() => ask, (next) => void setAsk(next)} data-argent="classifier-ask" />
    {#if !connected}<p class="tm__sub" data-argent="classifier-needs-connection">{t('argent.shell.helper_needs_connection')}</p>{/if}
    {#if !open}
        <div class="tm__actions"><Button size="sm" data-argent="classifier-open" onclick={() => void show()}>{t('argent.classifier.open')}</Button></div>
    {:else}
        <p class="tm__sub">{t('argent.classifier.heading')}</p>
        <Select label={t('argent.classifier.session')} bind:value={session} options={[{ value: '', label: '-' }, ...sessions]} disabled={busy} data-argent="classifier-session" />
        <Select label={t('argent.classifier.item')} bind:value={item} options={[{ value: '', label: '-' }, ...items]} disabled={busy} data-argent="classifier-item" />
        <div class="tm__actions">
            <Button size="sm" variant="confirm" disabled={busy || !session || !item} data-argent="classifier-send" onclick={() => void send()}>{t('argent.classifier.send')}</Button>
            <Button size="sm" disabled={busy} data-argent="classifier-close" onclick={() => { open = false; }}>{t('argent.classifier.cancel')}</Button>
        </div>
        {#if said}<p class="tm__sub" role="status" data-argent="classifier-said">{said}</p>{/if}
    {/if}
    {#if problem}<State kind="error" inline title={problem} data-argent="classifier-problem" />{/if}
</div>
