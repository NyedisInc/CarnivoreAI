
<script lang="ts">
    import SettingsForm from '../item-settings/SettingsForm.svelte';
    import type { SettingValue } from '../item-settings/api';
    import type { Translate } from '../sessions/types';
    import { setCplugSetting, type CplugItem, type SettingsWarning } from './cplugs-adapter';
    import { formIsShown, settingsExtraOf, visibleSchema } from './plugin-extras';
    import { hasPluginSettings } from './plugin-settings-link';
    import CplugSurface from '../cplug-ui/CplugSurface.svelte';

    interface Props {
        plugin: CplugItem;
        t: Translate;
        write?: (cplugId: string, key: string, value: SettingValue) => Promise<CplugItem>;
        onSaved?: (row: CplugItem) => void;
    }

    // svelte-ignore state_referenced_locally
    const { plugin, t, write = (id, key, value) => setCplugSetting(id, key, value, t), onSaved }: Props = $props();

    // svelte-ignore state_referenced_locally
    let settings = $state<Record<string, SettingValue>>({ ...plugin.settings });
    let busyKey = $state<string | null>(null);
    let error = $state<{ key: string; text: string } | null>(null);
    let advice = $state<readonly SettingsWarning[]>([]);
    const schema = $derived(plugin.settingsSchema);
    const shown = $derived(schema ? visibleSchema(plugin.cplugId, schema) : null);
    const Extra = $derived(settingsExtraOf(plugin.cplugId));

    const chosen = $derived(
        Object.fromEntries(Object.entries(settings).filter(([key, value]) => schema?.fields[key] && schema.fields[key]!.default !== value)),
    );

    async function change(key: string, value: SettingValue | null): Promise<void> {
        const field = schema?.fields[key];
        if (!field || busyKey) return;
        busyKey = key;
        error = null;
        advice = [];
        try {
            const row = await write(plugin.cplugId, key, value ?? (field.default as SettingValue));
            settings = { ...row.settings };
            advice = row.settingsWarnings ?? [];
            onSaved?.(row);
        } catch {
            error = { key, text: t('plugins.page.settings.failed') };
        } finally {
            busyKey = null;
        }
    }
</script>

{#if plugin.thirdParty && plugin.state === 'active'}
    
    <div class="plp-region" data-plugin-settings id={`plugin-settings-${plugin.cplugId}`}>
        <CplugSurface {plugin} surface="settings" {t} />
    </div>
{:else if hasPluginSettings(plugin) && (shown || Extra)}
    <div class="plp-region" data-plugin-settings id={`plugin-settings-${plugin.cplugId}`}>
        {#if shown && formIsShown(shown, Boolean(Extra))}<SettingsForm schema={shown} values={chosen} {t} onChange={(key, value) => void change(key, value)} {busyKey} {error} warnings={advice} idPrefix={`plugin-${plugin.cplugId}`} />{/if}
        {#if Extra}<Extra />{/if}
    </div>
{:else}
    <div class="plp-region">
        <p class="plp-note" data-plugin-settings-none>{t('plugins.page.pane.settings_none', { name: plugin.name })}</p>
    </div>
{/if}
