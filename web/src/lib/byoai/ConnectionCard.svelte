
<script lang="ts">
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import Button from '../base/Button.svelte';
    import ListRow from '../base/ListRow.svelte';
    import State from '../base/State.svelte';
    import Switch from '../base/Switch.svelte';
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
    const keyed = $derived(usesKey(preset, connection.options));
    const host = $derived(preset.kind === 'cli' ? t('settings.ai.cli_host') : hostOf(connection.base_url) || connection.base_url);
</script>

{#snippet extra()}
    {#if keyed}
        <span data-ai="key-state">{connection.has_key ? t('settings.ai.key_set', { hint: connection.key_hint }) : t('settings.ai.key_none')}</span>
    {/if}
    {#if confirming}
        <State kind="warn" role="alert" title={t('settings.ai.card.delete_warning', { label: connection.label || preset.label })} data-ai="delete-warning">
            {#snippet actions()}
                <Button data-ai="delete-cancel" onclick={() => (confirming = false)}>{t('settings.ai.form.cancel')}</Button>
                <Button variant="danger" disabled={busy} data-ai="delete-confirm" onclick={() => { confirming = false; onDelete(); }}>{t('settings.ai.card.delete_confirm')}</Button>
            {/snippet}
        </State>
    {/if}
    {#if testing}
        <ConnectionTest {t} {connection} {preset} {busy} {onModels} />
    {/if}
{/snippet}

<ListRow wrap data-ai-connection={connection.id} data-off={connection.enabled ? undefined : ''} below={keyed || confirming || testing ? extra : undefined}>
    {#snippet lead()}<ProviderMark preset={preset.id} size={18} />{/snippet}
    {#snippet primary()}<span data-ai="name">{connection.label || preset.label}</span>{/snippet}
    {#snippet secondary()}<span data-ai="preset-name">{preset.label}</span> <span data-ai="host">{host}</span>{/snippet}
    {#snippet actions()}
        <Switch bare label={t('settings.ai.form.enabled')} bind:checked={() => connection.enabled, onToggle} disabled={busy} data-ai="toggle" />
        <Button size="sm" disabled={busy} aria-expanded={testing} data-ai="test-toggle" onclick={() => (testing = !testing)}>{t('settings.ai.card.test')}</Button>
        <Button size="sm" disabled={busy} data-ai="edit" onclick={onEdit}>{t('settings.ai.card.edit')}</Button>
        <Button size="sm" variant="danger" disabled={busy} data-ai="delete" onclick={() => (confirming = true)}>{t('settings.ai.card.delete')}</Button>
    {/snippet}
</ListRow>
