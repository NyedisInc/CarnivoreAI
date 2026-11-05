
<script lang="ts">
    import { provideInset } from '../../opscenter/ui/page-inset';
    import LaunchProfilesScreen from '../launch-profiles-page/LaunchProfilesScreen.svelte';
    import InfoScreen from '../info-pages/InfoScreen.svelte';
    import DesktopPanel from './DesktopPanel.svelte';
    import PluginsScreen from '../plugins-page/PluginsScreen.svelte';
    import { settingsDoc } from './settings-doc.svelte';
    import type { FeatureLink } from './settings-hash';
    import type { ScreenKind } from './settings-registry';

    interface Props {
        kind: ScreenKind;
        tab?: string | null;
        panel?: Record<string, string | number>;
        focus?: FeatureLink | null;
        onSelectFeature?: (id: string, tab: string) => void;
    }

    const { kind, panel = {}, focus = null, onSelectFeature }: Props = $props();
    const developerMode = $derived(settingsDoc.summary?.server_prefs?.developer_mode === true);

    provideInset();
</script>

<div class="st-screen" data-screen={kind} {...panel}>
    {#if kind === 'launch-profiles'}
        <LaunchProfilesScreen embedded />
    {:else if kind === 'keys'}
        <InfoScreen view="keys" embedded />
    {:else if kind === 'features'}
        
        <PluginsScreen embedded scope="features" {developerMode} focusId={focus?.id ?? null} focusTab={focus?.settings ? 'settings' : null} onSelect={onSelectFeature} />
    {:else if kind === 'desktop'}
        <div class="oc-page__main st-main"><DesktopPanel /></div>
    {/if}
</div>
