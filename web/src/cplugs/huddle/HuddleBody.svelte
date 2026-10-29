<script lang="ts">
  /* pop-out window show empty groups */
  import { getContext, tick, untrack, type Snippet } from 'svelte';
  import '../sdk/ledger-chrome';
  import { Icon } from '../sdk/ui';
  import { currentProjectId, flyoutShowsTab, projectColorOf, projectColorVar, sidebarTabs, t } from '../sdk';
  import { PROJECT_HEAD_HEIGHT_PX, PROJECT_HEAD_HEIGHT_VAR, accordionStackFits, projectHeadHeight, sectionTop, stackSide } from './task-manager-sticky';
  import { addItem, doneCount, holdAggregate, holdSwarmLane, huddle, openOnProject, refreshTaskManager, removeCompleted, selectList, startTaskManager } from './huddle.svelte';
  import { setListNudge } from './task-list-prefs';
  import { holdDone } from './task-manager-done.svelte';
  import TaskManagerInboxRow from './TaskManagerInboxRow.svelte';
  import { pinView } from './task-manager-view';
  import { taskManagerPrefs, setHideCompleted, setShowEmptyGroups } from './task-manager-prefs.svelte';
  import {
    AGGREGATE, ALL_LIST, completedCount, listProjectId, wholeEntry, unreadTotal, visibleItems, waitingQuestions,
    type TaskManagerInboxEntry, type HuddleItem, type TaskManagerItemGroup, type TaskManagerListRow,
  } from './huddle-model';
  import { TASK_MANAGER_TAB } from './huddle-tab-id';
  import { firstPopoutList, rememberPopoutList } from './task-manager-popout-list';
  import { clearFocus, taskManagerFocus, startFocus } from './task-manager-focus.svelte';
  import { foldsHiding } from './task-manager-reveal';
  import TaskManagerSections from './TaskManagerSections.svelte';
  import SwarmPanelLive from './swarm/SwarmPanelLive.svelte';
  import { swarmView } from './huddle-swarm-view.svelte';
  import { swarmRoster } from './agents/agent-roster.svelte';
  import TaskManagerStatusSections from './TaskManagerStatusSections.svelte';
  import TaskManagerProjectHead from './TaskManagerProjectHead.svelte';
  import { accordionOpenKey, accordionToggle, hiddenSections, isFolded, projectFoldKey, setSectionFolded } from './task-manager-status-folds.svelte';
  import { foldAll, underProject } from './task-manager-fold-cascade';
  import { sectionOf, statusSections, withoutSections, type TaskManagerSectionKey } from './task-manager-status-sections';
  import { waitingMarks } from './task-manager-waiting';
  import HuddleViewSwitch from './HuddleViewSwitch.svelte';
  import TaskManagerStatusFilter from './TaskManagerStatusFilter.svelte';
  import TaskManagerMarkerFilter from './TaskManagerMarkerFilter.svelte';
  import TaskManagerSearch from './TaskManagerSearch.svelte';
  import { filterView, viewFilter, viewFilterActive } from './task-manager-view-filter.svelte';
  import TaskManagerNewGroup from './TaskManagerNewGroup.svelte';
  import TaskManagerSend from './TaskManagerSend.svelte';
  import { BODY_OPTIONS, DEFAULT_BODY_OPTIONS, type BodyOptions } from './task-manager-body-options';
  import { baseField } from './task-manager-base-field';
  import { createScrollKeeper, isKeeperScroll } from './task-manager-scroll-keep';
  import { applyHold, takeSnapshot } from './task-manager-view-hold';
  import { createViewHold } from './task-manager-view-hold.svelte';
  import { reopenPick, sendPicks } from './huddle-send-many.svelte';
  import TaskManagerScheduleEditor from './TaskManagerScheduleEditor.svelte';
  import TaskManagerArtifactDialog from './TaskManagerArtifactDialog.svelte';
  import TaskManagerForkDialog from './TaskManagerForkDialog.svelte';
  import TaskManagerTickConfirm from './TaskManagerTickConfirm.svelte';
  import { listLabel } from './task-manager-schedule-project';
  import { isAgentList } from './huddle-model';

  async function flipNudge(list: string, next: boolean): Promise<void> {
    const id = listProjectId(list);
    if (id === null) return;
    try {
      await setListNudge(id, next);
    } catch (error) {
      console.warn('huddle: could not change the nudge', error);
    }
    await refreshTaskManager();
  }
  import { startFollow } from './task-manager-follow.svelte';
  import { holdSteps, releaseSteps } from './task-manager-steps.svelte';
  import { createSentFlash, submitLook } from './task-submit-state.svelte';
  import { submitNow } from './task-submit';
  import { FOOTER_ICON_PX } from './task-manager-footer';

  let { popout = false, agent = null, list = null, bar = undefined }: { popout?: boolean; agent?: number | null; list?: string | null; bar?: Snippet<[HuddleItem[]]> } = $props();

  const bodyOptions: Readonly<BodyOptions> = getContext<BodyOptions | undefined>(BODY_OPTIONS) ?? DEFAULT_BODY_OPTIONS;

  const MULTILINE_ROWS = 5;

  let draft = $state('');
  let multiline = $state(false);
  let confirmRemove = $state(false);
  let root = $state<HTMLElement | null>(null);
  /* hide empty groups */
  const emptyWords = $derived(t(taskManagerPrefs.showEmptyGroups ? 'cplug.huddle.empty_groups.hide' : 'cplug.huddle.empty_groups.show'));
  let naming = $state(false);

  const agentList = $derived(agent === null ? null : (swarmRoster.agents.find((a) => a.id === agent)?.thread_key ?? `agent:${agent}`));
  const pinnedList = $derived(list ?? agentList);
  const pinnedAll = $derived(pinnedList === AGGREGATE);
  const swarmOn = $derived(!popout && pinnedList === null && swarmView.view === 'swarm');
  const pinnedProject = $derived(pinnedList !== null && pinnedList !== AGGREGATE && agent === null && !isAgentList(pinnedList));
  const viewList = $derived(pinnedAll ? AGGREGATE : pinnedProject ? (pinnedList as string) : huddle.selected);
  const aggregate = $derived(viewList === AGGREGATE);
  const offered = (key: string, keep: string): boolean => !isAgentList(key) || key === keep;
  const allGroups = $derived.by((): { list: string; heading: string | null; items: HuddleItem[]; named: TaskManagerItemGroup[]; inbox: TaskManagerInboxEntry[] }[] => {
    if (aggregate) {
      return (huddle.groups ?? []).filter((g) => !isAgentList(g.list)).map((g) => ({ list: g.list, heading: groupName(g.list, g.name), items: g.items, named: g.groups ?? [], inbox: g.inbox ?? [] }));
    }
    if (pinnedProject) {
      const own = huddle.groups?.find((g) => g.list === viewList);
      return own ? [{ list: viewList, heading: null, items: own.items, named: own.groups ?? [], inbox: own.inbox ?? [] }] : [];
    }
    return huddle.body?.list === viewList
      ? [{ list: viewList, heading: null, items: huddle.body.items, named: huddle.body.groups ?? [], inbox: huddle.body.inbox ?? [] }] : [];
  });
  const filtering = $derived(viewFilterActive());
  const looking = createViewHold();
  $effect(() => () => looking.release());
  const holdSignature = $derived(JSON.stringify([viewList, taskManagerPrefs.view, taskManagerPrefs.hideCompleted, taskManagerPrefs.showEmptyGroups, hiddenSections.keys, viewFilter.query, viewFilter.chip ?? null, viewFilter.markers, viewFilter.status]));
  const groups = $derived(allGroups.map((g) => {
    const live = filterView(withoutSections(g.items, hiddenSections.keys));
    const scoped = bodyOptions.holdWhileLooking ? applyHold(looking.snapshot, holdSignature, g.list, live) : live;
    const items = visibleItems(scoped, taskManagerPrefs.hideCompleted);
    const named = taskManagerPrefs.showEmptyGroups && !filtering ? g.named : g.named.filter((n) => items.some((i) => i.group === n.id));
    const doneAll = taskManagerPrefs.hideCompleted || hiddenSections.keys.includes('done') || filtering ? 0 : doneCount(g.list);
    const done = Math.max(0, doneAll - g.items.filter((i) => sectionOf(i) === 'done').length);
    return { ...g, all: g.items, scoped, items, done, doneAll, inbox: filtering ? [] : g.inbox, named: filtering ? named.map((n) => ({ ...n, folded: false })) : named };
  }));
  /*  hidden  */
  const filterItems = $derived(allGroups.flatMap((g) => g.items));
  const doneLeftTotal = $derived(groups.reduce((n, g) => n + g.done, 0));
  const byArea = $derived(taskManagerPrefs.view === 'area');
  const doneLists = $derived(byArea ? groups.filter((g) => g.doneAll > 0).map((g) => g.list).join('\n') : '');
  $effect(() => {
    if (doneLists === '') return;
    const releases = doneLists.split('\n').map((key) => holdDone(key));
    return () => releases.forEach((release) => release());
  });
  const shown = $derived(groups.reduce((n, g) => n + g.items.length + g.named.length + g.inbox.length + (g.done > 0 ? 1 : 0), 0));
  const drawnProjects = $derived(groups.filter((g) => g.items.length > 0 || g.done > 0 || g.inbox.length > 0 || (hiddenSections.keys.length === 0 && g.named.length > 0)));
  const projectKeys = $derived(drawnProjects.filter((g) => g.heading !== null).map((g) => projectFoldKey(g.list)));
  const accordionOn = $derived(taskManagerPrefs.accordion && !filtering);
  const accordionOpen = $derived(accordionOn ? accordionOpenKey(projectKeys) : null);

  let scrollHeight = $state(0);
  let scrollWidth = $state(0);
  let scrollBox = $state<HTMLElement | null>(null);
  $effect(() => {
    const box = scrollBox;
    if (!box || typeof ResizeObserver === 'undefined') return;
    const measure = (): void => { scrollHeight = box.clientHeight; scrollWidth = box.clientWidth; };
    const watch = new ResizeObserver(measure);
    watch.observe(box);
    measure();
    return () => watch.disconnect();
  });
  const stacked = $derived(accordionOn && accordionOpen !== null && accordionStackFits(scrollHeight, projectKeys.length, projectHeadHeight(scrollWidth)));
  const listRead = $derived(aggregate || pinnedProject ? huddle.groups !== null : huddle.body?.list === viewList);
  /* new read */
  $effect(() => {
    if (!listRead) return;
    const scroller = stacked ? scrollBox?.querySelector<HTMLElement>('[data-task-manager-open-body]') : scrollBox;
    if (!scroller) return;
    return createScrollKeeper(scroller);
  });
  $effect(() => {
    if (stacked && scrollBox) {
      void accordionOpen;
      scrollBox.scrollTop = 0;
    }
  });
  const openIndex = $derived(drawnProjects.findIndex((g) => g.heading !== null && projectFoldKey(g.list) === accordionOpen));

  function projectFoldedOf(group: { list: string; heading: string | null }): boolean {
    const fold = projectFoldKey(group.list);
    return group.heading !== null && (accordionOn ? fold !== accordionOpen : isFolded(fold));
  }

  function toggleProject(group: { list: string; all: HuddleItem[]; named: TaskManagerItemGroup[] }, fold: string, folded: boolean, event?: MouseEvent): void {
    if (accordionOn) accordionToggle(projectKeys, fold);
    else if (event?.shiftKey) {
      const under = underProject(taskManagerPrefs.view, group.list, group.all, group.named, taskManagerPrefs.hideCompleted);
      foldAll({ keys: [fold, ...under.keys], groups: under.groups }, !folded);
    } else setSectionFolded(fold, !folded);
  }

  function chipsOf(group: { all: HuddleItem[]; done: number }): { key: TaskManagerSectionKey; count: number }[] {
    const chips = statusSections(withoutSections(group.all, hiddenSections.keys), taskManagerPrefs.hideCompleted, false).map((s) => ({ key: s.key, count: s.items.length }));
    if (group.done === 0) return chips;
    const at = chips.findIndex((c) => c.key === 'done');
    return at < 0 ? [...chips, { key: 'done' as const, count: group.done }] : chips.map((c, i) => (i === at ? { ...c, count: c.count + group.done } : c));
  }

  const groupTarget = $derived(aggregate ? huddle.addTarget : viewList);
  const completed = $derived(allGroups.reduce((n, g) => n + Math.max(completedCount(g.items), doneCount(g.list)), 0));
  const removeWords = $derived(t('cplug.huddle.completed.button', { count: completed }));
  const removeAsk = $derived(t(aggregate ? 'cplug.huddle.completed.confirm_all' : 'cplug.huddle.completed.confirm', { count: completed }));
  const entry = $derived(wholeEntry(draft));
  const sent = createSentFlash();
  const addLook = $derived(submitLook(entry.length > 0, sent.on));
  const options = $derived<TaskManagerListRow[]>([
    { key: AGGREGATE, name: null, project_id: null, items: 0, open: 0, review: 0,
      questions: waitingQuestions(huddle.lists) ?? 0, claude_seq: 0, unread: unreadTotal(huddle.lists) ?? 0 },
    ...(huddle.lists.length ? huddle.lists.filter((r) => offered(r.key, viewList)) : [{ key: ALL_LIST, name: null, project_id: null, items: 0, open: 0,
      review: 0, questions: 0, claude_seq: 0 }]),
  ]);
  const targets = $derived(huddle.lists.length ? huddle.lists.filter((r) => offered(r.key, huddle.addTarget)) : options.slice(1));
  const addTargetName = $derived.by(() => {
    const key = pinnedList !== null && !pinnedAll ? pinnedList : huddle.addTarget;
    if (!key || key === AGGREGATE || key === ALL_LIST) return null;
    const row = huddle.lists.find((r) => r.key === key);
    return row ? groupName(row.key, row.name) : null;
  });
  const addPlaceholder = $derived(addTargetName ? t('cplug.huddle.add.placeholder_for', { name: addTargetName }) : t('cplug.huddle.add.placeholder'));

  function firstList(): string | null {
    return popout ? firstPopoutList(window.sessionStorage, window.name, window.location.search) : null;
  }

  startTaskManager(firstList());
  $effect(() => {
    if (popout) rememberPopoutList(window.sessionStorage, window.name, huddle.selected);
  });
  startFocus();
  startFollow();
  $effect(() => {
    holdSteps();
    return releaseSteps;
  });

  /*  hidden  */
  function drawnItem(id: number): { item: HuddleItem; group: (typeof groups)[number] } | null {
    for (const group of groups) {
      const item = group.all.find((i) => i.id === id);
      if (item) return { item, group };
    }
    return null;
  }

  function unfoldFor(id: number): boolean {
    const found = drawnItem(id);
    if (!found) return false;
    const { item, group } = found;
    const hiding = foldsHiding(taskManagerPrefs.view, group.list, item, group.all, group.named, taskManagerPrefs.hideCompleted);
    const project = projectFoldKey(group.list);
    const [, ...inside] = hiding.keys;
    if (group.heading !== null && accordionOn && accordionOpen !== project) accordionToggle(projectKeys, project);
    const keys = [...(group.heading !== null && !accordionOn ? [project] : []), ...inside].filter((key) => isFolded(key));
    foldAll({ keys, groups: hiding.groups.filter((g) => g.folded) }, false);
    return true;
  }

  let revealedSeq = 0;

  $effect(() => {
    const seq = taskManagerFocus.applied;
    const focus = taskManagerFocus.focus;
    if (!seq || !focus || !root || seq === revealedSeq) return;
    const target = focus.open ?? focus.items[0];
    if (target === undefined || !unfoldFor(target)) return;
    revealedSeq = seq;
    const host = root;
    void tick().then(() => requestAnimationFrame(() => host.querySelector<HTMLElement>(`[data-huddle-item="${target}"]`)?.scrollIntoView?.({ block: 'nearest' })));
  });

  function lookAtList(e?: Event): void {
    if (e?.type === 'scroll' && e.currentTarget instanceof HTMLElement && isKeeperScroll(e.currentTarget)) return;
    if (bodyOptions.holdWhileLooking) looking.look(() => takeSnapshot(holdSignature, groups.map((g) => [g.list, g.scoped] as const)), e?.type === 'pointermove');
  }

  function ownerActed(): void {
    if (bodyOptions.holdWhileLooking) looking.act();
  }

  function ownerKey(event: KeyboardEvent): void {
    if (event.key === 'Enter') ownerActed();
  }

  function touched(): void {
    if (taskManagerFocus.focus) void clearFocus();
  }

  let opening: string | null = agent !== null || list !== null ? null : popout ? firstList() : (currentProjectId()?.toString() ?? null);
  $effect(() => {
    if (opening === null || huddle.lists.length === 0) return;
    const key = opening;
    opening = null;
    void openOnProject(key);
  });

  if (list === AGGREGATE) pinView(AGGREGATE);
  $effect(() => {
    if (!pinnedAll && !pinnedProject) return;
    return untrack(() => holdAggregate());
  });

  $effect(() => {
    if (agentList === null) return;
    return holdSwarmLane(agentList);
  });

  $effect(() => {
    const key = pinnedList;
    if (key === null || key === AGGREGATE) return;
    if (pinnedProject) { untrack(() => { huddle.addTarget = key; }); return; }
    const before = untrack(() => huddle.selected);
    untrack(() => {
      huddle.addTarget = key;
      void selectList(key);
    });
    return () => { if (before !== key) untrack(() => void selectList(before)); };
  });

  $effect(() => {
    huddle.viewing = popout || sidebarTabs.active() === TASK_MANAGER_TAB || flyoutShowsTab(TASK_MANAGER_TAB);
  });

  function pickList(key: string): Promise<void> {
    if (key !== AGGREGATE) huddle.addTarget = key;
    return selectList(key);
  }

  function nameOf(row: TaskManagerListRow): string {
    if (row.key === AGGREGATE) return t('cplug.huddle.list.all');
    return groupName(row.key, row.name);
  }

  const groupName = listLabel;

  async function add(): Promise<void> {
    if (!entry) return;
    const save = async (): Promise<boolean> => {
      const outcome = await addItem(entry); // did not answer
      if (outcome !== 'failed') { draft = ''; sent.flash(); }
      return outcome === 'added';
    };
    await submitNow(huddle.addTarget, save);
  }

  function onAreaKey(event: KeyboardEvent): void {
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      void add();
    }
  }

  function toggleMultiline(): void {
    multiline = !multiline;
    if (!multiline) draft = draft.replace(/\s*\r?\n\s*/g, ' ').trim();
  }

  async function confirmRemoveCompleted(): Promise<void> {
    confirmRemove = false;
    await removeCompleted(viewList);
  }

  function startGroup(): void {
    confirmRemove = false;
    naming = true;
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="hd" bind:this={root} data-task-manager-body data-popout={popout ? 'on' : undefined}
     onpointerdowncapture={touched} onkeydowncapture={(event) => { touched(); ownerKey(event); }} onpointerupcapture={ownerActed}>
  {#if pinnedList === null && !swarmOn}
  <div class="hd-bar">
    <label class="hd-pick-label" for="task-list-pick">{t('cplug.huddle.list.label')}</label>
    <select id="task-list-pick" class="oc-field hd-pick" value={huddle.selected} data-huddle-pick
            onchange={(event) => void pickList((event.currentTarget as HTMLSelectElement).value)}>
      {#each options as row (row.key)}
        <option value={row.key} data-huddle-pick-unread={row.unread || undefined}>{nameOf(row)}{row.unread ? ` (${row.unread})` : ''}</option>
      {/each}
    </select>
    <HuddleViewSwitch viewKeys />
    <TaskManagerMarkerFilter items={filterItems} />
    <TaskManagerSearch />
    <TaskManagerStatusFilter items={filterItems} doneLeft={doneLeftTotal} />
  </div>
  {:else if list !== null && bar}
  {@render bar(filterItems)}
  {:else if list !== null}
  <div class="hd-bar" data-task-manager-widget-bar><HuddleViewSwitch viewKeys /><TaskManagerMarkerFilter items={filterItems} /><TaskManagerSearch /><TaskManagerStatusFilter items={filterItems} doneLeft={doneLeftTotal} /></div>
  {/if}
  {#if !popout && pinnedList === null}
    <div class="hd-swarm" hidden={!swarmOn} data-task-manager-swarm><SwarmPanelLive /></div>
  {/if}
  {#if !swarmOn}
  {#if huddle.notice}
    {#if sendPicks.reopen?.length}
      <button type="button" class="hd-notice" data-task-manager-notice data-task-manager-notice-pick onclick={reopenPick}>{huddle.notice}</button>
    {:else}
      <p class="hd-notice" role="status" data-task-manager-notice>{huddle.notice}</p>
    {/if}
  {/if}

  {#if shown > 0}
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="hd-scroll" class:hd-scroll--stack={stacked} data-task-manager-accordion-stack={stacked ? 'on' : undefined} bind:this={scrollBox} onpointermove={lookAtList} onpointerleave={() => looking.leave()} onscroll={lookAtList} onfocusin={lookAtList} style="{PROJECT_HEAD_HEIGHT_VAR}: {PROJECT_HEAD_HEIGHT_PX}px" data-task-manager-scroll>
      {#each drawnProjects as group, at (group.list)}
        {@const fold = projectFoldKey(group.list)}
        {@const projectFolded = projectFoldedOf(group)}
        {#if group.heading !== null}
          <TaskManagerProjectHead list={group.list} heading={group.heading} count={group.items.length + group.done} folded={projectFolded} nudge={huddle.lists.find((r) => r.key === group.list)?.nudge === true}
                             onNudge={listProjectId(group.list) === null ? undefined : (next) => void flipNudge(group.list, next)}
                             index={at} total={drawnProjects.length} accordion={accordionOn} stack={stacked ? stackSide(at, openIndex) : null}
                             chips={chipsOf(group)}
                             marks={waitingMarks(visibleItems(group.all, taskManagerPrefs.hideCompleted))}
                             onToggle={(event) => toggleProject(group, fold, projectFolded, event)} />
        {/if}
        {#if !projectFolded}
          {@const Sections = byArea ? TaskManagerSections : TaskManagerStatusSections}
          
          <div class="hd-block" class:hd-block--open={stacked} data-task-manager-open-body={stacked ? 'on' : undefined} style:--hd-project={projectColorVar(projectColorOf(listProjectId(group.list)))}
               style:--hd-stick-top={stacked ? '0px' : sectionTop(group.heading !== null, at)} data-task-manager-block={group.list}>
            {#each group.inbox as entry (entry.id)}<TaskManagerInboxRow {entry} />{/each}
            <Sections list={group.list} items={group.scoped} groups={group.named} hide={taskManagerPrefs.hideCompleted} lines={popout ? 2 : 1} doneTotal={group.doneAll} />
          </div>
        {/if}
      {/each}
      
      {#if bodyOptions.scheduleBlocks && aggregate && !byArea && !groups.some((g) => statusSections(g.all, taskManagerPrefs.hideCompleted, false).some((s) => s.key === 'scheduled'))}
        <TaskManagerStatusSections list={AGGREGATE} items={[]} bare />
      {/if}
    </div>
  {:else}
    {#if !byArea && bodyOptions.scheduleBlocks}<TaskManagerStatusSections list={viewList} items={[]} bare />{/if}
    <p class="hd-empty" data-task-manager-empty>{!listRead && huddle.status !== 'error'
      ? t('cplug.huddle.loading') : filtering ? t('cplug.huddle.search.none') : completed > 0 && taskManagerPrefs.hideCompleted ? t('cplug.huddle.completed.all_hidden') : t('cplug.huddle.empty')}</p>
  {/if}

  
  {#snippet face(icon: string)}<Icon name={icon} size={FOOTER_ICON_PX} />{/snippet}
  <div class="hd-foot" data-task-manager-controls>
    <span class="hd-foot-left">
      {#if naming && byArea}
        <TaskManagerNewGroup target={groupTarget} onClose={() => (naming = false)} />
      {:else if confirmRemove && completed > 0 && bodyOptions.completedKeys}
        <span class="hd-done-ask" role="status" title={removeAsk} data-task-manager-remove-ask>{removeAsk}</span>
        <button type="button" class="oc-ibtn oc-ibtn--bare hd-key" onclick={() => (confirmRemove = false)} data-task-manager-remove-cancel
                aria-label={t('cplug.huddle.completed.cancel')} title={t('cplug.huddle.completed.cancel')}>{@render face('close')}</button>
        <button type="button" class="oc-ibtn oc-ibtn--bare hd-key hd-key--danger" onclick={() => void confirmRemoveCompleted()} data-task-manager-remove-confirm
                aria-label={t('cplug.huddle.completed.remove')} title={t('cplug.huddle.completed.remove')}>{@render face('sweep')}</button>
      {:else}
        {#if completed > 0 && bodyOptions.completedKeys}
          <button type="button" class="oc-ibtn oc-ibtn--bare hd-key hd-key--count" data-task-manager-remove-completed
                  aria-label={removeWords} title={removeWords}
                  onclick={() => (confirmRemove = true)}>{@render face('trash')}{completed}</button>
        {/if}
        {#if byArea}
          <button type="button" class="oc-ibtn oc-ibtn--bare hd-key" data-task-manager-new-group aria-label={t('cplug.huddle.group.new')}
                  title={t('cplug.huddle.group.new_title')} onclick={startGroup}>{@render face('folder-plus')}</button>
          <button type="button" class="oc-ibtn oc-ibtn--bare hd-key" data-task-manager-show-empty-groups aria-pressed={taskManagerPrefs.showEmptyGroups}
                  aria-label={emptyWords} title={emptyWords}
                  onclick={() => void setShowEmptyGroups(!taskManagerPrefs.showEmptyGroups)}>{@render face(taskManagerPrefs.showEmptyGroups ? 'folder-eye' : 'folder-eye-off')}</button>
        {/if}
      {/if}
    </span>
    <span class="hd-foot-right">
      {#if bodyOptions.completedKeys}
        <button type="button" class="oc-ibtn oc-ibtn--bare hd-key" data-task-manager-hide-completed="on" aria-pressed={taskManagerPrefs.hideCompleted}
                aria-label={t('cplug.huddle.completed.hide')} title={t(taskManagerPrefs.hideCompleted ? 'cplug.huddle.completed.shown_title' : 'cplug.huddle.completed.hide_title')}
                onclick={() => void setHideCompleted(!taskManagerPrefs.hideCompleted)}>{@render face(taskManagerPrefs.hideCompleted ? 'eye-check-off' : 'eye-check')}</button>
      {/if}
      {#if !bodyOptions.sendInAddRow}<TaskManagerSend />{/if}
    </span>
  </div>

  <form class="hd-add" class:hd-add--multi={multiline} onsubmit={(event) => { event.preventDefault(); void add(); }}>
    {#if pinnedList === null || pinnedAll}
    <select class="oc-field hd-add-target" use:baseField={'sm'} bind:value={huddle.addTarget} aria-label={t('cplug.huddle.add.target')}
            title={t('cplug.huddle.add.target')} data-task-manager-add-target>
      {#each targets as row (row.key)}<option value={row.key}>{groupName(row.key, row.name)}</option>{/each}
    </select>
    {/if}
    {#if multiline}
      <textarea class="oc-field hd-add-input" use:baseField={'sm'} rows={MULTILINE_ROWS} bind:value={draft} maxlength="40000" onkeydown={onAreaKey}
                placeholder={addPlaceholder} title={t('cplug.huddle.add.multi_keys_title')} aria-label={addPlaceholder} data-task-manager-add></textarea>
    {:else}
      <input class="oc-field hd-add-input" use:baseField={'sm'} type="text" bind:value={draft} maxlength="2000"
             placeholder={addPlaceholder} title={t('cplug.huddle.add.keys_title')} aria-label={addPlaceholder} data-task-manager-add />
    {/if}
    <button type="button" class="oc-ibtn oc-ibtn--bare hd-multi" aria-pressed={multiline} data-task-manager-multiline
            aria-label={t(multiline ? 'cplug.huddle.add.single' : 'cplug.huddle.add.multi')}
            title={t(multiline ? 'cplug.huddle.add.single' : 'cplug.huddle.add.multi')} onclick={toggleMultiline}><Icon name="hamburger" size={12} /></button>
    {#if bodyOptions.sendInAddRow}
      <TaskManagerSend compose={{ text: draft, add }} />
    {:else}
      <button type="submit" class="oc-btn oc-btn--sm" class:oc-btn--confirm={addLook !== 'idle'} onclick={(event) => { event.preventDefault(); void add(); }} data-task-manager-submit-look={addLook}
              disabled={addLook === 'idle'}>{t(addLook === 'sent' ? 'cplug.huddle.submit.sent' : 'cplug.huddle.add.button')}</button>
    {/if}
  </form>
  {#if popout}
    
    <div class="hd-edge" aria-hidden="true" data-task-manager-popout-foot></div>
  {/if}
  {/if}
  <TaskManagerScheduleEditor />
  <TaskManagerForkDialog />
  <TaskManagerArtifactDialog />
  <TaskManagerTickConfirm />
</div>

<style>
  @layer components {
    .hd {
      display: flex;
      flex-direction: column;
      flex: 1 1 auto;
      min-width: 0;
      min-height: 0;
      font-family: var(--font-mono);
    }

    .hd[data-popout='on'] {
      --hd-fs: var(--oc-fs-body);
      --hdt-max: min(45vh, 420px);
    }

    .hd-edge {
      flex: none;
      height: 14px;
      background: var(--oc-ground-titlerow);
      box-shadow: inset 0 1px 0 var(--oc-line-rule);
    }

    @media (pointer: fine) {
      .hd :global(:is(.oc-btn, .oc-check, .oc-field)) {
        min-height: 0;
      }

      .hd :global(.oc-ibtn) {
        width: var(--oc-ibtn-size, 20px);
        height: var(--oc-ibtn-size, 20px);
      }
    }

    .hd-bar {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--oc-space-1);
      padding: calc(var(--oc-space-1) + 2.5px) var(--oc-space-2);
      box-shadow: inset 0 -1px 0 var(--oc-line-rule);
    }

    .hd-pick-label {
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.1em;
      text-transform: uppercase;
    }

    .hd-pick,
    .hd-add-target {
      min-width: 0;
      height: 20px;
      padding: 0 22px 0 6px;
      background-position: right 6px center;
      font-size: var(--oc-fs-label);
      line-height: 18px;
    }

    .hd-pick {
      flex: 1 1 auto;
    }

    /*  hidden  */
    .hd-swarm {
      flex: 1 1 auto;
      min-height: 0;
      overflow-x: hidden;
      overflow-y: auto;
    }

    /* show empty groups */
    .hd-foot {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: var(--oc-space-1);
      padding: var(--oc-space-1) var(--oc-space-2);
      box-shadow: inset 0 1px 0 var(--oc-line-rule);
    }

    .hd-foot-left,
    .hd-foot-right {
      display: flex;
      align-items: center;
      gap: var(--oc-space-1);
      min-width: 0;
    }

    .hd-foot-left {
      flex: 1 1 auto;
    }

    .hd-foot-right {
      flex: none;
      margin-left: auto;
    }

    .hd-foot :global(.hd-key) {
      --oc-ibtn-size: 24px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      position: relative;
      flex: none;
      box-sizing: border-box;
      gap: 4px;
      height: 24px;
      font-family: var(--font-mono);
      font-size: var(--oc-fs-label);
      line-height: 1;
      white-space: nowrap;
    }

    .hd-foot :global(.hd-key svg) {
      display: block;
      flex: none;
    }

    .hd-foot :global(.hd-key[aria-pressed='true']) {
      color: var(--oc-orange);
    }

    .hd-foot :global(.hd-key--danger) {
      --_bd: var(--oc-coral);
      border-color: var(--oc-coral);
      color: var(--oc-coral);
    }

    .hd-foot :global(.hd-key--act) {
      --_bd: var(--oc-orange);
      border-color: var(--oc-orange);
      background: var(--oc-orange-tint);
      color: var(--oc-text-bright);
    }

    .hd-foot :global(.hd-key--act:hover:not(:disabled)) {
      border-color: var(--oc-orange-bright);
      background: var(--oc-orange-dim);
      color: var(--oc-text-bright);
    }

    .hd-foot .hd-key--count {
      width: auto;
      min-width: var(--oc-ibtn-size, 24px);
      gap: 4px;
      padding: 0 5px;
      border-color: var(--oc-line-rule);
      --_bd: var(--oc-line-rule);
      border-radius: 2px;
      color: var(--oc-text-secondary);
      font-variant-numeric: tabular-nums;
    }

    .hd-foot .hd-key--count:hover {
      border-color: var(--oc-coral);
      color: var(--oc-coral);
    }

    @media (max-width: 1023px) and (pointer: coarse) {
      .hd-foot .hd-key--count {
        min-width: var(--oc-tap, 44px);
      }
    }

    .hd-done-ask {
      flex: 1 1 auto;
      min-width: 0;
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-micro);
      line-height: 1.3;
      overflow-wrap: anywhere;
    }

    .hd-notice {
      margin: 0;
      padding: var(--oc-space-1) var(--oc-space-2);
      color: var(--oc-cyan);
      font-size: var(--oc-fs-micro);
      box-shadow: inset 0 -1px 0 var(--oc-line-faint);
    }

    button.hd-notice {
      display: block;
      width: 100%;
      border: 0;
      background: none;
      font-family: inherit;
      text-align: left;
      cursor: pointer;
    }

    .hd-scroll {
      flex: 1 1 auto;
      min-height: 0;
      overflow-y: auto;
      overflow-anchor: none;
      container: hdb / inline-size;
    }

    @container hdb (max-width: 439px) {
      .hd-scroll > :global(*) {
        --hd-phead-h: 52px;
      }
    }

    .hd-scroll--stack {
      display: flex;
      flex-direction: column;
      overflow-y: hidden;
    }

    .hd-scroll > .hd-block + :global(h2) {
      box-shadow: inset 3px 0 0 var(--_project, var(--oc-line-rule)), inset 0 -1px 0 var(--oc-line-rule), inset 0 1px 0 var(--oc-line-rule);
    }

    .hd-scroll--stack > .hd-block--open {
      overflow-anchor: none;
      flex: 1 1 0;
      min-height: 0;
      overflow-y: auto;
    }

    .hd-block :global(:is([data-huddle-item], [data-task-manager-level='status'], [data-task-manager-level='area'], [data-task-manager-level='sub'], [data-task-manager-group-empty]))::before {
      content: '';
      position: absolute;
      inset: 0 auto 0 0;
      width: 3px;
      background: var(--hd-project, var(--oc-text-secondary));
      pointer-events: none;
    }

    .hd-add-target {
      flex: 0 1 38%;
    }
    .hd:not([data-popout='on']) .hd-add-target { max-width: 88px; }

    .hd-empty {
      flex: 1 1 auto;
      margin: var(--oc-space-3) var(--oc-space-2);
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-label);
    }

    /* padding */
    .hd-add {
      display: flex;
      align-items: center;
      gap: var(--oc-space-1);
      padding: var(--oc-space-2) var(--oc-space-2) var(--oc-space-3);
      background: var(--oc-ground-titlerow);
      box-shadow: inset 0 1px 0 var(--oc-line-rule);
    }

    .hd-add--multi {
      align-items: flex-end;
    }

    .hd-add-input {
      flex: 1 1 auto;
      height: 20px;
      padding: 0 6px;
      font-size: var(--oc-fs-label);
      line-height: 18px;
    }

    textarea.hd-add-input {
      height: auto;
      padding: 2px 6px;
      line-height: 1.4;
    }

    .hd-multi { --oc-ibtn-size: 20px; }

    .hd-multi[aria-pressed='true'] { color: var(--oc-orange); }
  }
</style>
