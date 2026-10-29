
<script lang="ts">
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import Check from '../../opscenter/ui/Check.svelte';
    import '../settings-page/panel-kit/panel-kit.css';
    import './byoai.css';
    import type { Connection, ModelOverride, Preset } from './api';
    import { hostOf, usesKey } from './form-logic';
    import ConnectionTest from './ConnectionTest.svelte';
    import ProviderMark from './ProviderMark.svelte';

    interface Props {
        t?: Translate;
        connection: Connection;
        preset: Preset;
        busy?: boolean;
        onToggle: (enabled: boolean) => void;
        onEdit: () => void;
        onDelete: () => void;
        onModels: (models: Record<string, ModelOverride>) => void;
    }
    const { t = reactiveT, connection, preset, busy = false, onToggle, onEdit, onDelete, onModels }: Props = $props();

    let confirming = $state(false);
    let testing = $state(false);
    const host = $derived(preset.kind === 'cli' ? t('settings.ai.cli_host') : hostOf(connection.base_url) || connection.base_url);
</script>

<div class="tm__srv" class:tm__srv--off={!connection.enabled} data-ai-connection={connection.id}>
    <div class="tm__srv-head">
        <ProviderMark preset={preset.id} size={18} />
        <span class="tm__srv-name" data-ai="name">{connection.label || preset.label}</span>
        <span class="tm__sub" data-ai="preset-name">{preset.label}</span>
        <span class="tm__sub" data-ai="host">{host}</span>
        <Check role="switch" label={t('settings.ai.form.enabled')} checked={connection.enabled} disabled={busy} data-ai="toggle" onToggle={onToggle} />
        <span class="tm__srv-tools">
            <button type="button" class="oc-btn" disabled={busy} aria-expanded={testing} data-ai="test-toggle" onclick={() => (testing = !testing)}>{t('settings.ai.card.test')}</button>
            <button type="button" class="oc-btn" disabled={busy} data-ai="edit" onclick={onEdit}>{t('settings.ai.card.edit')}</button>
            <button type="button" class="oc-btn oc-btn--danger" disabled={busy} data-ai="delete" onclick={() => (confirming = true)}>{t('settings.ai.card.delete')}</button>
        </span>
    </div>
    {#if usesKey(preset, connection.options)}
        <p class="tm__sub" data-ai="key-state">{connection.has_key ? t('settings.ai.key_set', { hint: connection.key_hint }) : t('settings.ai.key_none')}</p>
    {/if}
    {#if confirming}
        <div class="tm__warn" role="alert" data-ai="delete-warning">
            <p>{t('settings.ai.card.delete_warning', { label: connection.label || preset.label })}</p>
            <div class="tm__actions">
                <button type="button" class="modal-btn modal-btn-secondary" data-ai="delete-cancel" onclick={() => (confirming = false)}>{t('settings.ai.form.cancel')}</button>
                <button type="button" class="modal-btn modal-btn-danger" disabled={busy} data-ai="delete-confirm" onclick={() => { confirming = false; onDelete(); }}>{t('settings.ai.card.delete_confirm')}</button>
            </div>
        </div>
    {/if}
    {#if testing}
        <ConnectionTest {t} {connection} {preset} {busy} {onModels} />
    {/if}
</div>
