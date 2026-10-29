<script lang="ts" module>
import type { WidgetManifest } from '../widgets/types';
import type { AgentMarkFacts } from '../../lib/sessions/agent-marks';

export interface TabItem {
  id: string;
  name: string;
  family: string | null;
  tint?: string | null;
  face?: AgentMarkFacts;
  workflow?: boolean;
  glyph?: string;
  badge?: { manifest: WidgetManifest; global?: boolean } | null;
  agent?: Record<string, unknown> | null;
  nameStyle?: string;
}

export interface TabStripWords {
  list: string;
  close: (name: string) => string;
  confirm: (name: string) => string;
  add: string;
}

export const LONG_PRESS_MS = 500;
</script>

<script lang="ts">
  /**
   * One terminal component's tab strip: a tab per session.
   *
   * Description:(issue #452): on the terminal page the top
   *   bar row IS each component's tab strip.
   *
   *   A TAB READS, LEFT TO RIGHT (#514): the component's icon, the session's
   *   status light (THE ONE `StatusLed`, never a copy), the provider mark
   *   only when the session has a provider (the same mark the agents drawer
   *   draws, `client/js/agent-family-icon.js`), the name, and the "x".
   *
   *   THE ACTIVE TAB JOINS THE ROW UNDER IT (#514): it wears the title row's
   *   own ground, so tab and header read as one piece, while the rest of the
   *   strip sits on a darker mix of that same ground. Every colour is a theme
   *   token or a `color-mix` of one, so the contrast follows any theme.
   *
   *   CLICKING A TAB CHANGES THE VIEW AND NOTHING ELSE. It calls `onSelect`;
   *   the owning cell swaps which pane is visible. The grid, the URL and the
   *   page's own session stay exactly where they were. A drawer click is
   *   still the thing that navigates.
   *
   *   THE WAI-ARIA TABS PATTERN: a `tablist` of `tab`s, `aria-selected` on the
   *   one showing, a roving tabindex so the strip is one Tab stop, and the
   *   arrow keys, Home and End moving between tabs. Selection follows focus,
   *   because switching is cheap: every tab's terminal stays connected.
   *
   *   THE DIMMED "+" FOLLOWS THE LAST TAB (#453), outside the tablist because
   *   it is a menu button, not a tab: it opens the component's "+" tab menu,
   *   which the owning cell draws. It is drawn as a tab of its own, set off
   *   from the last tab by a gap (#514).
   *
   *   CLOSE AND KILL (#454). Each tab's "x" CLOSES THE TAB ONLY (`onClose`):
   *   the session keeps running. Holding Shift, or a 500 ms long-press on a
   *   touch screen, turns the "x" into a skull, and the skull KILLS the
   *   session (`onKill`, which confirms first through the one existing kill
   *   path). The "x" is outside the roving tab order; Delete on a focused tab
   *   closes it, Shift+Delete kills.
   *
   *   TINT AND OVERFLOW (#454). An inactive tab's background is its session's
   *   theme accent mixed into the strip ground, kept weaker than the step
   *   between the strip and the active tab (#514). Tabs shrink to a minimum width
   *   with the title truncated, then the row scrolls sideways with its edges
   *   faded where more tabs are hidden.
   *
   *   DRAG (#455). A press on a tab hands the pointer to `onDragStart`
   *   (`engine/tab-drag.ts`), which lifts the tab only past its threshold, so
   *   a click is still a click. While a drag runs, the carried tab dims and
   *   the strip it would land in draws a mark at `dropIndex`, an index that
   *   counts the tabs WITHOUT the carried one.
   */
  import Icon from '../ui/Icon.svelte';
  import AgentTabMarks from '../../lib/sidebar-shell/AgentTabMarks.svelte';
  import SessionFace from '../../lib/sessions/SessionFace.svelte';
  import { NOT_MEASURED } from '../../lib/sessions/agent-marks';
  import { INNER_LABELS } from '../../lib/led';
  import { t } from '../../lib/i18n/index.svelte';
  import { confirmOk, onMiddleClick, suppressMiddleAutoscroll } from '../../lib/confirm-ok/confirm-ok';
  import { glyphSvg } from '../../../../client/js/icons/glyphs.js';
  import { shiftKey, watchShift } from '../lib/shift-held.svelte';
  import { revealTabHorizontally } from './tab-strip-scroll';
  import ZoneBadge from '../../lib/zone-shell/ZoneBadge.svelte';
  import { nextKey } from '../../lib/zone-shell/key-nav';
  import TabKey, { keyFace } from '../../lib/zone-shell/TabKey.svelte';

  let {
    items,
    active,
    onSelect,
    onNew,
    newOpen = false,
    onClose,
    onKill,
    group,
    dragging = null,
    dropIndex = null,
    onDragStart,
    touch = false,
    onIconClick,
    onTabMenu,
    menuOpen = false,
    menuLabel = t('opscenter.tabs.options'),
    icons = true,
    follow = true,
    words = null,
  }: {
    items: TabItem[];
    active: string;
    onSelect: (id: string) => void;
    onClose?: (id: string) => void;
    onKill?: (id: string) => void;
    onNew?: (button: HTMLElement) => void;
    newOpen?: boolean;
    group?: string;
    dragging?: string | null;
    dropIndex?: number | null;
    onDragStart?: (button: HTMLElement, event: PointerEvent, id: string) => void;
    touch?: boolean;
    onIconClick?: (button: HTMLElement) => void;
    onTabMenu?: (id: string, anchor: HTMLElement, point: { x: number; y: number } | null) => boolean;
    menuOpen?: boolean;
    menuLabel?: string;
    icons?: boolean;
    follow?: boolean;
    words?: TabStripWords | null;
  } = $props();

  const said = $derived<TabStripWords>(words ?? {
    list: t('opscenter.tabs.list'),
    close: (name) => t('opscenter.tabs.close', { name }),
    confirm: (name) => t('opscenter.tabs.close_confirm.message', { name }),
    add: t('opscenter.tabs.new'),
  });

  const counted = $derived(items.filter((item) => item.id !== dragging));

  function markAt(id: string): 'before' | 'after' | null {
    if (dropIndex === null) return null;
    if (counted[dropIndex]?.id === id) return 'before';
    return dropIndex === counted.length && counted[counted.length - 1]?.id === id ? 'after' : null;
  }

  let buttons = $state<Record<string, HTMLElement | null>>({});

  $effect(() => watchShift());

  let armed = $state<string | null>(null);
  let pressTimer: ReturnType<typeof setTimeout> | null = null;
  let swallowClick = false;

  function cancelPress(): void {
    if (pressTimer !== null) clearTimeout(pressTimer);
    pressTimer = null;
  }

  function onPressStart(event: PointerEvent, id: string): void {
    if (event.pointerType === 'mouse') return;
    cancelPress();
    pressTimer = setTimeout(() => {
      pressTimer = null;
      armed = id;
      swallowClick = true;
    }, LONG_PRESS_MS);
  }

  function onEnd(event: MouseEvent, id: string): void {
    event.stopPropagation();
    cancelPress();
    if (swallowClick) {
      swallowClick = false;
      return;
    }
    const kill = shiftKey.held || event.shiftKey || armed === id;
    armed = null;
    if (kill) onKill?.(id);
    else onClose?.(id);
  }

  async function confirmClose(id: string, name: string): Promise<void> {
    const ok = await confirmOk({
      title: t('opscenter.tabs.close_confirm.title'),
      message: said.confirm(name),
    });
    if (ok) onClose?.(id);
  }

  $effect(() => {
    if (armed === null) return;
    const disarm = (event: PointerEvent): void => {
      if (!(event.target as Element | null)?.closest?.('.oc-tab-x')) armed = null;
    };
    globalThis.addEventListener('pointerdown', disarm, true);
    return () => globalThis.removeEventListener('pointerdown', disarm, true);
  });

  let scroller = $state<HTMLElement | null>(null);
  let fadeStart = $state(false);
  let fadeEnd = $state(false);

  function measureFade(): void {
    const el = scroller;
    if (!el) return;
    fadeStart = el.scrollLeft > 1;
    fadeEnd = el.scrollLeft + el.clientWidth < el.scrollWidth - 1;
  }

  $effect(() => {
    const el = scroller;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measureFade);
    observer.observe(el);
    return () => observer.disconnect();
  });

  $effect(() => {
    void items.length;
    if (scroller && buttons[active]) revealTabHorizontally(scroller, buttons[active]);
    measureFade();
  });

  function safeTint(tint: string | null | undefined): string | null {
    return tint && /^#[0-9a-f]{3,8}$/i.test(tint) ? tint : null;
  }

  function markFor(family: string | null): string | null {
    const icon = (globalThis as {
      AgentFamilyIcon?: { svg(f: string | null, size: number): string; normalize(f: string | null): string };
    }).AgentFamilyIcon;
    if (!icon) return null;
    const known = icon.normalize(family);
    return known === 'unknown' || known === 'shell' ? null : icon.svg(family, 14);
  }

  function iconFor(family: string | null): string {
    const icon = (globalThis as { AgentFamilyIcon?: { normalize(f: string | null): string } }).AgentFamilyIcon;
    const known = icon ? icon.normalize(family) : family;
    return known === 'shell' ? 'terminal' : 'bot';
  }

  function onTabContextMenu(event: MouseEvent, id: string): void {
    if (event.defaultPrevented || !onTabMenu) return;
    const anchor = buttons[id];
    if (!anchor) return;
    if (onTabMenu(id, anchor, { x: event.clientX, y: event.clientY })) event.preventDefault();
  }

  function onKey(event: KeyboardEvent, index: number): void {
    if (event.key === 'Delete' && (onClose || onKill)) {
      event.preventDefault();
      const id = items[index]?.id;
      if (!id) return;
      if (event.shiftKey) onKill?.(id);
      else onClose?.(id);
      return;
    }
    const id = nextKey(event.key, items.map((item) => item.id), items[index]?.id ?? null, 'x', true);
    if (id === null) return;
    event.preventDefault();
    if (follow) onSelect(id);
    buttons[id]?.focus();
  }
</script>

<div class="oc-tabrow" class:oc-tabrow-touch={touch} data-tab-group={group}>
<div
  class="oc-tabs"
  class:oc-tabs-fade-start={fadeStart}
  class:oc-tabs-fade-end={fadeEnd}
  role="tablist"
  aria-label={said.list}
  bind:this={scroller}
  onscroll={measureFade}
>
  {#each items as item, index (item.id)}
    {@const selected = item.id === active}
    {@const mark = item.glyph ? null : markFor(item.family)}
    {@const cellIcon = item.glyph ?? iconFor(item.family)}
    {@const tint = safeTint(item.tint)}
    {@const skull = onKill !== undefined && (shiftKey.held || armed === item.id)}
    {@const drop = markAt(item.id)}
    <div
      class={[
        'oc-tabwrap',
        item.id === dragging && 'tw:opacity-40',
        drop === 'before' && 'tw:shadow-[inset_2px_0_0_var(--oc-orange)]',
        drop === 'after' && 'tw:shadow-[inset_-2px_0_0_var(--oc-orange)]',
      ]}
      data-drop-mark={drop}
      class:oc-tabwrap-active={selected}
      class:oc-tabwrap-tinted={tint !== null && !selected}
      style:--oc-tab-tint={tint}
      role="presentation"
      onmousedown={onClose ? suppressMiddleAutoscroll : undefined}
      onauxclick={onClose ? (event) => onMiddleClick(event, () => void confirmClose(item.id, item.name)) : undefined}
      oncontextmenu={(event) => onTabContextMenu(event, item.id)}
    >
      {#if icons}
      <button
        type="button"
        class="oc-tab-icon oc-tab-icon--action"
        data-corner=""
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        aria-label={menuLabel}
        title={menuLabel}
        onclick={(event) => onIconClick?.(event.currentTarget as HTMLElement)}
        oncontextmenu={(event) => {
          event.preventDefault();
          if (!menuOpen) onIconClick?.(event.currentTarget as HTMLElement);
        }}
      >
        
        {#if mark}<span class="oc-tab-mark" aria-hidden="true">{@html mark}</span>{:else if item.badge}<span class="oc-tab-badgehost"><Icon name={cellIcon} size={14} /><ZoneBadge manifest={item.badge.manifest} global={item.badge.global} /></span>{:else}<Icon name={cellIcon} size={14} />{/if}
      </button>
      {/if}
      <TabKey
        id={item.id}
        shape="tab"
        variant="strip"
        face={keyFace({ label: item.name })}
        labelStyle={item.nameStyle}
        iconPx={14}
        quiet
        state="selected"
        active={selected}
        tabbable={selected}
        attrs={{ 'data-tab': item.id }}
        bind:element={buttons[item.id]}
        onpress={onSelect}
        close={onClose
          ? {
              label: skull ? t('opscenter.tabs.kill', { name: item.name }) : said.close(item.name),
              run: (event) => onEnd(event, item.id),
              armed: skull,
              attrs: { 'data-tab-close': item.id, 'data-tab-action': skull ? 'kill' : 'close' },
              onpress: (event) => onPressStart(event, item.id),
              onrelease: cancelPress,
            }
          : undefined}
        ondragstart={(event, id) => onDragStart?.(event.currentTarget as HTMLElement, event, id)}
        onkey={(event) => onKey(event, index)}
        onmenu={onTabMenu ? (id, anchor, event) => onTabMenu(id, anchor, event instanceof MouseEvent ? { x: event.clientX, y: event.clientY } : null) : undefined}
      >
        {#snippet lead()}<SessionFace facts={item.face ?? { ...NOT_MEASURED, family: item.family }} />{#if item.agent}<AgentTabMarks info={item.agent} part="lead" />{/if}{/snippet}
        {#snippet tail()}{#if item.workflow}<span class="oc-tab-icon oc-tab-workflow" role="img" aria-label={t('sidebar.row.workflow_icon.title')} title={t('sidebar.row.workflow_icon.title')}>{@html glyphSvg('workflow', 13)}</span>{/if}{#if item.agent}<AgentTabMarks info={item.agent} part="tail" />{/if}{/snippet}
      </TabKey>
    </div>
  {/each}
</div>
{#if onNew}
  <TabKey
    id="new"
    variant="strip"
    face={keyFace({ ariaLabel: said.add, icon: 'plus' })}
    iconPx={14}
    quiet
    state={null}
    active={false}
    tabbable={null}
    classes="oc-tab-new"
    attrs={{ 'aria-haspopup': 'menu', 'aria-expanded': newOpen }}
    onpress={(_id, event) => onNew(event.currentTarget as HTMLElement)}
  />
{/if}
</div>

<style>
  @layer components {
    .oc-tabrow {
      --oc-tab-ground: var(--oc-ground-tab-inactive);
      display: flex;
      align-items: stretch;
      gap: 6px;
      min-width: 0;
      flex: 1 1 auto;
    }

    .oc-tabs {
      display: flex;
      align-items: stretch;
      gap: 1px;
      min-width: 0;
      flex: 0 1 auto;
      overflow-x: auto;
      overflow-y: hidden;
      scrollbar-width: none;
    }

    .oc-tabs::-webkit-scrollbar {
      display: none;
    }

    .oc-tabs-fade-start {
      mask-image: linear-gradient(to right, transparent, currentColor 24px);
    }

    .oc-tabs-fade-end {
      mask-image: linear-gradient(to left, transparent, currentColor 24px);
    }

    .oc-tabs-fade-start.oc-tabs-fade-end {
      mask-image: linear-gradient(to right, transparent, currentColor 24px, currentColor calc(100% - 24px), transparent);
    }

    .oc-tabwrap {
      display: flex;
      align-items: stretch;
      flex: 0 1 auto;
      min-width: 176px;
      max-width: 240px;
      background: var(--oc-tab-ground);
      border-top: 2px solid transparent;
      border-bottom: 1px solid var(--oc-line-rule);
    }

    .oc-tabwrap:hover {
      background: var(--oc-ground-tab-inactive-hover);
    }

    .oc-tabwrap-tinted {
      background: color-mix(in srgb, var(--oc-tab-tint) 5%, var(--oc-tab-ground));
    }

    .oc-tabwrap-tinted:hover {
      background: color-mix(in srgb, var(--oc-tab-tint) 8%, var(--oc-tab-ground));
    }

    .oc-tabwrap-active,
    .oc-tabwrap-active:hover {
      background: var(--oc-ground-titlerow);
      border-top-color: var(--oc-orange);
      border-bottom-color: transparent;
    }


    .oc-tabrow-touch .oc-tab-icon--action {
      width: 44px;
      padding: 0;
    }

    .oc-tab-icon {
      display: inline-flex;
      align-items: center;
      flex: 0 0 auto;
    }

    .oc-tab-badgehost {
      position: relative;
      display: inline-flex;
      align-items: center;
    }

    .oc-tab-icon--action {
      justify-content: center;
      padding: 0 3px 0 14px;
      background: none;
      border: 0;
      color: var(--oc-text-dim);
      cursor: pointer;
    }

    .oc-tabwrap:hover .oc-tab-icon--action {
      color: var(--oc-text-primary);
    }

    .oc-tabwrap-active .oc-tab-icon--action,
    .oc-tabwrap-active:hover .oc-tab-icon--action {
      color: var(--oc-orange);
    }

    .oc-tab-workflow {
      color: var(--oc-cyan);
      line-height: 0;
      animation: oc-tab-workflow-pulse 2.4s ease-in-out infinite;
    }

    @keyframes oc-tab-workflow-pulse {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.6; }
    }

    @media (prefers-reduced-motion: reduce) {
      .oc-tab-workflow { animation: none; }
    }
  }
</style>
