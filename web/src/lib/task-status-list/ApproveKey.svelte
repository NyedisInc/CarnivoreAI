<script lang="ts">
  /* the Task Manager */
  import Icon from '../../opscenter/ui/Icon.svelte';
  import { t } from '../i18n/index.svelte';
  import { tickItem } from '../../plugins/taskmanager/task-manager-tick-confirm.svelte';
  import type { HuddleItem } from '../../plugins/taskmanager/huddle-model';

  let { item }: { item: HuddleItem } = $props();
  let busy = $state(false);

  async function approve(): Promise<void> {
    if (busy) return;
    busy = true;
    try {
      await tickItem(item, true);
    } finally {
      busy = false;
    }
  }
</script>

<button type="button" class="oc-ibtn oc-ibtn--bare hl-approve" data-task-manager-list-approve={item.id} disabled={busy}
        aria-label={t('opscenter.cell.task_list.approve')} title={t('opscenter.cell.task_list.approve')} onclick={() => void approve()}>
  <Icon name="approve" size={14} />
</button>

<style>
  @layer components {
    .hl-approve { color: var(--oc-orange); }

    .hl-approve:hover:not(:disabled) { color: var(--oc-orange-bright); background: var(--oc-orange-tint); }
  }
</style>
