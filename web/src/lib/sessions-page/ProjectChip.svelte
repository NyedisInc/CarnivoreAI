
<script lang="ts">
    import { projectColorOf } from '../project-colors/store.svelte';
    import { projectColorVar } from '../project-colors/palette';

    const { name, projectId = null }: { name: string; projectId?: number | null } = $props();
</script>

<span class="sp-pchip" style:--pc={projectColorVar(projectColorOf(projectId))}>{(name.charAt(0) || '?').toUpperCase()}</span>
