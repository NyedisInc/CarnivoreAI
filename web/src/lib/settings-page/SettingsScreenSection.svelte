
<script lang="ts">
    import { provideInset } from '../../opscenter/ui/page-inset';
    import LaunchProfilesScreen from '../launch-profiles-page/LaunchProfilesScreen.svelte';
    import InfoScreen from '../info-pages/InfoScreen.svelte';
    import DesktopPanel from './DesktopPanel.svelte';
    import type { ScreenKind } from './settings-registry';

    interface Props {
        kind: ScreenKind;
        tab?: string | null;
        panel?: Record<string, string | number>;
    }

    const { kind, panel = {} }: Props = $props();

    provideInset();
</script>

<div class="st-screen" data-screen={kind} {...panel}>
    {#if kind === 'launch-profiles'}
        <LaunchProfilesScreen embedded />
    {:else if kind === 'keys'}
        <InfoScreen view="keys" embedded />
    {:else if kind === 'desktop'}
        <div class="oc-page__main st-main"><DesktopPanel /></div>
    {/if}
</div>
