<script lang="ts">
  import { Button } from '../base';
  import { t } from '../i18n/index.svelte';
  import './search-d.css';
  import type { DeepSearchController } from './deepsearch.svelte';
  import type { DeepGroup } from './deepsearch-api';
  import { hiddenCount, visibleHits } from './result-model';

  interface Props {
    controller: DeepSearchController;
    group: DeepGroup;
  }
  let { controller, group }: Props = $props();
  const open = $derived(controller.expanded[group.conversationId] === true);
  const hidden = $derived(hiddenCount(group, open));
</script>

{#if hidden > 0 && !open}
  <Button variant="quiet" size="sm" data-testid="deepsearch-more-in" onmousedown={(e) => e.preventDefault()}
    onclick={() => void controller.expand(group)}>{t('deepsearch.more_in', { count: hidden })}</Button>
{:else if open && group.matches > visibleHits(group, true).length}
  <span class="sd-more dps__capped" data-testid="deepsearch-capped">{t('deepsearch.capped', { shown: visibleHits(group, true).length, total: group.matches })}</span>
{/if}
