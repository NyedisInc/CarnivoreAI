
<script lang="ts">
    import { uiPrefs } from './prefs.svelte';
    const both = $derived(`${uiPrefs.archivedSessionsVisible}/${uiPrefs.archivedProjectsVisible}`);
</script>

<p data-probe>{both}</p>
