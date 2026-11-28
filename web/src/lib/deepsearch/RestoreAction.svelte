<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import Button from '../base/Button.svelte';
  import { promptRestore } from '../offload-prompt/offload-prompt';
  import type { DeepGroup } from './deepsearch-api';
  import { isRemote } from './result-model';
  import './search-d.css';

  interface Props {
    group: DeepGroup;
    onrestored?: () => void;
  }
  let { group, onrestored }: Props = $props();

  const label = $derived(group.session ?? group.firstPrompt ?? '');

  async function restore(event: MouseEvent): Promise<void> {
    event.stopPropagation();
    if (await promptRestore({ conversationId: group.conversationId, label })) onrestored?.();
  }
</script>

{#if group.offloaded && !isRemote(group)}
  <div class="sd-acts" role="group" aria-label={t('deepsearch.action.restore')}>
    <Button size="sm" variant="secondary" data-action="restore" title={t('deepsearch.action.restore_tip')} onclick={restore}>{t('deepsearch.action.restore')}</Button>
  </div>
{/if}
