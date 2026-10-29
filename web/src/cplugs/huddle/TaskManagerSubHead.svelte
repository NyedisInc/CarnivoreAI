<script lang="ts">
  import { FoldChevron, Icon } from '../sdk/ui';
  import { t } from '../sdk';
  import TaskManagerTail from './TaskManagerTail.svelte';
  import { keepShiftOffSelection } from './task-manager-fold-cascade';
  import { marksToBadges, type TailKind } from './task-manager-tail-slots';
  import type { WaitingMark } from './task-manager-waiting';
  import { SECTION_ICON, SECTION_ICON_COLOR, type TaskManagerSectionKey } from './task-manager-status-sections';

  let { fold, status, name, folded, count, onToggle, dropArea, over = false, marks = [], kinds }: {
    fold: string;
    status: TaskManagerSectionKey;
    name: string;
    folded: boolean;
    count: number;
    onToggle: () => void;
    dropArea?: string;
    over?: boolean;
    kinds?: readonly TailKind[];
    marks?: WaitingMark[];
  } = $props();
</script>

<li class="hds-sub" data-task-manager-level="sub" class:hds-sub--over={over} data-task-manager-area-sub={fold} data-folded={folded ? 'on' : undefined}
    data-task-manager-area-drop={dropArea}>
  <button type="button" class="hds-sub-fold" aria-expanded={!folded} data-task-manager-area-sub-fold={fold}
          onmousedown={keepShiftOffSelection} onclick={onToggle}>
    <FoldChevron />
    <span class="hds-sub-mark" style:--_mark={SECTION_ICON_COLOR[status]} data-task-manager-section-icon={SECTION_ICON[status]} aria-hidden="true"><Icon name={SECTION_ICON[status]} size={11} strokeWidth={1.75} /></span>
    <span class="hds-sub-name">{name}</span>
    <span class="hds-count" data-task-manager-area-sub-count={fold}>{count}</span>
  </button>
  <TaskManagerTail scope={fold} badges={marksToBadges(marks)} {kinds} />
</li>

<style>
  @layer components {
    .hds-sub {
      position: relative;
      display: flex;
      align-items: center;
      min-height: 20px;
      padding: 0 var(--oc-space-2) 0 calc(14px + var(--hd-step, 0px));
      box-shadow: inset 0 -1px 0 var(--oc-line-faint);
    }

    .hds-sub--over {
      background: var(--oc-orange-tint);
      color: var(--oc-orange);
      box-shadow: inset 0 0 0 1px var(--oc-orange);
    }

    .hds-sub--over .hds-sub-fold {
      color: var(--oc-orange);
    }

    .hds-sub-fold {
      display: inline-flex;
      flex: 0 1 auto;
      align-items: center;
      gap: 6px;
      min-width: 0;
      padding: 1px 0;
      border: 1px solid transparent;
      background: none;
      color: var(--oc-text-muted);
      font: inherit;
      font-size: var(--oc-fs-micro);
      letter-spacing: var(--oc-tracking-label, 0.6px);
      text-transform: lowercase;
      text-align: left;
      cursor: pointer;
    }

    .hds-sub-fold:hover {
      color: var(--oc-text-bright);
    }

    .hds-sub-mark {
      flex: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 11px;
      color: var(--_mark);
    }

    .hds-sub-name {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .hds-count {
      color: var(--oc-text-muted);
      font-variant-numeric: tabular-nums;
      letter-spacing: 0;
    }
  }
</style>
