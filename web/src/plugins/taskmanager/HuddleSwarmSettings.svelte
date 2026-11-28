
<script lang="ts">
    import { onMount } from 'svelte';
    import SwarmSettingsForm from './swarm/SwarmSettingsForm.svelte';
    import { loadSwarmSettings } from './swarm/swarm-settings.svelte';

    onMount(() => void loadSwarmSettings());
</script>

<div data-huddle-swarm-settings>
    <SwarmSettingsForm />
</div>
