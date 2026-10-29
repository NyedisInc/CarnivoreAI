<script lang="ts">
    import { motionReduced } from '../../lib/motion/motion';
  import { FoldChevron, Icon } from '../sdk/ui';
  import { openModal, projectColorOf, projectColorVar, t } from '../sdk';
  import { listProjectId } from './huddle-model';
  import TaskManagerStatusModal from './TaskManagerStatusModal.svelte';
  import { taskManagerPrefs } from './task-manager-prefs.svelte';
  import { badgeAction, isClickable, statusOfBadge } from './task-manager-status-modal';
  import { toggleViewStatus, viewFilter } from './task-manager-view-filter.svelte';
  import TaskManagerTail from './TaskManagerTail.svelte';
  import { cascadeCue, keepShiftOffSelection } from './task-manager-fold-cascade';
  import { projectBadges, type TailKind } from './task-manager-tail-slots';
  import type { WaitingMark } from './task-manager-waiting';
  import { projectStick, scrollProjectToTop } from './task-manager-sticky';
  import type { TaskManagerSectionKey } from './task-manager-status-sections';

  let { list, heading, count, chips, marks = [], folded, nudge = false, onNudge, index = 0, total = 1, onToggle, accordion = false, stack = null }: {
    list: string;
    heading: string;
    count: number;
    chips: { key: TaskManagerSectionKey; count: number }[];
    marks?: WaitingMark[];
    folded: boolean;
    nudge?: boolean;
    onNudge?: (next: boolean) => void;
    index?: number;
    total?: number;
    onToggle: (event?: MouseEvent) => void;
    accordion?: boolean;
    stack?: 'top' | 'open' | 'bottom' | null;
  } = $props();
  const stick = $derived(projectStick(index, total));

  let head = $state<HTMLElement | null>(null);

  function scrollHere(): void {
    if (accordion && folded) { onToggle(); return; }
    if (head) scrollProjectToTop(head, motionReduced());
  }

  function foldHere(event?: MouseEvent): void {
    if (accordion) { scrollHere(); return; }
    onToggle(event);
  }

  function titleKey(event: KeyboardEvent): void {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    foldHere();
  }

  function pressBadge(kind: TailKind): void {
    const action = badgeAction(kind);
    if (action === 'filter') { toggleViewStatus(statusOfBadge(kind)); return; }
    const badge = projectBadges(folded, marks, chips).find((one) => one.kind === kind);
    if (action !== 'modal' || !badge) return;
    void openModal(TaskManagerStatusModal, { list, heading, kind, marked: true, label: badge.title, count: null, hide: taskManagerPrefs.hideCompleted });
  }

  const badges = $derived(projectBadges(folded, marks, chips).map((badge) => (badgeAction(badge.kind) === 'filter'
    ? { ...badge, title: t(viewFilter.status === badge.kind ? 'cplug.huddle.tail.filter_on_title' : 'cplug.huddle.tail.filter_title', { title: badge.title }) } : badge)));

  const color = $derived(projectColorVar(projectColorOf(listProjectId(list))));
</script>

<h2 class="hd-group" bind:this={head} data-task-manager-level="project" class:hd-stack-top={stack === 'top'} class:hd-stack-open={stack === 'open'} class:hd-stack-bottom={stack === 'bottom'} data-folded={folded ? 'on' : undefined} style:--_project={color} style:--_top={stack === null ? stick.top : undefined} style:--_bottom={stack === null ? stick.bottom : undefined}>
  
  {#if accordion}
    <span class="hd-pchev" aria-hidden="true" data-task-manager-project-fold-none={list}></span>
  {:else}
    <button type="button" class="hd-pchev" aria-expanded={!folded} data-task-manager-project-fold={list}
            aria-label={t(folded ? 'cplug.huddle.project.unfold' : 'cplug.huddle.project.fold', { name: heading })} {@attach cascadeCue()} onmousedown={keepShiftOffSelection} onclick={(event) => onToggle(event)}>
      <FoldChevron />
    </button>
  {/if}
  
  {#if onNudge}
    <button type="button" class="oc-ibtn oc-ibtn--bare hd-pnudge" aria-pressed={nudge} data-task-manager-project-nudge={list} data-on={nudge ? 'on' : 'off'}
            title={t(nudge ? 'cplug.huddle.nudge.on' : 'cplug.huddle.nudge.off')} aria-label={t(nudge ? 'cplug.huddle.nudge.on' : 'cplug.huddle.nudge.off')}
            onclick={() => onNudge(!nudge)}><Icon name="bell" size={12} strokeWidth={1.75} /></button>
  {/if}
  <div class="hd-pfold" role="button" tabindex="0" aria-expanded={accordion ? undefined : !folded} data-task-manager-project-title={list}
       aria-label={t(folded ? 'cplug.huddle.project.unfold' : 'cplug.huddle.project.fold', { name: heading })}
       {@attach cascadeCue()} onmousedown={keepShiftOffSelection} onclick={(event) => foldHere(event)} onkeydown={titleKey}>
    <span class="hd-pcount" data-task-manager-project-count={list}>{count}</span>
    <span class="hd-pname" data-task-manager-heading={list}>{heading}</span>
  </div>
  
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div class="hd-pfold hd-pfill" data-task-manager-project-scroll={list} onclick={scrollHere}>
    <TaskManagerTail scope={list} badges={badges} packed opens={isClickable} onOpen={pressBadge} active={viewFilter.status} />
  </div>
</h2>

<style>
  @layer components {
    .hd-group {
      --_row-gap: 3px;
      display: flex;
      align-items: stretch;
      position: sticky;
      top: var(--_top, 0);
      bottom: var(--_bottom, 0);
      z-index: 3;
      box-sizing: border-box;
      height: var(--hd-phead-h);
      margin: 0;
      padding: 4px 0 0;
      background: var(--oc-ground-panel);
      font-weight: 400;
      box-shadow: inset 3px 0 0 var(--_project, var(--oc-line-rule)), inset 0 -1px 0 var(--oc-line-rule);
    }

    .hd-stack-top,
    .hd-stack-open,
    .hd-stack-bottom {
      position: relative;
      top: auto;
      bottom: auto;
      flex: none;
    }

    .hd-pchev {
      flex: none;
      display: inline-flex;
      align-items: center;
      padding: 0 var(--_row-gap) 0 10px;
      border: 1px solid transparent;
      background: none;
      color: var(--oc-text-muted);
      cursor: pointer;
    }

    .hd-pchev:hover {
      color: var(--oc-text-bright);
    }

    .hd-pfold {
      flex: 0 1 auto;
      display: flex;
      align-items: center;
      gap: 6px;
      min-width: 0;
      padding: 0 var(--oc-space-2) 0 0;
      border: 1px solid transparent;
      background: none;
      color: var(--oc-text-muted);
      font: inherit;
      font-size: var(--oc-fs-body);
      letter-spacing: 0.1em;
      text-transform: uppercase;
      text-align: left;
      cursor: pointer;
    }

    .hd-pfill {
      flex: 1 1 0;
      justify-content: flex-end;
      padding-left: var(--oc-space-2);
    }

    .hd-pfold:hover {
      color: var(--oc-text-bright);
    }

    .hd-pname {
      color: var(--_project, var(--oc-text-secondary));
      font-weight: 600;
    }

    .hd-pfold:hover .hd-pname {
      color: var(--_project, var(--oc-text-bright));
      filter: brightness(1.15);
    }

    .hd-pname {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .hd-pcount {
      flex: none;
      box-sizing: border-box;
      min-inline-size: calc(2ch + 8px);
      padding: 1px 3px;
      border: 1px solid var(--oc-line-rule);
      border-radius: 2px;
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-micro);
      font-variant-numeric: tabular-nums;
      letter-spacing: 0;
      text-align: center;
    }

    .hd-pnudge {
      --oc-ibtn-size: 16px;
      flex: none;
      align-self: center;
      margin-right: var(--_row-gap);
      color: var(--oc-text-dim);
    }

    .hd-pnudge[data-on='on'] {
      color: var(--oc-orange);
    }

    .hd-pnudge:hover {
      color: var(--oc-text-bright);
    }

    @container hdb (max-width: 439px) {
      .hd-group {
        display: grid;
        grid-template-columns: auto auto minmax(0, 1fr);
        grid-template-rows: 26px 22px;
        align-items: center;
      }

      .hd-pchev { grid-column: 1; grid-row: 1; }
      .hd-pnudge { grid-column: 2; grid-row: 1; }
      .hd-pfold:not(.hd-pfill) { grid-column: 3; grid-row: 1; }

      .hd-pfill {
        grid-column: 1 / -1;
        grid-row: 2;
        justify-content: flex-end;
        padding: 0 10px 0 0;
      }
    }
  }
</style>
