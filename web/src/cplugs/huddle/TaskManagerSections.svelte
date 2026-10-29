<script lang="ts">
  /* a fold chevron */
  import { FoldChevron, Icon } from '../sdk/ui';
  import { baseField } from './task-manager-base-field';
  import { t } from '../sdk';
  import { reorderList } from './huddle.svelte';
  import { moveGroup, removeGroup, renameGroup, setFolded, setItemGroup } from './task-manager-groups.svelte';
  import {
    dropTarget, sectionIndex, sectionsOf, visibleItems, type HuddleItem, type TaskManagerItemGroup, type SectionBox,
  } from './huddle-model';
  import {
    areaSubsections, clampInto, sectionKey, sectionReorder, subsectionAt,
  } from './task-manager-status-sections';
  import { isFolded, setSectionFolded, subFoldKey } from './task-manager-status-folds.svelte';
  import { cascadeCue, foldAll, keepShiftOffSelection, underArea } from './task-manager-fold-cascade';
  import { beginRowDrag, type AreaHit } from './task-manager-drag-session';
  import './task-manager-tree.css';
  import TaskManagerRow from './TaskManagerRow.svelte';
  import TaskManagerSubHead from './TaskManagerSubHead.svelte';
  import TaskManagerTail from './TaskManagerTail.svelte';
  import { kindsPresent, marksToBadges } from './task-manager-tail-slots';
  import { waitingMarks } from './task-manager-waiting';

  let { list, items, groups = [], hide = false, lines = 1 }: {
    list: string;
    items: HuddleItem[];
    groups?: TaskManagerItemGroup[];
    hide?: boolean;
    lines?: 1 | 2;
  } = $props();

  type Spot = { key: number | null; index: number };

  let root = $state<HTMLElement | null>(null);
  let drag = $state<{ from: Spot; to: Spot; over: AreaHit | null; out: boolean } | null>(null);
  let renaming = $state<number | null>(null);
  let nameDraft = $state('');

  const sections = $derived(sectionsOf(items, groups).map((s) => {
    const key = s.group?.id ?? null;
    const { subs, drawn } = areaSubsections(s.items, hide, (k) => isFolded(subFoldKey(key, k)));
    return { ...s, key, all: s.items, items: drawn, subs, shown: subs.reduce((n, sub) => n + sub.items.length, 0) };
  }));
  const named = $derived(sections.filter((s) => s.group !== null));
  const areaMarks = (s: { all: HuddleItem[] }) => waitingMarks(visibleItems(s.all, hide));
  const groupKinds = $derived(kindsPresent(named.map((s) => (s.group?.folded ? marksToBadges(areaMarks(s)) : []))));
  const subKinds = $derived(kindsPresent(sections.flatMap((s) => (s.group?.folded ? [] : s.subs).map((sub) => (sub.folded ? marksToBadges(waitingMarks(sub.items, ['question'])) : [])))));

  function domKey(key: number | null): string {
    return key === null ? 'none' : String(key);
  }

  function boxes(): SectionBox[] {
    if (!root) return [];
    return [...root.querySelectorAll<HTMLElement>('[data-task-manager-section]')].map((el) => {
      const box = el.getBoundingClientRect();
      const middles = [...el.querySelectorAll<HTMLElement>('[data-huddle-item]')].map((row) => {
        const r = row.getBoundingClientRect();
        return r.top + r.height / 2;
      });
      const raw = el.dataset.taskManagerSection ?? 'none';
      return { key: raw === 'none' ? null : Number(raw), top: box.top, bottom: box.bottom, middles };
    });
  }

  function land(from: Spot, to: Spot): Promise<boolean> {
    const source = sections.find((s) => s.key === from.key);
    const target = sections.find((s) => s.key === to.key);
    const moved = source?.items[from.index];
    if (!source || !target || !moved) return Promise.resolve(true);
    if (from.key === to.key) {
      const sub = subsectionAt(source.subs, from.index);
      const at = sub ? clampInto(sub, to.index) : from.index;
      if (!sub || from.index === at) return Promise.resolve(true);
      return reorderList(sectionReorder(items, sub, from.index - sub.start, at - sub.start), list);
    }
    const at = sectionIndex(target.all.map((i) => i.id), target.items.map((i) => i.id), to.index);
    return setItemGroup(moved, to.key, at);
  }

  function inSections(y: number): boolean {
    return boxes().some((b) => y >= b.top && y < b.bottom);
  }

  function onGripDown(event: PointerEvent, key: number | null, index: number): void {
    if (event.button !== 0) return;
    event.preventDefault();
    const from = { key, index };
    const moved = sections.find((s) => s.key === key)?.items[index];
    drag = { from, to: from, over: null, out: false };
    beginRowDrag(event, root, {
      onMove: (y, _x, over) => {
        if (drag) drag = { from, to: clampSame(from, dropTarget(boxes(), y, from)), over, out: !over && !inSections(y) };
      },
      onEnd: (dropped, over) => {
        const done = drag;
        drag = null;
        if (!dropped || !done) return;
        if (over) {
          if (moved && (moved.group ?? null) !== over.id) void setItemGroup(moved, over.id);
          return;
        }
        if (!done.out) void land(done.from, done.to);
      },
    });
  }

  async function onStep(key: number | null, index: number, delta: number): Promise<void> {
    await land({ key, index }, { key, index: index + delta });
    root?.querySelectorAll<HTMLElement>(`[data-task-manager-section="${domKey(key)}"] [data-task-manager-grip]`)[index + delta]?.focus();
  }

  function clampSame(from: Spot, to: Spot): Spot {
    if (to.key !== from.key) return to;
    const sub = subsectionAt(sections.find((s) => s.key === from.key)?.subs ?? [], from.index);
    return sub ? { key: to.key, index: clampInto(sub, to.index) } : to;
  }

  function lineAt(key: number | null): number | null {
    if (!drag || drag.over || drag.out || drag.to.key !== key) return null;
    if (drag.from.key !== key) return drag.to.index;
    if (drag.to.index === drag.from.index) return null;
    return drag.to.index < drag.from.index ? drag.to.index : drag.to.index + 1;
  }

  function startRename(group: TaskManagerItemGroup): void {
    nameDraft = group.name;
    renaming = group.id;
  }

  async function commitRename(group: TaskManagerItemGroup): Promise<void> {
    if (renaming !== group.id) return;
    renaming = null;
    await renameGroup(group, nameDraft);
  }

  function onNameKey(event: KeyboardEvent, group: TaskManagerItemGroup): void {
    if (event.key === 'Enter') {
      event.preventDefault();
      void commitRename(group);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      renaming = null;
    }
  }
</script>

<div bind:this={root} data-task-manager-group={list}>
  {#each sections as section (domKey(section.key))}
    {@const group = section.group}
    {@const line = lineAt(section.key)}
    
    <div class="hds-section">
    {#if group}
      {@const place = named.findIndex((s) => s.key === group.id)}
      <div class="hds-head" data-task-manager-level="area" class:hds-head--target={drag && drag.from.key !== group.id && (drag.over?.id === group.id || (drag.to.key === group.id && !drag.out && (group.folded || !section.items.length)))}
           data-task-manager-area-drop={drag ? group.id : undefined} data-task-manager-section-head={group.id} data-folded={group.folded ? 'on' : undefined}>
        {#if renaming === group.id}
          <!-- svelte-ignore a11y_autofocus -->
          <input class="oc-field hds-rename" use:baseField type="text" maxlength="80" bind:value={nameDraft} autofocus
                 aria-label={t('cplug.huddle.group.rename_label', { name: group.name })} data-task-manager-group-rename-input={group.id}
                 onkeydown={(event) => onNameKey(event, group)} onblur={() => void commitRename(group)} />
        {:else}
          <button type="button" class="hds-fold" aria-expanded={!group.folded} data-task-manager-fold={group.id}
                  ondblclick={() => startRename(group)}
                  {@attach cascadeCue()} onmousedown={keepShiftOffSelection}
                  onclick={(event) => (event.shiftKey ? foldAll({ keys: underArea(group.id, section.all, hide), groups: [group] }, !group.folded) : void setFolded(group, !group.folded))}>
            <FoldChevron />
            <span class="hds-name">{group.name}</span>
            <span class="hds-count" data-task-manager-group-count={group.id}>{section.shown}</span>
          </button>
          <span class="hds-keys">
            <button type="button" class="oc-ibtn oc-ibtn--bare hds-key" data-task-manager-group-rename={group.id}
                    aria-label={t('cplug.huddle.group.rename', { name: group.name })}
                    onclick={() => startRename(group)}><Icon name="pencil" size={11} /></button>
            <button type="button" class="oc-ibtn oc-ibtn--bare hds-key" data-task-manager-group-up={group.id} disabled={place <= 0}
                    aria-label={t('cplug.huddle.group.up', { name: group.name })}
                    onclick={() => void moveGroup(group, place - 1)}><Icon name="chevron-up" size={11} /></button>
            <button type="button" class="oc-ibtn oc-ibtn--bare hds-key" data-task-manager-group-down={group.id} disabled={place >= named.length - 1}
                    aria-label={t('cplug.huddle.group.down', { name: group.name })}
                    onclick={() => void moveGroup(group, place + 1)}><Icon name="chevron-down" size={11} /></button>
            <button type="button" class="oc-ibtn oc-ibtn--bare hds-key hds-remove" data-task-manager-group-remove={group.id}
                    aria-label={t('cplug.huddle.group.remove', { name: group.name })} title={t('cplug.huddle.group.remove_title')}
                    onclick={() => void removeGroup(group)}><Icon name="close" size={11} /></button>
          </span>
          <TaskManagerTail scope={String(group.id)} badges={group.folded ? marksToBadges(areaMarks(section)) : []} kinds={groupKinds} />
        {/if}
      </div>
    {/if}
    <ol class="hd-list" class:hds-list--zone={drag !== null && !group && !section.items.length} aria-label={group ? group.name : t('cplug.huddle.list.items')}
        data-task-manager-section={domKey(section.key)}>
      {#if !group?.folded}
        {#each section.subs as sub (sub.key)}
          {@const fold = subFoldKey(section.key, sub.key)}
          {@const name = group ? t('cplug.huddle.section.in_area', { area: group.name, name: t(sectionKey(sub.key)) }) : t(sectionKey(sub.key))}
          <TaskManagerSubHead {fold} status={sub.key} {name} folded={sub.folded} count={sub.items.length}
                         marks={sub.folded ? waitingMarks(sub.items, ['question']) : []} kinds={subKinds}
                         onToggle={() => setSectionFolded(fold, !sub.folded)} />
          {#if !sub.folded}
            {#each sub.items as item, i (item.id)}
              {@const index = sub.start + i}
              {#if line === index}<li class="hd-drop" aria-hidden="true"></li>{/if}
              <TaskManagerRow {item} index={i} count={sub.items.length} {lines}
                         dragging={drag !== null && drag.from.key === section.key && drag.from.index === index}
                         onGripDown={(event) => onGripDown(event, section.key, index)} onStep={(_i, delta) => onStep(section.key, index, delta)} />
            {/each}
          {/if}
        {/each}
        {#if line !== null && line >= section.items.length && (section.items.length > 0 || !group)}<li class="hd-drop" aria-hidden="true"></li>{/if}
        {#if group && !section.shown}
          <li class="hds-empty" class:hds-empty--target={line !== null} data-task-manager-group-empty={group.id}>{t('cplug.huddle.group.empty')}</li>
        {/if}
      {/if}
    </ol>
    </div>
  {/each}
</div>

<style>
  @layer components {
    .hds-section {
      min-width: 0;
    }

    .hd-list {
      list-style: none;
      margin: 0;
      padding: 0;
    }

    .hds-list--zone {
      min-height: 10px;
    }

    .hd-drop {
      position: relative;
      z-index: 1;
      height: 0;
      box-shadow: 0 0 0 1px var(--oc-orange);
    }

    .hd-drop::before {
      content: '';
      position: absolute;
      left: 0;
      top: -1px;
      width: 16px;
      height: 3px;
      background: var(--oc-orange);
    }

    /* border: box-shadow */
    .hds-head {
      position: sticky;
      top: var(--hd-stick-top, 0px);
      z-index: 2;
      display: flex;
      align-items: center;
      gap: var(--oc-space-1);
      min-height: 22px;
      padding: 0 var(--oc-space-2) 0 calc(4px + var(--hd-step, 0px));
      background: var(--oc-ground-titlerow);
      box-shadow: inset 2px 0 0 var(--oc-line-frame), inset 0 -1px 0 var(--oc-line-rule), inset 0 1px 0 var(--oc-line-faint);
    }

    .hds-head--target {
      background: var(--oc-orange-tint);
      box-shadow: inset 0 0 0 1px var(--oc-orange);
    }

    .hds-fold {
      display: inline-flex;
      flex: 0 1 auto;
      align-items: center;
      gap: 6px;
      min-width: 0;
      padding: 2px 0;
      border: 1px solid transparent;
      background: none;
      color: var(--oc-text-primary);
      font: inherit;
      font-size: var(--oc-fs-label);
      font-weight: 600;
      letter-spacing: 0.2px;
      text-align: left;
      cursor: pointer;
    }

    .hds-fold:hover {
      color: var(--oc-text-bright);
    }

    .hds-name {
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

    .hds-keys {
      display: inline-flex;
      flex: none;
      margin-left: auto;
      align-items: center;
      gap: 2px;
      opacity: 0;
    }

    .hds-head:hover .hds-keys,
    .hds-head:focus-within .hds-keys {
      opacity: 1;
    }

    .hds-key {
      --oc-ibtn-size: 18px;
    }

    .hds-remove:hover {
      color: var(--oc-coral);
    }

    .hds-rename {
      flex: 1 1 auto;
      min-width: 0;
      height: 18px;
      padding: 0 6px;
      font-size: var(--oc-fs-label);
      line-height: 16px;
    }

    .hds-empty {
      position: relative;
      padding: 6px var(--oc-space-2) 6px 34px;
      color: var(--oc-text-dim);
      font-size: var(--oc-fs-micro);
      box-shadow: inset 0 -1px 0 var(--oc-line-faint);
    }

    .hds-empty--target {
      background: var(--oc-orange-tint);
      color: var(--oc-orange);
      box-shadow: inset 0 0 0 1px var(--oc-orange);
    }

    @media (hover: none) {
      .hds-keys {
        opacity: 1;
      }
    }
  }
</style>
