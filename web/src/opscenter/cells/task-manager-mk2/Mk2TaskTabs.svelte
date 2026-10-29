<script lang="ts">
  /* padding */
  import { getContext, untrack } from 'svelte';
  import { buttonAttrs } from '../../../lib/base/classes';
  import { titleWhenTruncated } from '../../../lib/base/truncate';
  import { MK2_VIEW, type Mk2ViewHolder } from './mk2-view-context';
  import { saveTab } from './mk2-view-state.svelte';
  import { isApproved, type HuddleItem } from '../../../cplugs/huddle/huddle-model';
  import { huddle } from '../../../cplugs/huddle/huddle.svelte';
  import HuddleReview from '../../../cplugs/huddle/HuddleReview.svelte';
  import TaskManagerScheduleKeys from '../../../cplugs/huddle/TaskManagerScheduleKeys.svelte';
  import HuddleReply from '../../../cplugs/huddle/HuddleReply.svelte';
  import TaskManagerRowPosts from '../../../cplugs/huddle/TaskManagerRowPosts.svelte';
  import { decisionKeys } from '../../../cplugs/huddle/chat/chat-model';
  import { wrapperParts } from '../../../cplugs/huddle/huddle-density';
  import { reviewAnswerOf, reviewOf } from '../../../cplugs/huddle/huddle-review';
  import { stepsOfItem } from '../../../cplugs/huddle/task-manager-steps.svelte';
  import { taskOf } from '../../../cplugs/huddle/task-manager-design/adapter';
  import { inspectionOf } from '../../../cplugs/huddle/task-manager-design/inspection.svelte';
  import { newCount, type Resource, type Tab } from '../../../cplugs/huddle/task-manager-design/model';
  import './mk2-design.css';
  import Tabs, { panelAttrs, type TabDef } from '../../ui/Tabs.svelte';
  import { t } from '../../../lib/i18n/index.svelte';
  import { TaskAgeClock } from '../task-list/task-clock.svelte';
  import Mk2Details from './Mk2Details.svelte';
  import Mk2Discussion from './Mk2Discussion.svelte';
  import Mk2MarkRead from './Mk2MarkRead.svelte';
  import Mk2ReviewChecks from './Mk2ReviewChecks.svelte';
  import Mk2SharedViewer from './Mk2SharedViewer.svelte';
  import Mk2Subtasks from './Mk2Subtasks.svelte';
  import { actionableIdOf, actionDataOf, statusLinesOf } from './mk2-task-tabs';
  import { progressOf, sinceRead } from '../../../cplugs/huddle/task-manager-progress.svelte';
  import { waitLine } from '../../../cplugs/huddle/task-manager-wait';

  let { item, detailed = false }: { item: HuddleItem; detailed?: boolean } = $props();

  const ages = new TaskAgeClock();
  $effect(() => ages.hold());
  const project = $derived(huddle.lists.find((row) => row.key === item.list)?.name ?? item.list);
  const task = $derived(taskOf({ item, project, list: item.list }, { steps: stepsOfItem(item.list, item.id), clock: ages.wording() }));
  const view = $derived(inspectionOf(task.id, () => task.messages));
  const wait = $derived(waitLine(item, new Date(), { t, due: { today: t('cplug.huddle.schedule.today'), tomorrow: t('cplug.huddle.schedule.tomorrow') } }));
  const action = $derived(actionDataOf(item, wait));
  const workers = $derived(statusLinesOf(progressOf(item.id), sinceRead(), { t }));
  const actionable = $derived(actionableIdOf(item));
  const review = $derived(reviewOf(item));
  const keep = getContext<Mk2ViewHolder | undefined>(MK2_VIEW);
  let restored = false;
  $effect(() => {
    const open = task.id;
    const tab = view.tab;
    untrack(() => {
      if (!keep) return;
      if (!restored) {
        restored = true;
        if (keep.view?.open === open && keep.view.tab !== tab && tab === 'action') { view.tab = keep.view.tab; return; }
      }
      saveTab(keep, open, tab);
    });
  });
  const TAB_ICON: Readonly<Record<string, string>> = { action: 'bolt', discussion: 'chat', details: 'info', subtasks: 'list' };
  const taskTabs = $derived<TabDef[]>((['action', 'discussion', 'details', 'subtasks'] as const).map((id) => ({
    id,
    label: id === 'discussion' && newCount(task) ? t('cplug.huddle.tm.tab_unread', { n: newCount(task) }) : t(`cplug.huddle.tm.tab_${id}`),
    icon: TAB_ICON[id],
    //  hidden 
    dot: id === 'discussion' && newCount(task) > 0,
  })));
  const idBase = $derived(`tm-task-${task.id}`);

  let viewer = $state<Resource | null>(null);
  let resourceVersion = $state('');
  let backTab = $state<Tab>('details');
  let source = $state(-1);
  let sourceResource = $state<Resource | null>(null);

  function openResource(id: string): void {
    const resource = (task.shared ?? task.review?.resources ?? []).find((r) => r.id === id);
    if (!resource) return;
    backTab = view.tab; viewer = resource; resourceVersion = resource.rev ?? '';
  }

  function inspectSource(resource: Resource): void {
    sourceResource = resource; source = resource.source ?? -1; view.earlier = true; viewer = null; view.tab = 'discussion';
  }

  function restoreResource(): void {
    viewer = sourceResource; sourceResource = null; source = -1; view.tab = backTab;
  }
</script>

<div class="mk2-design" data-task-manager-mk2-tabs={item.id}>
  <section class="tn-detail" aria-label={t('cplug.huddle.tm.details_of', { title: task.title })}>
    <Tabs compact collapse tabs={taskTabs} active={view.tab} onSelect={(id) => { view.tab = id as Tab; viewer = null; source = -1; }} label={t('cplug.huddle.tm.task_view')} {idBase}>{#snippet trailing()}<Mk2MarkRead {item} />{/snippet}</Tabs>
    <div class="tn-tabbody" {...panelAttrs(idBase, view.tab)} data-task-manager-mk2-tab={view.tab} data-mk2-detailed={detailed ? '' : undefined}>
      {#if viewer}
        <Mk2SharedViewer itemId={task.id} resource={viewer} {backTab} bind:version={resourceVersion} onBack={() => { viewer = null; view.tab = backTab; }} onSource={inspectSource} />
      {:else if view.tab === 'discussion'}
        {#if sourceResource}<button type="button" class="tn-chip" use:titleWhenTruncated {...buttonAttrs('secondary', 'sm')} onclick={restoreResource}>{t('cplug.huddle.tm.back_to', { tab: sourceResource.name })}</button>{/if}
        <Mk2Discussion {task} {view} {source} {detailed} onResource={openResource} />
      {:else if view.tab === 'details'}
        <Mk2Details {task} {item} {detailed} onResource={openResource} onSource={inspectSource} />
      {:else if view.tab === 'subtasks'}
        <Mk2Subtasks {item} />
      {:else}
        {#if review}<HuddleReview block={review} id={item.id} answer={reviewAnswerOf(item)} issue={item.github_issue} foldAll unfolded={detailed} />{/if}
        {#if actionable !== null}<div class="mk2-actionable" data-mk2-actionable={actionable}><TaskManagerRowPosts {item} parts={wrapperParts('opened', item)} only={actionable} unfolded={detailed} oneLine /></div>{/if}
        <dl class="mk2-rows">
          {#if workers.length || action.statusKey}
            <dt>{t('opscenter.cell.task_manager_mk2.tab.status')}</dt>
            <dd data-mk2-status>{#if workers.length}{#each workers as line (line.worker)}<span class="mk2-worker" class:mk2-worker--stale={line.stale} data-mk2-worker={line.worker}>{line.text}</span>{/each}{:else if action.statusKey}{t(action.statusKey)}{/if}</dd>
          {/if}
          {#each action.rows as row (row.labelKey)}<dt>{t(row.labelKey)}</dt><dd>{row.value}</dd>{/each}
        </dl>
        
        {#if item.start_trigger && !isApproved(item.state)}<div class="mk2-sched-keys" data-mk2-schedule-keys={item.id}><TaskManagerScheduleKeys {item} /></div>{/if}
        <Mk2ReviewChecks {item} />
      {/if}
      {#if !decisionKeys(item)}<div class="mk2-reply" data-mk2-reply={item.id}><HuddleReply {item} /></div>{/if}
    </div>
  </section>
</div>

<style>
  @layer components {
    .mk2-rows {
      display: grid;
      grid-template-columns: max-content minmax(0, 1fr);
      gap: var(--oc-space-2) var(--oc-space-4);
      margin: var(--oc-space-3) 0;
    }

    .mk2-rows dt {
      color: var(--oc-text-muted);
      letter-spacing: 0.1em;
      text-transform: uppercase;
    }

    .mk2-rows dd {
      margin: 0;
      color: var(--oc-text-primary);
    }

    /* padding */
    .mk2-worker {
      display: block;
      overflow-wrap: anywhere;
    }

    .mk2-worker--stale {
      color: var(--oc-text-dim);
    }

    .mk2-reply {
      margin-top: var(--oc-space-4);
    }

    .mk2-sched-keys {
      display: flex;
      flex-wrap: wrap;
      gap: var(--oc-space-2);
      margin-bottom: var(--oc-space-3);
    }

    .mk2-actionable {
      min-width: 0;
    }
  }
</style>
