
<script lang="ts">
    import { onMount } from 'svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import '../settings-page/panel-kit/panel-kit.css';
    import './byoai.css';
    import { errorText } from '../settings-page/panel-kit/error-text';
    import { clearKey, createConnection, deleteConnection, isStale, patchConnection, type Fetcher, type ModelOverride } from './api';
    import { createFor, patchFor, type Draft } from './form-logic';
    import { ai, attach, presetOf, refresh } from './store.svelte';
    import ConnectionCard from './ConnectionCard.svelte';
    import ConnectionForm from './ConnectionForm.svelte';

    interface Props {
        t?: Translate;
        fetcher?: Fetcher;
    }
    const { t = reactiveT, fetcher }: Props = $props();

    let editing = $state<string | null>(null);
    let busy = $state(false);
    let problem = $state('');
    let note = $state('');

    onMount(() => attach(fetcher));

    const revision = (): number => ai.config?.revision ?? 0;

    async function act(work: () => Promise<void>): Promise<boolean> {
        busy = true;
        problem = '';
        note = '';
        try {
            await work();
            return true;
        } catch (error) {
            if (isStale(error)) {
                editing = null;
                problem = t('settings.ai.stale');
            } else {
                problem = errorText(error);
            }
            return false;
        } finally {
            busy = false;
            await refresh();
        }
    }

    async function save(draft: Draft): Promise<void> {
        const preset = presetOf(draft.preset);
        if (!preset) return;
        const saved = ai.config?.connections.find((c) => c.id === editing);
        const done = await act(async () => {
            if (!saved) {
                await createConnection(createFor(preset, draft, revision()), fetcher);
                return;
            }
            const body = patchFor(preset, saved, draft, revision());
            let next = revision();
            if (Object.keys(body).length > 1) next = (await patchConnection(saved.id, body, fetcher)).revision;
            if (draft.clearKey && !draft.key.trim() && saved.has_key) await clearKey(saved.id, next, fetcher);
        });
        if (done) {
            editing = null;
            note = t('settings.ai.saved');
        }
    }

    const toggle = (id: string, enabled: boolean): Promise<boolean> =>
        act(async () => void (await patchConnection(id, { enabled, expected_revision: revision() }, fetcher)));
    const remove = (id: string): Promise<boolean> => act(async () => void (await deleteConnection(id, revision(), fetcher)));
    const saveModels = (id: string, models: Record<string, ModelOverride>): Promise<boolean> =>
        act(async () => void (await patchConnection(id, { models, expected_revision: revision() }, fetcher)));
</script>

<div class="tm" data-ai="connections">
    <p class="tm__sub">{t('settings.ai.connections.intro')}</p>
    {#if ai.config}
        {#each ai.config.connections as connection (connection.id)}
            {@const preset = presetOf(connection.preset)}
            {#if editing === connection.id && preset}
                <ConnectionForm {t} presets={ai.presets} {connection} accounts={ai.accounts} {busy} onSave={(d) => void save(d)} onCancel={() => (editing = null)} />
            {:else if preset}
                <ConnectionCard {t} {connection} {preset} {busy} onToggle={(on) => void toggle(connection.id, on)} onEdit={() => (editing = connection.id)}
                    onDelete={() => void remove(connection.id)} onModels={(models) => void saveModels(connection.id, models)} />
            {/if}
        {/each}
        {#if ai.config.connections.length === 0}<p class="tm__sub" data-ai="none">{t('settings.ai.connections.none')}</p>{/if}
        {#if editing === 'new' && ai.presets.length > 0}
            <ConnectionForm {t} presets={ai.presets} connection={null} accounts={ai.accounts} {busy} onSave={(d) => void save(d)} onCancel={() => (editing = null)} />
        {:else}
            <div class="tm__actions">
                <button type="button" class="oc-btn oc-btn--confirm" disabled={busy || editing !== null} data-ai="add" onclick={() => (editing = 'new')}>{t('settings.ai.connections.add')}</button>
            </div>
        {/if}
    {:else if !ai.problem}
        <p class="tm__sub">{t('settings.ai.loading')}</p>
    {/if}
    {#if note}<p class="tm__note" role="status" data-ai="note">{note}</p>{/if}
    {#if problem || ai.problem}<p class="tm__problem" role="alert" data-ai="problem">{problem || ai.problem}</p>{/if}
</div>
