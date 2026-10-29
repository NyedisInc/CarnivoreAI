
<script lang="ts">
    import { onMount } from 'svelte';
    import { t } from '../i18n/index.svelte';
    import ViewFrame from './ViewFrame.svelte';
    import { overlays, startOverlays } from './overlay-views.svelte';

    onMount(startOverlays);
</script>

{#each overlays.list as entry (entry.key)}
    <ViewFrame plugin={entry.plugin} view={entry.view} surface="overlay" {t} />
{/each}
