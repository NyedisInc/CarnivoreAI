
<script lang="ts">
    import { onMount } from 'svelte';
    import { t as reactiveT } from '../../i18n/index.svelte';
    import type { Translate } from '../../sessions/types';
    import '../../settings-page/panel-kit/panel-kit.css';
    import './destinations.css';
    import { errorText } from '../../settings-page/panel-kit/error-text';
    import { copyText } from '../../settings-page/mcp-panel/api';
    import { createDestination, deleteDestination, patchDestination, putExtras, resetOverride, type Destination, type ExtrasBody, type Fetcher } from './api';
    import { addableKinds, createBody, kindOf, patchBody, saveProblem, type Draft } from './form-logic';
    import { attach, notify, refresh, upsert } from './store.svelte';
    import DestinationCard from './DestinationCard.svelte';
    import DestinationForm from './DestinationForm.svelte';

    interface Props {
        t?: Translate;
        fetcher?: Fetcher;
    }
    const { t = reactiveT, fetcher }: Props = $props();

    let editing = $state<string | null>(null);
    let busy = $state(false);
    let problem = $state('');
    let note = $state('');
    let signing = $state<{ name: string; value: string } | null>(null);
    let copied = $state(false);

    onMount(() => attach(fetcher));

    async function act(work: () => Promise<void>): Promise<boolean> {
        busy = true;
        problem = '';
        note = '';
        try {
            await work();
            return true;
        } catch (error) {
            problem = saveProblem(error, t) ?? errorText(error);
            return false;
        } finally {
            busy = false;
            await refresh();
        }
    }

    async function save(draft: Draft, scope: 'global' | 'local'): Promise<void> {
        const kind = kindOf(notify.kinds, draft.kind);
        if (!kind) return;
        const saved = notify.destinations.find((d) => d.id === editing);
        const done = await act(async () => {
            if (!saved) {
                const made = await createDestination(createBody(kind, draft, scope), fetcher);
                upsert(made.destination);
                if (made.signing_secret) signing = { name: made.destination.name, value: made.signing_secret };
                return;
            }
            upsert((await patchDestination(saved.id, patchBody(kind, draft, saved), fetcher)).destination);
        });
        if (done) {
            editing = null;
            note = t('settings.notify.dest.saved');
        }
    }

    const toggle = (d: Destination, enabled: boolean): Promise<boolean> =>
        act(async () => upsert((await patchDestination(d.id, d.pinned ? { enabled, scope: 'local' } : { enabled }, fetcher)).destination));
    const pin = (d: Destination): Promise<boolean> =>
        act(async () => upsert((await patchDestination(d.id, { enabled: d.enabled, scope: 'local' }, fetcher)).destination));
    const reset = (d: Destination): Promise<boolean> => act(async () => void (await resetOverride(`dest/${d.id}`, fetcher)));
    const remove = (d: Destination): Promise<boolean> => act(async () => void (await deleteDestination(d.id, fetcher)));
    const saveExtras = (d: Destination, body: ExtrasBody): Promise<boolean> =>
        act(async () => upsert((await putExtras(d.id, body, fetcher)).destination));

    async function copySecret(): Promise<void> {
        if (!signing) return;
        try {
            await copyText(signing.value);
            copied = true;
        } catch {
            problem = t('settings.notify.dest.signing.copy_failed');
        }
    }
</script>

<div class="tm" data-notify="panel">
    <p class="tm__sub">{t('settings.notify.dest.intro')}</p>
    {#if signing}
        <div class="tm__warn" role="alert" data-notify="signing">
            <p>{t('settings.notify.dest.signing.title', { name: signing.name })}</p>
            <code class="tm__code" data-notify="signing-value">{signing.value}</code>
            <p>{t('settings.notify.dest.signing.once')}</p>
            <div class="tm__actions">
                <button type="button" class="modal-btn modal-btn-secondary" data-notify="signing-copy" onclick={() => void copySecret()}>{t(copied ? 'settings.notify.dest.signing.copied' : 'settings.notify.dest.signing.copy')}</button>
                <button type="button" class="modal-btn modal-btn-confirm" data-notify="signing-done" onclick={() => { signing = null; copied = false; }}>{t('settings.notify.dest.signing.done')}</button>
            </div>
        </div>
    {/if}
    {#each notify.destinations as destination (destination.id)}
        {@const kind = kindOf(notify.kinds, destination.kind)}
        {#if editing === destination.id && kind}
            <DestinationForm {t} kinds={notify.kinds} {destination} {busy} onSave={(d, s) => void save(d, s)} onCancel={() => (editing = null)} />
        {:else}
            <DestinationCard {t} {destination} {kind} {busy} {fetcher} onToggle={(on) => void toggle(destination, on)} onEdit={() => (editing = destination.id)}
                onDelete={() => void remove(destination)} onExtras={(body) => void saveExtras(destination, body)} onPin={() => void pin(destination)} onReset={() => void reset(destination)} />
        {/if}
    {/each}
    {#if notify.loaded && notify.destinations.length === 0}<p class="tm__sub" data-notify="none">{t('settings.notify.dest.none')}</p>{/if}
    {#if editing === 'new' && addableKinds(notify.kinds).length > 0}
        <DestinationForm {t} kinds={addableKinds(notify.kinds)} destination={null} {busy} onSave={(d, s) => void save(d, s)} onCancel={() => (editing = null)} />
    {:else}
        <div class="tm__actions">
            <button type="button" class="oc-btn oc-btn--confirm" disabled={busy || addableKinds(notify.kinds).length === 0} data-notify="add" onclick={() => (editing = 'new')}>{t('settings.notify.dest.add')}</button>
        </div>
    {/if}
    {#if note}<p class="tm__note" role="status" data-notify="note">{note}</p>{/if}
    {#if problem}<p class="tm__problem" role="alert" data-notify="problem">{problem}</p>{/if}
    {#if notify.problem}<p class="tm__problem" role="alert" data-notify="load-problem">{notify.problem}</p>{/if}
</div>
