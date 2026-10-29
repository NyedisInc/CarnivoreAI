
<script lang="ts">
    import { provideInset } from '../../opscenter/ui/page-inset';
    import PackWorkTab from '../pack-machines/PackWorkTab.svelte';
    import PackLoginsTab from '../pack-machines/PackLoginsTab.svelte';
    import PackSkillsTab from '../skills-hub/pack/PackSkillsTab.svelte';
    import PackRoster from '../pack-roster/PackRoster.svelte';
    import type { PackTab } from './pack-hash';

    interface Props {
        tab: PackTab;
        panel?: Record<string, string | number>;
    }

    const { tab, panel = {} }: Props = $props();

    provideInset();
</script>

<div class="pk-screen" data-screen="hosts" {...panel}>
    {#if tab === 'work'}
        <PackWorkTab />
    {:else if tab === 'logins'}
        <PackLoginsTab />
    {:else if tab === 'skills'}
        <PackSkillsTab />
    {:else}
        <PackRoster />
    {/if}
</div>
