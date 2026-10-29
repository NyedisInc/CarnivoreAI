<script lang="ts">
  import { t } from '../sdk';
  import type { HuddleItem } from './huddle-model';

  let { item }: { item: HuddleItem } = $props();

  const source = $derived(item.from_inbox ?? null);
</script>

{#if source}
  <div class="tkm-inbox-from" data-task-manager-from-inbox={item.id}>
    <p class="tkm-inbox-from-label">{t('cplug.huddle.inbox.from')}</p>
    <p class="tkm-inbox-from-text" data-task-manager-from-inbox-text={item.id}>{source.text}</p>
  </div>
{/if}

<style>
  @layer components {
    .tkm-inbox-from {
      min-width: 0;
      display: grid;
      gap: var(--oc-space-1);
    }
    .tkm-inbox-from-label {
      margin: 0;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }
    .tkm-inbox-from-text {
      margin: 0;
      overflow-wrap: anywhere;
      color: var(--oc-text-muted);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-micro);
      white-space: pre-wrap;
    }
  }
</style>
