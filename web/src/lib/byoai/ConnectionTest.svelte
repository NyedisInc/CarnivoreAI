
<script lang="ts">
    import { onMount } from 'svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import '../settings-page/panel-kit/panel-kit.css';
    import './byoai.css';
    import { errorText } from '../settings-page/panel-kit/error-text';
    import { generateMedia, testConnection, type Connection, type MediaItem, type ModelOverride, type Preset, type TestResult } from './api';
    import { playBase64 } from './audio';
    import { base64Bytes, offeredCapabilities } from './form-logic';
    import ModelPicker from './ModelPicker.svelte';
    import { defaultModelId, modelFacts, modelItems } from './picker-logic';
    import { ai, loadModels } from './store.svelte';

    interface Props {
        t?: Translate;
        connection: Connection;
        preset: Preset;
        busy?: boolean;
        onModels: (models: Record<string, ModelOverride>) => void;
    }
    const { t = reactiveT, connection, preset, busy = false, onModels }: Props = $props();

    const MEDIA = ['image', 'video', 'audio'];
    const capabilities = $derived(offeredCapabilities(preset, connection));
    let capability = $state('');
    let model = $state('');
    let typed = $state('');
    let prompt = $state('');
    let running = $state(false);
    let result = $state<TestResult | null>(null);
    let items = $state<MediaItem[] | null>(null);
    let problem = $state('');
    let playing = $state(false);

    const listed = $derived(ai.models[connection.id]);
    const models = $derived(listed && listed !== 'error' ? listed : []);
    const choices = $derived(modelItems(models, capability, ai.recent[connection.id] ?? [], (m) => modelFacts(m, t)));
    let customModel = $state(false);
    const isMedia = $derived(MEDIA.includes(capability));

    onMount(() => {
        capability = capabilities.includes('chat') ? 'chat' : (capabilities[0] ?? '');
    });

    $effect(() => {
        if (!ai.models[connection.id]) void loadModels(connection.id);
    });

    $effect(() => {
        if (choices.length > 0 && !customModel && !choices.some((m) => m.id === model)) model = defaultModelId(choices);
    });

    function pickModel(id: string): void {
        model = id;
        customModel = !choices.some((m) => m.id === id);
    }

    async function runTest(): Promise<void> {
        running = true;
        problem = '';
        result = null;
        items = null;
        try {
            result = await testConnection(connection.id, capability, model.trim() || null);
        } catch (error) {
            problem = errorText(error);
        } finally {
            running = false;
        }
    }

    async function play(): Promise<void> {
        if (!result?.audio) return;
        playing = true;
        problem = '';
        try {
            await playBase64(result.audio);
        } catch (error) {
            problem = error instanceof Error ? error.message : String(error);
        } finally {
            playing = false;
        }
    }

    async function generate(): Promise<void> {
        running = true;
        problem = '';
        result = null;
        try {
            items = (await generateMedia(connection.id, model.trim() || null, capability, prompt.trim())).items ?? [];
        } catch (error) {
            problem = errorText(error);
        } finally {
            running = false;
        }
    }

    const refreshModels = (): Promise<unknown> => loadModels(connection.id, true);

    function addTyped(): void {
        const id = typed.trim();
        if (!id) return;
        onModels({ ...connection.models, [id]: { capabilities: [], flags: [], enabled: true } });
        typed = '';
    }

    const safeUrl = (url: string): boolean => /^https?:\/\//i.test(url);
</script>

<div class="ai-test" data-ai="test-panel">
    <div class="tm__srv-grid">
        <label class="tm__field">
            <span class="oc-key">{t('settings.ai.test.capability')}</span>
            <select class="oc-field" bind:value={capability} disabled={busy || running} data-ai="test-capability" onchange={() => (customModel = false)}>
                {#each capabilities as cap (cap)}<option value={cap}>{t(`settings.ai.capability.${cap}`)}</option>{/each}
            </select>
        </label>
        <div class="tm__field">
            <span class="oc-key">{t('settings.ai.test.model')}</span>
            <ModelPicker {t} items={choices} value={model} onChange={pickModel} label={t('settings.ai.test.model')} allowCustom loading={!listed}
                disabled={busy || running} dataAi="test-model" />
        </div>
    </div>
    <div class="tm__actions">
        <button type="button" class="oc-btn oc-btn--confirm" disabled={busy || running || !capability} data-ai="test-run" onclick={() => void runTest()}>
            {running ? t('settings.ai.test.running') : t('settings.ai.test.run')}
        </button>
    </div>
    {#if result}
        <p class="tm__srv-result" class:tm__srv-result--ok={result.ok} class:tm__srv-result--bad={!result.ok} role="status" data-ai="test-result" data-ok={result.ok}>
            {result.ok ? t('settings.ai.test.ok') : t('settings.ai.test.failed')}{result.latency_ms !== null ? `, ${t('settings.ai.test.latency', { ms: result.latency_ms })}` : ''}{result.model ? `, ${result.model}` : ''}{result.detail ? `: ${result.detail}` : ''}
        </p>
        {#if result.audio}
            <div class="tm__actions">
                <button type="button" class="oc-btn" disabled={playing} data-ai="test-play" onclick={() => void play()}>{t('settings.ai.test.play')}</button>
            </div>
        {/if}
    {/if}
    {#if isMedia}
        <div class="tm__field">
            <span class="oc-key">{t('settings.ai.test.prompt')}</span>
            <input class="oc-field" type="text" bind:value={prompt} disabled={busy || running} spellcheck="false" autocomplete="off" data-ai="try-prompt" />
        </div>
        <div class="tm__actions">
            <button type="button" class="oc-btn" disabled={busy || running || !prompt.trim()} data-ai="try-run" onclick={() => void generate()}>{t('settings.ai.test.generate')}</button>
        </div>
        {#if items}
            <ul class="ai-test__links" data-ai="try-items">
                {#each items as item, index (index)}
                    <li>
                        {#if item.url && safeUrl(item.url)}
                            <a href={item.url} target="_blank" rel="noopener noreferrer">{item.url}</a>
                        {:else if item.data}
                            {t('settings.ai.test.inline', { mime: item.mime || 'bytes', bytes: base64Bytes(item.data) })}
                        {:else}
                            {item.url}
                        {/if}
                    </li>
                {/each}
                {#if items.length === 0}<li class="tm__sub">{t('settings.ai.test.no_items')}</li>{/if}
            </ul>
        {/if}
    {/if}
    {#if problem}<p class="tm__problem" role="alert" data-ai="test-problem">{problem}</p>{/if}

    <div class="tm__field" data-ai="models">
        <span class="oc-key">{t('settings.ai.models.title')}</span>
        {#if listed === 'error'}
            <p class="tm__sub" data-ai="models-error">{t('settings.ai.models.error')}</p>
        {:else if models.length === 0}
            <p class="tm__sub">{t('settings.ai.models.none')}</p>
        {:else}
            <p class="tm__sub" data-ai="models-list">{models.slice(0, 6).map((m) => m.id).join(', ')}{models.length > 6 ? t('settings.ai.models.more', { n: models.length - 6 }) : ''}</p>
        {/if}
        <div class="tm__actions">
            <input class="oc-field" type="text" bind:value={typed} disabled={busy} spellcheck="false" autocomplete="off"
                placeholder={t('settings.ai.models.typed_placeholder')} data-ai="model-typed" />
            <button type="button" class="oc-btn" disabled={busy || !typed.trim()} data-ai="model-add" onclick={addTyped}>{t('settings.ai.models.add')}</button>
            <button type="button" class="oc-btn" disabled={busy} data-ai="models-refresh" onclick={() => void refreshModels()}>{t('settings.ai.models.refresh')}</button>
        </div>
    </div>
</div>
