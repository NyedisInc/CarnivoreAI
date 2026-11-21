
<script lang="ts">
    import { onMount } from 'svelte';
    import SwarmSettingsForm from '../../plugins/huddle/swarm/SwarmSettingsForm.svelte';
    import { loadSwarmSettings } from '../../plugins/huddle/swarm/swarm-settings.svelte';

    onMount(() => void loadSwarmSettings());
</script>

<div data-huddle-swarm-settings>
    <SwarmSettingsForm />
</div>
