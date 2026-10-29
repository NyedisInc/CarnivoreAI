
<script lang="ts">
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import Check from '../../opscenter/ui/Check.svelte';
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

<form class="tm__srv" data-ai="form" onsubmit={(e) => { e.preventDefault(); if (!missing && !busy) onSave(draft); }}>
    <div class="tm__srv-grid">
        <div class="tm__field">
            <span class="oc-key">{t('settings.ai.form.preset')}</span>
            {#if editing}
                <span class="tm__figs" data-ai="preset-fixed">{preset.label}</span>
            {:else}
                <ModelPicker {t} items={presetRows} value={draft.preset} onChange={pickPreset} label={t('settings.ai.form.preset')} grouped alpha={false}
                    disabled={busy} dataAi="preset" />
            {/if}
        </div>
        <label class="tm__field">
            <span class="oc-key">{t('settings.ai.form.label')}</span>
            <input class="oc-field" type="text" bind:value={draft.label} disabled={busy} spellcheck="false" autocomplete="off" data-ai="label" />
        </label>
        {#if showUrl}
            <label class="tm__field">
                <span class="oc-key">{t('settings.ai.form.base_url')}</span>
                <input class="oc-field" type="text" bind:value={draft.baseUrl} disabled={busy} spellcheck="false" autocomplete="off"
                    placeholder={t('settings.ai.form.base_url_placeholder')} data-ai="base-url" oninput={() => (urlTouched = true)} />
            </label>
        {/if}
        {#each preset.fields as field (field.name)}
            {#if field.name === 'capabilities'}
                <div class="tm__field" data-ai="capabilities">
                    <span class="oc-key">{t('settings.ai.form.capabilities')}</span>
                    <div class="ai-ticks">
                        {#each Object.keys(preset.capabilities) as capability (capability)}
                            <Check label={t(`settings.ai.capability.${capability}`)} checked={Array.isArray(draft.options['capabilities']) && (draft.options['capabilities'] as string[]).includes(capability)}
                                disabled={busy} data-ai="capability" onToggle={(next) => tick(capability, next)} />
                        {/each}
                    </div>
                </div>
            {:else if field.name === 'auth_header' && !customHeader}
                
            {:else if field.name === 'account'}
                <label class="tm__field">
                    <span class="oc-key">{t('settings.ai.form.account')}</span>
                    <select class="oc-field" value={String(draft.options['account'] ?? '')} disabled={busy} data-ai="account"
                        onchange={(e) => setOption('account', e.currentTarget.value)}>
                        <option value="">{t('settings.ai.form.account_default')}</option>
                        {#each accountsHere as account (account.id)}<option value={account.id}>{account.name}</option>{/each}
                    </select>
                </label>
            {:else if field.kind === 'bool'}
                <div class="tm__field">
                    <Check role="switch" label={t(`settings.ai.field.${field.name}`)} checked={draft.options[field.name] === true} disabled={busy}
                        data-ai={`field-${field.name}`} onToggle={(next) => setOption(field.name, next)} />
                </div>
            {:else if field.kind === 'choice'}
                <label class="tm__field">
                    <span class="oc-key">{t(`settings.ai.field.${field.name}`)}</span>
                    <select class="oc-field" value={String(draft.options[field.name] ?? '')} disabled={busy} data-ai={`field-${field.name}`}
                        onchange={(e) => setOption(field.name, e.currentTarget.value)}>
                        <option value="">{t('settings.ai.form.default_choice')}</option>
                        {#each field.choices as choice (choice)}<option value={choice}>{choiceLabel(field.name, choice)}</option>{/each}
                    </select>
                </label>
            {:else}
                <label class="tm__field">
                    <span class="oc-key">{t(`settings.ai.field.${field.name}`)}</span>
                    <input class="oc-field" type="text" value={String(draft.options[field.name] ?? '')} disabled={busy} spellcheck="false" autocomplete="off"
                        data-ai={`field-${field.name}`} oninput={(e) => setOption(field.name, e.currentTarget.value)} />
                </label>
            {/if}
        {/each}
        {#if showExtra}
            <label class="tm__field ai-extra">
                <span class="oc-key">{t('settings.ai.form.extra_body')}</span>
                <textarea class="oc-field" rows="3" value={extraText} disabled={busy} spellcheck="false" autocomplete="off"
                    placeholder={t('settings.ai.form.extra_body_placeholder')} aria-invalid={extraProblem !== null} data-ai="extra-body"
                    oninput={(e) => setOption(EXTRA_BODY_OPTION, e.currentTarget.value)}></textarea>
                {#if extraProblem}
                    <span class="tm__sub tm__problem" role="alert" data-ai="extra-body-problem">{t(extraProblem)}</span>
                {:else}
                    <span class="tm__sub">{t('settings.ai.form.extra_body_hint')}</span>
                {/if}
            </label>
        {/if}
        {#if showKey}
            <label class="tm__field">
                <span class="oc-key">{t(editing && connection?.has_key ? 'settings.ai.form.key_replace' : 'settings.ai.form.key')}{preset.key_required ? '' : ` (${t('settings.ai.form.optional')})`}</span>
                <input class="oc-field" use:secretField bind:value={draft.key} disabled={busy}
                    placeholder={t(editing && connection?.has_key ? 'settings.ai.form.key_keep' : 'settings.ai.form.key_placeholder')} data-ai="key" />
            </label>
        {/if}
    </div>
    {#if showKey && editing}
        <p class="tm__sub" data-ai="key-state">
            {connection?.has_key ? t('settings.ai.key_set', { hint: connection.key_hint }) : t('settings.ai.key_none')}
        </p>
        {#if connection?.has_key}
            <Check label={t('settings.ai.form.key_clear')} checked={draft.clearKey} disabled={busy} data-ai="clear-key"
                onToggle={(next) => (draft.clearKey = next)} />
        {/if}
    {/if}
    <Check role="switch" label={t('settings.ai.form.enabled')} checked={draft.enabled} disabled={busy} data-ai="enabled" onToggle={(next) => (draft.enabled = next)} />
    {#if warnDrop}
        <div class="tm__warn" role="alert" data-ai="host-warning">
            <p>{t('settings.ai.form.host_warning', { host: connection?.key_host ?? '' })}</p>
        </div>
    {/if}
    <div class="tm__actions">
        <button type="button" class="modal-btn modal-btn-secondary" disabled={busy} data-ai="cancel" onclick={onCancel}>{t('settings.ai.form.cancel')}</button>
        <button type="submit" class="modal-btn modal-btn-confirm" disabled={busy || missing} data-ai="save">{t(editing ? 'settings.ai.form.save' : 'settings.ai.form.add')}</button>
    </div>
</form>
