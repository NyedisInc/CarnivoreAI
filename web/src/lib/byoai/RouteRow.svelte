
<script lang="ts">
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import '../settings-page/panel-kit/panel-kit.css';
    import './byoai.css';
    import type { Connection, TargetRef } from './api';
    import { capabilityIcon } from './capability-icons';
    import { offeredCapabilities, voicesOf } from './form-logic';
    import ModelPicker from './ModelPicker.svelte';
    import { defaultModelId, modelFacts, modelItems, type PickItem } from './picker-logic';
    import { ai, loadModels, presetOf } from './store.svelte';
    import { followSettingsLink } from '../settings-page/settings-navigate';

    interface Props {
        t?: Translate;
        name: string;
        href?: string | null;
        capability: string;
        target: TargetRef | null;
        busy?: boolean;
        onSet: (target: TargetRef) => void;
        onClear: () => void;
        unsetLabel?: string;
        modelPlaceholder?: string;
    }
    const { t = reactiveT, name, href = null, capability, target, busy = false, onSet, onClear, unsetLabel = '', modelPlaceholder = '' }: Props = $props();

    function follow(event: MouseEvent): void {
        if (href && followSettingsLink(href)) event.preventDefault();
    }

    // svelte-ignore state_referenced_locally
    let connectionId = $state(target?.connection ?? '');
    // svelte-ignore state_referenced_locally
    let model = $state(target?.model ?? '');
    // svelte-ignore state_referenced_locally
    let voice = $state(target?.voice ?? '');

    const serving = $derived<Connection[]>(
        (ai.config?.connections ?? []).filter((c) => {
            const preset = presetOf(c.preset);
            return c.enabled && !!preset && offeredCapabilities(preset, c).includes(capability);
        }),
    );
    const listed = $derived(connectionId ? ai.models[connectionId] : undefined);
    const models = $derived(listed && listed !== 'error' ? listed : []);
    const modelRows = $derived(modelItems(models, capability, ai.recent[connectionId] ?? [], (m) => modelFacts(m, t)));
    const connectionRows = $derived<PickItem[]>([
        ...serving.map((c) => ({ id: c.id, text: c.label || c.id, name: '', vendor: '', detail: presetOf(c.preset)?.label ?? c.preset, flags: [], preset: c.preset })),
        ...(connectionId && !serving.some((c) => c.id === connectionId) ? [{ id: connectionId, text: connectionId, name: '', vendor: '', detail: '', flags: [] }] : []),
    ]);
    const voiceRows = $derived<PickItem[]>(voicesOf(models.find((m) => m.id === model)).map((v) => ({ id: v, text: v, name: '', vendor: '', detail: '', flags: [] })));
    const voices = $derived(voicesOf(models.find((m) => m.id === model)));
    const dirty = $derived(connectionId !== (target?.connection ?? '') || model !== (target?.model ?? '') || voice !== (target?.voice ?? ''));

    $effect(() => {
        if (connectionId && !ai.models[connectionId]) void loadModels(connectionId);
    });

    function pickConnection(id: string): void {
        connectionId = id;
        model = '';
        voice = '';
    }

    $effect(() => {
        if (connectionId && model === '' && modelRows.length > 0) model = defaultModelId(modelRows);
    });
</script>

<div class="ai-route" data-ai-route={capability} data-ai-route-name={name}>
    <p class="ai-route__name"><span class="ai-route__icon" data-ai-capability-icon={capability}><Icon name={capabilityIcon(capability)} size={16} /></span>{#if href}<a class="ai-route__link" {href} data-ai="route-owner-link" onclick={follow}>{name}</a>{:else}{name}{/if}</p>
    <div class="tm__field">
        <span class="oc-key">{t('settings.ai.route.connection')}</span>
        <ModelPicker {t} items={connectionRows} value={connectionId} onChange={pickConnection} label={t('settings.ai.route.connection')} grouped={false}
            emptyLabel={unsetLabel || t('settings.ai.route.unset')} disabled={busy} dataAi="route-connection" />
    </div>
    <div class="tm__field">
        <span class="oc-key">{t('settings.ai.route.model')}</span>
        <ModelPicker {t} items={modelRows} value={model} onChange={(id) => (model = id)} label={t('settings.ai.route.model')} allowCustom placeholder={modelPlaceholder}
            loading={!!connectionId && !listed} disabled={busy || !connectionId} dataAi="route-model" />
    </div>
    {#if capability === 'speak'}
        <div class="tm__field">
            <span class="oc-key">{t('settings.ai.route.voice')}</span>
            <ModelPicker {t} items={voiceRows} value={voice} onChange={(id) => (voice = id)} label={t('settings.ai.route.voice')} grouped={false} allowCustom
                disabled={busy || !connectionId} dataAi="route-voice" />
        </div>
    {:else}
        <span aria-hidden="true"></span>
    {/if}
    <div class="ai-route__tools">
        <button type="button" class="oc-btn oc-btn--confirm" disabled={busy || !connectionId || !dirty} data-ai="route-set"
            onclick={() => onSet({ connection: connectionId, model: model.trim() || null, voice: voice.trim() || null })}>{t('settings.ai.route.set')}</button>
        <button type="button" class="oc-btn" disabled={busy || !target} data-ai="route-clear" onclick={onClear}>{t('settings.ai.route.clear')}</button>
    </div>
</div>
