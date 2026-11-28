<script lang="ts">
  import { t } from '../sdk';
  import { huddle } from './huddle.svelte';
  import type { HuddleItem } from './huddle-model';

  let { item }: { item: HuddleItem } = $props();

  const source = $derived(item.from_project ?? null);
  const name = $derived.by(() => {
    if (!source) return '';
    const live = huddle.lists.find((l) => l.project_id !== null && String(l.project_id) === source.id)?.name;
    return live || source.name || source.id;
  });
</script>

{#if source}
  <p class="tkm-from" data-task-manager-from-project={item.id}>{t('cplug.huddle.from_project.from', { project: name })}</p>
{/if}

<style>
  @layer components {
    .tkm-from {
      min-width: 0;
      margin: 0;
      overflow: hidden;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.06em;
      text-overflow: ellipsis;
      text-transform: uppercase;
      white-space: nowrap;
    }
  }
</style>
