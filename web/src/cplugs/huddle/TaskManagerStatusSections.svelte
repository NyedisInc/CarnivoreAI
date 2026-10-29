<script lang="ts">
  /* a fold chevron */
  import { getContext } from 'svelte';
  import { BODY_OPTIONS, DEFAULT_BODY_OPTIONS, type BodyOptions } from './task-manager-body-options';
  import { FoldChevron, Icon } from '../sdk/ui';
  import { t } from '../sdk';
  import { reorderList } from './huddle.svelte';
  import { doneLeft, doneLoading, hasMoreDone, holdDone, loadMoreDone } from './task-manager-done.svelte';
  import { viewKey } from './task-manager-view';
  import { openScheduleEditor } from './task-manager-schedule-editor.svelte';
  import { setItemGroup } from './task-manager-groups.svelte';
  import { AGGREGATE, dropIndex, type HuddleItem, type TaskManagerItemGroup } from './huddle-model';
  import {
    SECTION_ICON, SECTION_ICON_COLOR, sectionKey, sectionReorder, statusSections, type TaskManagerSectionKey, type StatusSection,
  } from './task-manager-status-sections';
  import { isFolded, setSectionFolded } from './task-manager-status-folds.svelte';
  import { cascadeCue, foldAll, keepShiftOffSelection, underStatusSection } from './task-manager-fold-cascade';
  import { beginRowDrag, type AreaHit } from './task-manager-drag-session';
  import TaskManagerEmptyGroup from './TaskManagerEmptyGroup.svelte';
  import './task-manager-tree.css';
  import TaskManagerRow from './TaskManagerRow.svelte';
  import TaskManagerSubHead from './TaskManagerSubHead.svelte';
  import TaskManagerTail from './TaskManagerTail.svelte';
  import { kindsPresent, marksToBadges } from './task-manager-tail-slots';
  import { waitingMarks } from './task-manager-waiting';
  import { areaDropIndex, sectionAreas, type SectionArea } from './task-manager-status-areas';
  import { sectionFoldKey, statusSubFoldKey } from './task-manager-status-folds.svelte';

  const options: Readonly<BodyOptions> = getContext<BodyOptions | undefined>(BODY_OPTIONS) ?? DEFAULT_BODY_OPTIONS;

  let { list, items, groups = [], hide = false, lines = 1, bare = false, doneTotal = 0 }: {
    list: string;
    items: HuddleItem[];
    groups?: TaskManagerItemGroup[];
    hide?: boolean;
    lines?: 1 | 2;
    bare?: boolean;
    doneTotal?: number;
  } = $props();
  const view = viewKey();

  let root = $state<HTMLElement | null>(null);
  let drag = $state<{
    key: TaskManagerSectionKey; area: number | null; from: number; toArea: number | null; to: number; over: AreaHit | null; out: boolean;
  } | null>(null);

  const sections = $derived.by(() => {
    const drawn = statusSections(items, hide).map((section) => ({
      section, ...sectionAreas(section, groups, (key, area) => isFolded(statusSubFoldKey(area, key, list))),
    }));
    if (doneTotal > 0 && !hide && !bare && !drawn.some((entry) => entry.section.key === 'done')) {
      drawn.push({ section: { key: 'done', all: [], items: [] }, subs: [], headed: false, drawn: [] });
    }
    return drawn;
  });
  const wantDone = $derived(!bare && !hide && doneTotal > 0 && !isFolded(sectionFoldKey(list, 'done')));
  const holdKey = $derived(wantDone ? list : null);
  $effect(() => {
    const key = holdKey;
    return key === null ? undefined : holdDone(key);
  });
  const countOf = (section: StatusSection): number => (section.key === 'done' ? Math.max(doneTotal, section.items.length) : section.items.length);
  const emptyAreas = $derived.by((): { id: number | null; name: string }[] => {
    if (!groups.length) return [];
    const shown = new Set(sections.flatMap((entry) => entry.subs.map((sub) => sub.area)));
    return [...groups].sort((a, b) => a.position - b.position || a.id - b.id).map((g) => ({ id: g.id as number | null, name: g.name }))
      .concat([{ id: null, name: t('cplug.huddle.group.none') }]).filter((a) => !shown.has(a.id));
  });

  const sectionBadges = (entry: (typeof sections)[number]) =>
    isFolded(sectionFoldKey(list, entry.section.key)) ? marksToBadges(waitingMarks(entry.section.items, ['question'])) : [];
  const sectionKinds = $derived(kindsPresent(sections.map(sectionBadges)));
  const subKinds = $derived(kindsPresent(sections.flatMap((entry) => (entry.headed ? entry.subs : []).map((sub) => (sub.folded ? marksToBadges(waitingMarks(sub.items, ['question'])) : [])))));

  const emptyGroups = $derived(
    emptyAreas.flatMap((a) => groups.filter((g) => g.id === a.id)),
  );

  function rowsBox(sub: SectionArea): { top: number; bottom: number } | null {
    if (!root) return null;
    const rows = [...root.querySelectorAll<HTMLElement>(`[data-task-manager-status-section="${sub.key}"] [data-huddle-item]`)]
      .slice(sub.start, sub.start + sub.items.length);
    const first = rows[0]?.getBoundingClientRect();
    const last = rows[rows.length - 1]?.getBoundingClientRect();
    return first && last ? { top: first.top, bottom: last.bottom } : null;
  }

  function middles(sub: SectionArea): number[] {
    if (!root) return [];
    const rows = [...root.querySelectorAll<HTMLElement>(`[data-task-manager-status-section="${sub.key}"] [data-huddle-item]`)];
    return rows.slice(sub.start, sub.start + sub.items.length).map((row) => {
      const r = row.getBoundingClientRect();
      return r.top + r.height / 2;
    });
  }

  function subAt(key: TaskManagerSectionKey, y: number): SectionArea | null {
    const entry = sections.find((e) => e.section.key === key);
    for (const sub of entry?.subs ?? []) {
      if (sub.folded) continue;
      const box = rowsBox(sub);
      if (box && y >= box.top && y < box.bottom) return sub;
    }
    return null;
  }

  function land(section: StatusSection, from: number, to: number): Promise<boolean> {
    if (from === to) return Promise.resolve(true);
    return reorderList(sectionReorder(items, section, from, to), list);
  }

  function onGripDown(event: PointerEvent, section: SectionArea, index: number): void {
    if (event.button !== 0) return;
    event.preventDefault();
    drag = { key: section.key, area: section.area, from: index, toArea: section.area, to: index, over: null, out: false };
    const moved = section.items[index];
    beginRowDrag(event, root, {
      onMove: (y, _x, area) => {
        if (!drag) return;
        const sub = area ? null : subAt(section.key, y);
        const own = sub !== null && sub.area === section.area;
        drag = { ...drag, toArea: sub ? sub.area : section.area, to: sub ? dropIndex(middles(sub), y, own ? index : -1) : index,
          over: area, out: !area && !sub };
      },
      onEnd: (dropped, area) => {
        const done = drag;
        drag = null;
        if (!dropped || !done) return;
        if (area) {
          if (moved && (moved.group ?? null) !== area.id) void setItemGroup(moved, area.id);
          return;
        }
        if (done.out) return;
        if (done.toArea === section.area) {
          void land(section, done.from, done.to);
          return;
        }
        const target = sections.find((e) => e.section.key === section.key)?.subs.find((s) => s.area === done.toArea);
        if (moved && target) {
          void setItemGroup(moved, done.toArea, areaDropIndex(items, groups, moved.id, done.toArea, target.items.map((i) => i.id), done.to));
        }
      },
    });
  }

  async function onStep(section: SectionArea, index: number, delta: number): Promise<void> {
    await land(section, index, index + delta);
    root?.querySelectorAll<HTMLElement>(`[data-task-manager-status-section="${section.key}"] [data-task-manager-grip]`)[section.start + index + delta]?.focus();
  }

  function lineAt(key: TaskManagerSectionKey, area: number | null): number | null {
    if (!drag || drag.over || drag.out || drag.key !== key || drag.toArea !== area) return null;
    if (drag.area !== area) return drag.to;
    if (drag.to === drag.from) return null;
    return drag.to < drag.from ? drag.to : drag.to + 1;
  }
</script>

<div bind:this={root} data-task-manager-status-list={list}>
  {#each sections as entry (entry.section.key)}
    {@const section = entry.section}
    {@const sectionFold = sectionFoldKey(list, section.key)}
    {@const folded = isFolded(sectionFold)}
    {@const name = t(sectionKey(section.key))}
    
    <div class="hss-section">
    <div class="hss-head" data-task-manager-level="status" data-task-manager-status-head={section.key} data-folded={folded ? 'on' : undefined}>
      <button type="button" class="hss-fold" aria-expanded={!folded} data-task-manager-status-fold={section.key} {@attach cascadeCue()} onmousedown={keepShiftOffSelection}
              onclick={(event) => (event.shiftKey ? foldAll({ keys: [sectionFold, ...underStatusSection(list, section, groups)], groups: [] }, !folded) : setSectionFolded(sectionFold, !folded))}>
        <FoldChevron />
        <span class="hss-mark" style:--_mark={SECTION_ICON_COLOR[section.key]} data-task-manager-section-icon={SECTION_ICON[section.key]} aria-hidden="true"><Icon name={SECTION_ICON[section.key]} size={12} strokeWidth={1.75} /></span>
        <span class="hss-name">{name}</span>
        <span class="hss-count" data-task-manager-status-count={section.key}>{countOf(section)}</span>
      </button>
      {#if section.key === 'scheduled'}{@render addSchedule()}{/if}
      <TaskManagerTail scope={section.key} badges={sectionBadges(entry)} kinds={sectionKinds} />
    </div>
    <ol class="hss-list" aria-label={name} data-task-manager-status-section={section.key}>
      {#if !folded}
        {#each entry.subs as sub (sub.area ?? 'none')}
          {@const line = lineAt(section.key, sub.area)}
          {#if entry.headed}
            {@const fold = statusSubFoldKey(sub.area, section.key, list)}
            {@const label = t('cplug.huddle.section.of_area', { name, area: sub.name ?? t('cplug.huddle.group.none') })}
            <TaskManagerSubHead {fold} status={section.key} name={label} folded={sub.folded} count={sub.items.length}
                           marks={sub.folded ? waitingMarks(sub.items, ['question']) : []} kinds={subKinds}
                           dropArea={drag ? String(sub.area ?? 'none') : undefined}
                           over={drag !== null && drag.over !== null && drag.over.id === sub.area && drag.area !== sub.area}
                           onToggle={() => setSectionFolded(fold, !sub.folded)} />
          {/if}
          {#if !sub.folded}
            {#each sub.items as item, index (item.id)}
              {#if line === index}<li class="hss-drop" aria-hidden="true"></li>{/if}
              <TaskManagerRow {item} {index} count={sub.items.length} {lines}
                         dragging={drag !== null && drag.key === section.key && drag.area === sub.area && drag.from === index}
                         onGripDown={(event, i) => onGripDown(event, sub, i)} onStep={(i, delta) => onStep(sub, i, delta)} />
            {/each}
            {#if line !== null && line >= sub.items.length}<li class="hss-drop" aria-hidden="true"></li>{/if}
          {/if}
        {/each}
        {#if section.key === 'done' && (hasMoreDone(list) || doneLoading(list))}
          <li class="hss-more">
            <button type="button" class="oc-btn oc-btn--sm oc-btn--ghost" data-task-manager-done-more={list} disabled={doneLoading(list)} onclick={() => void loadMoreDone(list)}>
              {doneLoading(list) ? t('cplug.huddle.done.loading') : t('cplug.huddle.done.more', { count: doneLeft(list) })}
            </button>
          </li>
        {/if}
      {/if}
    </ol>
    </div>
  {/each}
  
  {#if options.scheduleBlocks && !sections.some((e) => e.section.key === 'scheduled') && (bare || view() !== AGGREGATE)}
    <div class="hss-head" data-task-manager-level="status" data-task-manager-schedule-strip={list}>
      <span class="hss-fold"><span class="hss-name">{t(sectionKey('scheduled'))}</span></span>
      {@render addSchedule()}
      <TaskManagerTail scope="schedule-{list}" />
    </div>
    <p class="hss-none" data-task-manager-schedule-none={list}>{t('cplug.huddle.schedule.none')}</p>
  {/if}
  {#if !drag}
    {#each emptyGroups as group (group.id)}<TaskManagerEmptyGroup {group} />{/each}
  {/if}
  {#if drag && emptyAreas.length}
    {#each emptyAreas as area (area.id ?? 'none')}
      <div class="hss-head hss-head--empty" class:hss-head--over={drag.over !== null && drag.over.id === area.id && drag.area !== area.id}
           data-task-manager-area-drop={area.id ?? 'none'}>
        <span class="hss-name">{area.name}</span>
      </div>
    {/each}
  {/if}
</div>

{#snippet addSchedule()}
  <button type="button" class="oc-ibtn oc-ibtn--bare hss-add" data-task-manager-schedule-add={list} aria-label={t('cplug.huddle.schedule.add')}
          title={t('cplug.huddle.schedule.add')} onclick={() => openScheduleEditor(list)}>
    <Icon name="plus" size={12} />
  </button>
{/snippet}

<style>
  @layer components {
    .hss-section {
      min-width: 0;
    }

    .hss-list {
      list-style: none;
      margin: 0;
      padding: 0;
    }
    .hss-more {
      padding: var(--oc-space-2) var(--oc-space-2) var(--oc-space-2) calc(var(--oc-space-6) + var(--oc-space-1) / 2);
      box-shadow: inset 0 -1px 0 var(--oc-line-faint);
    }

    .hss-drop {
      position: relative;
      z-index: 1;
      height: 0;
      box-shadow: 0 0 0 1px var(--oc-orange);
    }

    .hss-drop::before {
      content: '';
      position: absolute;
      left: 0;
      top: -1px;
      width: 16px;
      height: 3px;
      background: var(--oc-orange);
    }

    .hss-head {
      position: sticky;
      top: var(--hd-stick-top, 0px);
      z-index: 2;
      display: flex;
      align-items: center;
      min-height: 22px;
      padding: 0 var(--oc-space-2) 0 calc(4px + var(--hd-step, 0px));
      background: var(--oc-ground-titlerow);
      box-shadow: inset 0 -1px 0 var(--oc-line-rule), inset 0 1px 0 var(--oc-line-faint);
    }

    .hss-head--empty {
      position: relative;
      padding-left: 14px;
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-micro);
      letter-spacing: var(--oc-tracking-label, 0.6px);
      text-transform: uppercase;
    }

    .hss-head--over {
      background: var(--oc-orange-tint);
      color: var(--oc-orange);
      box-shadow: inset 0 0 0 1px var(--oc-orange);
    }

    .hss-fold {
      display: inline-flex;
      flex: 0 1 auto;
      align-items: center;
      gap: 6px;
      min-width: 0;
      padding: 2px 0;
      border: 1px solid transparent;
      background: none;
      color: var(--oc-text-secondary);
      font: inherit;
      font-size: var(--oc-fs-micro);
      letter-spacing: var(--oc-tracking-label, 0.6px);
      text-transform: uppercase;
      text-align: left;
      cursor: pointer;
    }

    .hss-add {
      --oc-ibtn-size: 18px;
      flex: none;
      margin-inline-start: var(--oc-space-2);
    }

    .hss-none {
      margin: 0;
      padding: var(--oc-space-2) var(--oc-space-2) var(--oc-space-2) 34px;
      color: var(--oc-text-dim);
      font-size: var(--oc-fs-micro);
      box-shadow: inset 0 -1px 0 var(--oc-line-faint);
    }

    .hss-add:hover {
      color: var(--oc-text-bright);
    }

    .hss-fold:hover {
      color: var(--oc-text-bright);
    }

    .hss-mark {
      flex: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 12px;
      color: var(--_mark);
    }

    .hss-name {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .hss-count {
      color: var(--oc-text-muted);
      font-variant-numeric: tabular-nums;
      letter-spacing: 0;
    }
  }
</style>
