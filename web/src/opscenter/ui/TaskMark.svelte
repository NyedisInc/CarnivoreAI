
<script lang="ts">
  import Icon from './Icon.svelte';
  import { t } from '../../lib/i18n/index.svelte';

  let { rank = null, size = 11 }: { rank?: string | null; size?: number } = $props();
  const label = $derived(t('swarm.agent.task_mark'));
</script>

{#if rank === 'task'}<span class="oc-task-mark" role="img" aria-label={label} title={label} data-task-mark><Icon name="hourglass" {size} /></span>{/if}

<style>
  @layer components {
    .oc-task-mark {
      display: inline-flex;
      flex: none;
      align-items: center;
      margin-right: var(--oc-space-1);
      color: var(--oc-text-secondary);
      vertical-align: middle;
    }
  }
</style>
