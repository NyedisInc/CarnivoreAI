<script lang="ts">
    import type { ProjectPanelProps } from '../../cplugs/sdk/project-panels';
    const { projectKey }: ProjectPanelProps = $props();
</script>

<div data-fake-panel={projectKey}></div>
