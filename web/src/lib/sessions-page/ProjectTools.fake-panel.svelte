<script lang="ts">
    import type { ProjectPanelProps } from '../../plugins/sdk/project-panels';
    const { projectKey }: ProjectPanelProps = $props();
</script>

<div data-fake-panel={projectKey}></div>
