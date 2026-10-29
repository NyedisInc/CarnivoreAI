<script lang="ts">
  import { Icon } from '../sdk/ui';
  import { t } from '../sdk';
  import { removeGroup } from './task-manager-groups.svelte';
  import type { TaskManagerItemGroup } from './huddle-model';
  import TaskManagerTail from './TaskManagerTail.svelte';

  let { group }: { group: TaskManagerItemGroup } = $props();
</script>

<div class="hdeg-head" data-task-manager-level="area" data-task-manager-section-head={group.id} data-task-manager-empty-group={group.id}>
  <span class="hdeg-name">{group.name}</span>
  <span class="hdeg-count" data-task-manager-group-count={group.id}>0</span>
  <button type="button" class="oc-ibtn oc-ibtn--bare hdeg-key" data-task-manager-group-remove={group.id}
          aria-label={t('cplug.huddle.group.remove', { name: group.name })} title={t('cplug.huddle.group.remove_title')}
          onclick={() => void removeGroup(group)}><Icon name="close" size={11} /></button>
  <TaskManagerTail scope={String(group.id)} />
</div>
<p class="hdeg-line" data-task-manager-group-empty={group.id}>{t('cplug.huddle.group.empty')}</p>

<style>
  @layer components {
    .hdeg-head {
      position: relative;
      display: flex;
      align-items: center;
      gap: var(--oc-space-1);
      min-height: 22px;
      padding: 0 var(--oc-space-2) 0 14px;
      background: var(--oc-ground-titlerow);
      box-shadow: inset 2px 0 0 var(--oc-line-frame), inset 0 -1px 0 var(--oc-line-rule), inset 0 1px 0 var(--oc-line-faint);
    }

    .hdeg-name {
      flex: 0 1 auto;
      min-width: 0;
      overflow: hidden;
      color: var(--oc-text-primary);
      font-size: var(--oc-fs-label);
      font-weight: 600;
      letter-spacing: 0.2px;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .hdeg-count {
      flex: none;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-label);
      font-variant-numeric: tabular-nums;
    }

    .hdeg-key {
      --oc-ibtn-size: 18px;
      margin-left: auto;
    }

    .hdeg-key:hover {
      color: var(--oc-coral);
    }

    .hdeg-line {
      position: relative;
      margin: 0;
      padding: 6px var(--oc-space-2) 6px 34px;
      color: var(--oc-text-dim);
      font-size: var(--oc-fs-micro);
      box-shadow: inset 0 -1px 0 var(--oc-line-faint);
    }
  }
</style>
