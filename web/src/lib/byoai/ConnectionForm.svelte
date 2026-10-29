
<script lang="ts">
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import Button from '../base/Button.svelte';
    import Field from '../base/Field.svelte';
    import Select from '../base/Select.svelte';
    import State from '../base/State.svelte';
    import Switch from '../base/Switch.svelte';
    import '../settings-page/panel-kit/panel-kit.css';
    import './byoai.css';
    import type { Connection, LedgerAccount, Preset } from './api';
    import { secretField } from '../secret-field';
    import ModelPicker from './ModelPicker.svelte';
    import type { PickItem } from './picker-logic';
    import {
        defaultBaseUrl, dropsKey, EXTRA_BODY_OPTION, extraBodyProblem, initialDraft, ledgerProviderOf, speaksOpenAiChat, usesKey, type Draft,
    } from './form-logic';

    interface Props {
        t?: Translate;
        presets: readonly Preset[];
        connection: Connection | null;
        accounts?: readonly LedgerAccount[];
        busy?: boolean;
        onSave: (draft: Draft) => void;
        onCancel: () => void;
    }
    const { t = reactiveT, presets, connection, accounts = [], busy = false, onSave, onCancel }: Props = $props();

    const KINDS = ['local', 'cloud', 'cli'] as const;
    const presetRows = $derived<PickItem[]>(KINDS.flatMap((kind) => presets.filter((p) => p.kind === kind).map((p) => ({
        id: p.id, text: p.label, name: '', vendor: t(`settings.ai.kind.${kind}`), detail: '', flags: [], preset: p.id }))));
    const byId = (id: string): Preset => presets.find((p) => p.id === id) ?? presets[0]!;
    // svelte-ignore state_referenced_locally
    const start = byId(connection?.preset ?? presets.find((p) => p.kind === 'local')?.id ?? presets[0]!.id);

    // svelte-ignore state_referenced_locally
    let draft = $state<Draft>(initialDraft(start, connection));
    // svelte-ignore state_referenced_locally
    let urlTouched = connection !== null;

    const preset = $derived(byId(draft.preset));
    const editing = $derived(connection !== null);
    const showUrl = $derived(preset.kind !== 'cli');
    const showKey = $derived(usesKey(preset, draft.options));
    const warnDrop = $derived(dropsKey(connection, draft.baseUrl, draft.key));
    const customHeader = $derived(preset.custom && draft.options['auth'] === 'custom-header');
    const showExtra = $derived(speaksOpenAiChat(preset));
    const extraText = $derived(String(draft.options[EXTRA_BODY_OPTION] ?? ''));
    const extraProblem = $derived(showExtra ? extraBodyProblem(extraText) : null);
    const missing = $derived(
        !draft.label.trim() || (showUrl && !draft.baseUrl.trim()) || preset.fields.some((f) => f.required && !String(draft.options[f.name] ?? '').trim())
        || extraProblem !== null,
    );

    function pickPreset(id: string): void {
        draft = { ...initialDraft(byId(id), null), key: draft.key };
        urlTouched = false;
    }

    function setOption(name: string, value: unknown): void {
        draft.options = { ...draft.options, [name]: value };
        if (name === 'region' && !urlTouched) draft.baseUrl = defaultBaseUrl(preset, draft.options);
    }

    function tick(capability: string, on: boolean): void {
        const now = Array.isArray(draft.options['capabilities']) ? (draft.options['capabilities'] as string[]) : [];
        setOption('capabilities', on ? [...now, capability] : now.filter((c) => c !== capability));
    }

    const accountsHere = $derived(accounts.filter((a) => a.provider === ledgerProviderOf(preset)));
    const choiceLabel = (name: string, choice: string): string => (name === 'protocol' ? t(`settings.ai.protocol.${choice}`) : t(`settings.ai.auth.${choice}`));
</script>

<form class="tm__field" data-ai="form" onsubmit={(e) => { e.preventDefault(); if (!missing && !busy) onSave(draft); }}>
    <div class="tm__srv-grid">
        <div class="oc-form-field">
            <span class="oc-label">{t('settings.ai.form.preset')}</span>
            {#if editing}
                <span class="tm__figs" data-ai="preset-fixed">{preset.label}</span>
            {:else}
                <ModelPicker {t} items={presetRows} value={draft.preset} onChange={pickPreset} label={t('settings.ai.form.preset')} grouped alpha={false}
                    disabled={busy} dataAi="preset" />
            {/if}
        </div>
        <Field label={t('settings.ai.form.label')} bind:value={draft.label} disabled={busy} spellcheck="false" autocomplete="off" data-ai="label" />
        {#if showUrl}
            <Field label={t('settings.ai.form.base_url')} bind:value={draft.baseUrl} disabled={busy} spellcheck="false" autocomplete="off"
                placeholder={t('settings.ai.form.base_url_placeholder')} data-ai="base-url" oninput={() => (urlTouched = true)} />
        {/if}
        {#each preset.fields as field (field.name)}
            {#if field.name === 'capabilities'}
                <div class="tm__field" data-ai="capabilities">
                    <span class="oc-label">{t('settings.ai.form.capabilities')}</span>
                    <div class="ai-ticks">
                        {#each Object.keys(preset.capabilities) as capability (capability)}
                            <Switch role="checkbox" label={t(`settings.ai.capability.${capability}`)}
                                bind:checked={() => Array.isArray(draft.options['capabilities']) && (draft.options['capabilities'] as string[]).includes(capability), (next) => tick(capability, next)}
                                disabled={busy} data-ai="capability" />
                        {/each}
                    </div>
                </div>
            {:else if field.name === 'auth_header' && !customHeader}
                
            {:else if field.name === 'account'}
                <Select label={t('settings.ai.form.account')} value={String(draft.options['account'] ?? '')} disabled={busy} data-ai="account"
                    options={[{ value: '', label: t('settings.ai.form.account_default') }, ...accountsHere.map((a) => ({ value: a.id, label: a.name }))]}
                    onchange={(e) => setOption('account', e.currentTarget.value)} />
            {:else if field.kind === 'bool'}
                <div class="tm__field">
                    <Switch label={t(`settings.ai.field.${field.name}`)} bind:checked={() => draft.options[field.name] === true, (next) => setOption(field.name, next)} disabled={busy}
                        data-ai={`field-${field.name}`} />
                </div>
            {:else if field.kind === 'choice'}
                <Select label={t(`settings.ai.field.${field.name}`)} value={String(draft.options[field.name] ?? '')} disabled={busy} data-ai={`field-${field.name}`}
                    options={[{ value: '', label: t('settings.ai.form.default_choice') }, ...field.choices.map((choice) => ({ value: choice, label: choiceLabel(field.name, choice) }))]}
                    onchange={(e) => setOption(field.name, e.currentTarget.value)} />
            {:else}
                <Field label={t(`settings.ai.field.${field.name}`)} value={String(draft.options[field.name] ?? '')} disabled={busy} spellcheck="false" autocomplete="off"
                    data-ai={`field-${field.name}`} oninput={(e) => setOption(field.name, e.currentTarget.value)} />
            {/if}
        {/each}
        {#if showExtra}
            <div class="ai-extra">
                <Field multiline rows={3} label={t('settings.ai.form.extra_body')} value={extraText} disabled={busy} spellcheck="false" autocomplete="off"
                    placeholder={t('settings.ai.form.extra_body_placeholder')} data-ai="extra-body"
                    error={extraProblem ? t(extraProblem) : undefined} help={extraProblem ? undefined : t('settings.ai.form.extra_body_hint')}
                    oninput={(e) => setOption(EXTRA_BODY_OPTION, e.currentTarget.value)} />
            </div>
        {/if}
        {#if showKey}
            <Field label={`${t(editing && connection?.has_key ? 'settings.ai.form.key_replace' : 'settings.ai.form.key')}${preset.key_required ? '' : ` (${t('settings.ai.form.optional')})`}`}
                bind:value={draft.key} disabled={busy} {@attach (node) => secretField(node as HTMLInputElement)}
                placeholder={t(editing && connection?.has_key ? 'settings.ai.form.key_keep' : 'settings.ai.form.key_placeholder')} data-ai="key" />
        {/if}
    </div>
    {#if showKey && editing}
        <p class="tm__sub" data-ai="key-state">
            {connection?.has_key ? t('settings.ai.key_set', { hint: connection.key_hint }) : t('settings.ai.key_none')}
        </p>
        {#if connection?.has_key}
            <Switch role="checkbox" label={t('settings.ai.form.key_clear')} bind:checked={() => draft.clearKey, (next) => (draft.clearKey = next)} disabled={busy} data-ai="clear-key" />
        {/if}
    {/if}
    <Switch label={t('settings.ai.form.enabled')} bind:checked={() => draft.enabled, (next) => (draft.enabled = next)} disabled={busy} data-ai="enabled" />
    {#if warnDrop}
        <State kind="warn" role="alert" title={t('settings.ai.form.host_warning', { host: connection?.key_host ?? '' })} data-ai="host-warning" />
    {/if}
    <div class="tm__actions">
        <Button disabled={busy} data-ai="cancel" onclick={onCancel}>{t('settings.ai.form.cancel')}</Button>
        <Button type="submit" variant="confirm" disabled={busy || missing} data-ai="save">{t(editing ? 'settings.ai.form.save' : 'settings.ai.form.add')}</Button>
    </div>
</form>
