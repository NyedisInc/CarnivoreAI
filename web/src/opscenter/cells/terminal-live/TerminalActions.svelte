<script lang="ts">
  import type { Snippet } from 'svelte';
  import Icon from '../../ui/Icon.svelte';
  import { sessions, asleep, sleepSession } from '../../api';
  import { primarySessionId } from '../../api/host';
  import { rowFor } from '../terminal-viewer/meta';
  import { terminalAction, toolShowing } from './actions';
  import { splitToolbar, planFolds, menuItems, itemApplies, STRIP_ITEMS, TOOLBAR_ITEMS, type ToolbarItem, type ToolbarSplit } from './toolbar';
  import { openSessionBookmarks } from '../../../lib/bookmarks/row-actions';
  import { isKeptAwake, setKeepAwake, SLEEPABLE_FAMILIES } from '../../../lib/auto-sleep/auto-sleep-store.svelte';
  import { notesAreOpen, toggleSessionNotes } from '../../../lib/notes-header/mount-notes';
  import { inputFocus } from '../../lib/input-focus.svelte';
  import { activeTerminalSlot } from '../../lib/active-terminal';
  import { shiftKey, watchShift } from '../../lib/shift-held.svelte';
  import { layoutZoom } from '../../engine/layout-zoom.svelte';
  import { t } from '../../../lib/i18n/index.svelte';
  import TerminalBackgroundButton from '../../../lib/terminal-background/TerminalBackgroundButton.svelte';
  import SizeMasterCrown from './SizeMasterCrown.svelte';
  import { closeRowMenu, openRowMenu, uuidOfTmuxName } from './row-menu';
  import Glyph from '../../../lib/Glyph.svelte';
  import { sizeMasterRole, toggleSizeMaster } from '../../api/size-master.svelte';
  import { useFrameHeader } from '../../shell/frame-header.svelte';
  import { declareWidgetActions } from '../../widgets/menu/declared-actions.svelte';
  import { tabMenuActions, widgetMenuActions, type TerminalMenuInput } from './terminal-menu-actions';
  import { claimOpenMenu } from '../../../lib/drawer-tabs/open-menu';
  import { canOpenInTerminal, openInTerminal } from '../../../lib/desktop-menu/open-in-terminal';
  import { canPopOutSession, popOutSession } from '../../../lib/desktop-menu/pop-out-session';
  let { slot, sessionId, width = 0, utilities, groupSlot = null, sessionName = null, getPalette, inHeader = false, agentFamily = null }: {
    slot: string; sessionId: string; width?: number; utilities?: Snippet; groupSlot?: string | null;
    inHeader?: boolean;
    agentFamily?: string | null;
    sessionName?: string | null;
    getPalette?: () => Record<string, string> | undefined;
  } = $props();
  let expanded = $state(false);
  let options = $state<HTMLDivElement | null>(null);
  let menuAnchor = $state<HTMLButtonElement | null>(null);
  let actionsItem = $state<HTMLButtonElement | null>(null);
  let foldOpen = $state(false);
  let foldFromHover = false;
  const row = $derived(rowFor(sessions.data, sessionId));

  let step = $state('');
  const ladder = $derived(splitToolbar(width, step));
  $effect(() => { step = ladder.state; });

  let tools = $state<HTMLDivElement | null>(null);
  let fit = $state<{ room: number; kebab: number } | null>(null);
  let widths = $state<Record<string, number>>({});

  function isActive(item: ToolbarItem): boolean {
    if (item.id === 'utilities') return isKeptAwake(sessionName) === true;
    if (item.id === 'size-master') return sizeMasterRole(sessionId) === 'master';
    return pressed(item);
  }

  const applies = (item: ToolbarItem): boolean => itemApplies(item.id, agentFamily);

  const split = $derived.by((): ToolbarSplit => {
    if (!fit) return { ...ladder, bar: ladder.bar.filter(applies), overflow: ladder.overflow.filter(applies) };
    const folded = new Set(planFolds(fit.room, fit.kebab,
      STRIP_ITEMS.filter(applies).map((item) => ({ id: item.id, width: widths[item.id] ?? 28, active: isActive(item) }))));
    return {
      state: ladder.state,
      bar: STRIP_ITEMS.filter((item) => applies(item) && !folded.has(item.id)),
      overflow: menuItems(folded).filter(applies),
    };
  });

  const kebabHolds = $derived(split.overflow.length > 0 || !!row?.tmux_session);

  function naturalTab(tab: HTMLElement): number {
    const name = tab.querySelector<HTMLElement>('.oc-tab-name');
    const full = tab.offsetWidth + (name ? name.scrollWidth - name.clientWidth : 0);
    return Math.min(240, Math.max(96, full));
  }

  function itemWidths(bar: HTMLElement): Record<string, number> {
    const next: Record<string, number> = { ...widths };
    for (const el of bar.querySelectorAll<HTMLElement>(':scope > [data-tool]')) {
      const id = el.dataset.tool === 'leave-fullscreen' ? 'search' : el.dataset.tool;
      if (!id || id === 'overflow') continue;
      const extra = el.dataset.tool === 'leave-fullscreen' ? (next[id] ?? 0) : 0;
      next[id] = el.offsetWidth + 2 + extra;
    }
    for (const item of TOOLBAR_ITEMS) if (!bar.querySelector(`:scope > [data-tool="${item.id}"]`)) next[item.id] ??= 28;
    return next;
  }

  function keep(next: Record<string, number>, room: number, kebab: number): void {
    if (Object.keys(next).some((k) => next[k] !== widths[k])) widths = next;
    if (!fit || fit.room !== room || fit.kebab !== kebab) fit = { room, kebab };
  }

  function measureHead(): void {
    const head = tools?.closest<HTMLElement>('[data-widget-head]');
    const spacer = head?.querySelector<HTMLElement>(':scope > .oc-frame-spacer');
    if (!tools || !head || !spacer || !head.clientWidth) return;
    keep(itemWidths(tools), tools.offsetWidth + spacer.offsetWidth, 0);
  }

  function measure(): void {
    if (inHeader) { measureHead(); return; }
    const strip = tools?.closest<HTMLElement>('.oc-frame-strip');
    const row = strip?.querySelector<HTMLElement>('.oc-tabrow');
    if (!tools || !strip || !row || !strip.clientWidth) return;
    const next = itemWidths(tools);
    const tabs = [...row.querySelectorAll<HTMLElement>('.oc-tabwrap')];
    const plus = row.querySelector<HTMLElement>('.oc-tab-new');
    const natural = tabs.reduce((sum, tab) => sum + naturalTab(tab), 0) + Math.max(0, tabs.length - 1)
      + (plus ? plus.offsetWidth + 6 : 0);
    const room = tools.offsetWidth + (row.offsetWidth - natural);
    keep(next, room, menuAnchor ? menuAnchor.offsetWidth + 2 : 0);
  }

  $effect(() => {
    const strip = tools?.closest<HTMLElement>(inHeader ? '[data-widget-head]' : '.oc-frame-strip');
    if (!strip || typeof ResizeObserver === 'undefined') return;
    let queued = false;
    const again = (): void => {
      if (queued) return;
      queued = true;
      queueMicrotask(() => { queued = false; measure(); });
    };
    const resize = new ResizeObserver(again);
    resize.observe(strip);
    const mutate = new MutationObserver(again);
    const tabs = strip.querySelector(inHeader ? '.oc-frame-name' : '.oc-tabs');
    if (tabs) mutate.observe(tabs, { childList: true, subtree: true, characterData: true });
    again();
    return () => { resize.disconnect(); mutate.disconnect(); };
  });

  let themeOpen = $state(false);

  function pressed(item: ToolbarItem): boolean {
    if (item.id === 'theme') return themeOpen;
    if (item.id === 'notes') return notesAreOpen() && activeTerminalSlot() === slot;
    return item.action ? toolShowing(slot, item.action) : false;
  }

  let downShowing: boolean | undefined;

  function sleepUuid(): string | null {
    return uuidOfTmuxName(row?.tmux_session);
  }

  function ready(item: ToolbarItem): boolean {
    if (item.id === 'theme') return !!row?.tmux_session;
    if (item.id === 'sleep') return !!sleepUuid();
    return !!sessionId;
  }

  function labelFor(item: ToolbarItem, armed: boolean): string {
    if (armed) return t('opscenter.tabs.zoom_hint');
    return item.label ? t(item.label) : '';
  }

  function run(item: ToolbarItem, anchor: HTMLElement): void {
    const showing = downShowing;
    downShowing = undefined;
    inputFocus.select(slot);
    if (item.id === 'theme') { chooseTheme(anchor); return; }
    if (item.id === 'notes') { runNotes(showing); return; }
    if (item.id === 'sleep') { void sleepThis(); return; }
    if (item.action) runTool(item.action, anchor, showing);
  }

  $effect(() => watchShift());

  function zoomArmed(item: ToolbarItem): boolean {
    return item.id === 'search' && shiftKey.held && groupSlot !== null && layoutZoom.canZoom;
  }

  function runOrZoom(item: ToolbarItem, anchor: HTMLElement, event: MouseEvent): void {
    if (item.id === 'search' && groupSlot !== null && (event.shiftKey || shiftKey.held) && layoutZoom.canZoom) {
      layoutZoom.toggle(groupSlot);
      return;
    }
    run(item, anchor);
  }

  let releaseHandle: () => void = () => {};

  function showOptions(): void {
    if (!options || !menuAnchor) return;
    if (!options.togglePopover()) return;
    releaseHandle();
    releaseHandle = claimOpenMenu(() => options?.hidePopover());
    options.style.maxHeight = `${Math.max(0, (window.visualViewport?.height ?? innerHeight) - 16)}px`;
    const placement = (globalThis as { AnchorPopover?: {
      place(el: HTMLElement, anchor: HTMLElement): unknown;
    } }).AnchorPopover;
    placement?.place(options, menuAnchor);
    options.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
  }
  function closeOptions(): void {
    options?.hidePopover();
    menuAnchor?.focus();
  }
  function onOptionsKeyDown(event: KeyboardEvent): void {
    if (event.key === 'Escape') { closeOptions(); return; }
    if (event.key === 'ArrowRight' && document.activeElement === actionsItem) { event.preventDefault(); openFold(); return; }
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
    event.preventDefault();
    const items = options
      ? [...options.querySelectorAll<HTMLElement>('[role="menuitem"]')].filter((item) => item.closest('[role="menu"]') === options)
      : [];
    if (!items.length) return;
    const at = items.findIndex((item) => item === document.activeElement);
    const step = event.key === 'ArrowDown' ? 1 : -1;
    const next = items[(at + step + items.length) % items.length];
    next?.focus();
  }
  function chooseTheme(anchor: HTMLElement | null = menuAnchor): void {
    options?.hidePopover();
    const picker = (globalThis as { SessionThemeMenu?: {
      open(anchor: HTMLElement, context: Record<string, unknown>): void;
      close?(): void;
    } }).SessionThemeMenu;
    if (themeOpen) {
      picker?.close?.();
      themeOpen = false;
      return;
    }
    if (!anchor || !row?.tmux_session || !picker) return;
    picker.open(anchor, { sessionName: row.tmux_session, hostKey: row.host_key,
      pinnedTheme: row.pinned_theme,
      agentType: row.agent_type, onSelected: () => { void sessions.refresh(true); },
      onClose: () => { themeOpen = false; } });
    themeOpen = true;
  }
  function runTool(action: TerminalActionId, anchor: HTMLElement, showing?: boolean): void {
    options?.hidePopover();
    terminalAction(slot, action, anchor, showing);
  }
  function runNotes(showing?: boolean): void {
    options?.hidePopover();
    const mine = showing ?? (notesAreOpen() && activeTerminalSlot() === slot);
    // there is nothing
    if (!mine && notesAreOpen()) return;
    toggleSessionNotes();
  }
  function openFold(fromHover = false): void {
    if (foldOpen || !row || !actionsItem || !options) return;
    foldOpen = openRowMenu(row, sleepUuid(), actionsItem, {
      host: options, onClose: () => { foldOpen = false; foldFromHover = false; },
    });
    foldFromHover = foldOpen && fromHover;
  }

  function hoverFold(): void {
    openFold(true);
  }

  function toggleFold(): void {
    if (foldOpen && foldFromHover) foldFromHover = false;
    else if (foldOpen) closeRowMenu();
    else openFold();
  }

  function retractFold(event: PointerEvent): void {
    if (!foldOpen) return;
    const item = (event.target as Element | null)?.closest<HTMLElement>('[role="menuitem"]');
    if (item && item !== actionsItem && item.closest('[role="menu"]') === options) closeRowMenu();
  }
  type TerminalActionId = Parameters<typeof terminalAction>[1];

  /* too rather than */
  const PRIMARY_SESSION_GONE_EVENT = 'cloude:primary-session-gone';

  async function sleepThis(): Promise<void> {
    options?.hidePopover();
    const uuid = sleepUuid();
    if (!uuid) return;
    try {
      const res = await sleepSession(uuid);
      if (res?.status !== 'asleep') return;
      await Promise.all([sessions.refresh(true), asleep.refresh()]);
      if (sessionId === primarySessionId()) {
        globalThis.dispatchEvent(new CustomEvent(PRIMARY_SESSION_GONE_EVENT, { detail: { sessionId } }));
      }
    } catch (err) {
      console.error('[TerminalActions] sleep failed:', err);
    }
  }

  const frameHeader = useFrameHeader();
  /* the widget menu */
  let background = $state<{ toggleAt(anchor: HTMLElement): void } | null>(null);
  const headIcon = (): HTMLElement | null => tools?.closest('[data-widget-head]')?.querySelector<HTMLElement>('[data-corner]') ?? tools;
  $effect(() => {
    if (!frameHeader) return;
    const anchor = (): HTMLElement | null => (inHeader ? headIcon() : menuAnchor);
    const zoomable = groupSlot !== null && layoutZoom.canZoom;
    const input: TerminalMenuInput = {
      runItem: (id) => {
        const item = TOOLBAR_ITEMS.find((one) => one.id === id);
        const at = anchor();
        if (item && at) run(item, at);
      },
      ready: (id) => {
        const item = TOOLBAR_ITEMS.find((one) => one.id === id);
        return item ? ready(item) : false;
      },
      zoom: zoomable ? { label: t(layoutZoom.isZoomed(groupSlot!) ? 'opscenter.tabs.leave_fullscreen' : 'opscenter.tabs.zoom'), run: () => (layoutZoom.isZoomed(groupSlot!) ? layoutZoom.restore() : layoutZoom.toggle(groupSlot!)) } : null,
      sizeMaster: sessionId ? { on: sizeMasterRole(sessionId) === 'master', run: () => void toggleSizeMaster(sessionId) } : null,
      sleepLabel: labelFor(TOOLBAR_ITEMS.find((one) => one.id === 'sleep')!, false),
      notReady: t('opscenter.tabs.not_ready'),
      applies: (id) => itemApplies(id, agentFamily),
      popOut: canPopOutSession(row?.session_row_id) ? { label: t('terminal.menu.pop_out'), run: () => void popOutSession(row!.session_row_id!, slot) } : null,
    };
    if (!inHeader) return declareWidgetActions(frameHeader.hostId, 'terminal', tabMenuActions(input));
    const kept = isKeptAwake(sessionName);
    return declareWidgetActions(frameHeader.hostId, 'terminal', widgetMenuActions({
      ...input,
      menu: split.overflow.map((item) => item.id),
      background: () => { const at = anchor(); if (at) background?.toggleAt(at); },
      keepAwake: sessionName && agentFamily && SLEEPABLE_FAMILIES.includes(agentFamily) && kept !== null
        ? { on: kept, run: () => void setKeepAwake(sessionName, !kept) } : null,
      bookmarks: sessionName && agentFamily === 'claude' ? () => void openSessionBookmarks(sessionName) : null,
      rowActions: row?.tmux_session ? () => { const at = anchor(); if (at && row) openRowMenu(row, sleepUuid(), at); } : null,
      openInTerminal: canOpenInTerminal(sessionId, row?.host_key, row?.tmux_session) ? () => void openInTerminal(sessionId) : null,
      words: { background: t('terminal.background.open'), keepAwake: t('session.menu.keep_awake.turn_on'), bookmarks: t('bookmarks.title'), actions: t('terminal.actions.open'), openInTerminal: t('desktop.menu.open_in_terminal') },
    }));
  });

</script>
<div class="cell-tools" bind:this={tools} role="group" aria-label={t('terminal.tools.label')} data-toolbar-state={split.state}>
  {#each split.bar as item (item.id)}
    {#if item.id === 'utilities'}
      {#if utilities}<span class="bar-utilities" data-tool="utilities">{@render utilities()}</span>{/if}
    {:else if item.id === 'background'}
      
      <span class="bar-utilities" data-tool="background"><TerminalBackgroundButton {sessionName} {getPalette} /></span>
    {:else if item.id === 'size-master'}
      <SizeMasterCrown {sessionId} />
    {:else}
      {@const armed = zoomArmed(item)}
      <button type="button" data-tool={item.id} class:tool-zoom-armed={armed}
        title={labelFor(item, armed)}
        aria-label={labelFor(item, armed)}
        aria-pressed={pressed(item)} disabled={!ready(item)}
        onpointerdown={() => { downShowing = pressed(item); }}
        onclick={(event) => runOrZoom(item, event.currentTarget, event)}
        >{#if armed}<Icon name="expand" size={15} />{:else}<Icon name={item.icon ?? ''} size={15} />{/if}</button>
      {#if item.id === 'search' && groupSlot !== null && layoutZoom.isZoomed(groupSlot)}
        <button type="button" data-tool="leave-fullscreen"
          title={t('opscenter.tabs.leave_fullscreen')} aria-label={t('opscenter.tabs.leave_fullscreen')}
          onclick={() => layoutZoom.restore()}>
          <Icon name="shrink" size={15} />
        </button>
      {/if}
    {/if}
  {/each}
  
  {#if inHeader}
    <TerminalBackgroundButton {sessionName} {getPalette} headless bind:this={background} />
  {:else if kebabHolds}
  <button type="button" bind:this={menuAnchor} aria-label={t('terminal.options.label')}
    aria-haspopup="menu" aria-expanded={expanded} data-tool="overflow" onclick={showOptions}><svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="12" cy="5" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="12" cy="19" r="1.5"/></svg></button>
  {/if}
</div>
{#if !inHeader}

<div class="cell-options popup-focus" bind:this={options} popover="auto" role="menu" tabindex="-1"
  aria-label={t('terminal.options.label')}
  ontoggle={(event) => {
    expanded = event.newState === 'open';
    if (expanded) return;
    releaseHandle();
    if (foldOpen) closeRowMenu();
  }}
  onpointerover={retractFold}
  onkeydown={onOptionsKeyDown}>
  {#each split.overflow as item (item.id)}
    {#if item.id === 'background'}
      
      <div role="none" data-tool="background">
        <TerminalBackgroundButton {sessionName} {getPalette} asMenuItem />
      </div>
    {:else if item.id === 'utilities'}
      {#if utilities}
        <div class="overflow-utilities" role="group" aria-label={t('terminal.keep_awake.label')} data-tool="utilities">
          {@render utilities()}
        </div>
      {/if}
    {:else if item.id === 'size-master'}
      
      {@const role = sizeMasterRole(sessionId)}
      <button type="button" role="menuitem" data-tool="size-master" data-size-master={role} aria-pressed={role === 'master'}
        disabled={!sessionId}
        onclick={() => { void toggleSizeMaster(sessionId); }}>
        <Glyph name="crown" size={15} />{t(`terminal.size_master.${role}`)}
      </button>
    {:else}
      {@const armed = zoomArmed(item)}
      <button type="button" role="menuitem" data-tool={item.id} class:tool-zoom-armed={armed} disabled={!ready(item)}
        aria-pressed={pressed(item)}
        onpointerdown={() => { downShowing = pressed(item); }}
        onclick={(event) => { if (menuAnchor) runOrZoom(item, menuAnchor, event); }}>
        {#if armed}<Icon name="expand" size={15} />{:else}<Icon name={item.icon ?? ''} size={15} />{/if}{labelFor(item, armed)}
      </button>
      {#if item.id === 'search' && groupSlot !== null && layoutZoom.isZoomed(groupSlot)}
        <button type="button" role="menuitem" data-tool="leave-fullscreen"
          onclick={() => layoutZoom.restore()}>
          <Icon name="shrink" size={15} />{t('opscenter.tabs.leave_fullscreen')}
        </button>
      {/if}
    {/if}
  {/each}
  
  <button type="button" role="menuitem" data-tool="actions" class:after-tools={split.overflow.length > 0} disabled={!row?.tmux_session}
    bind:this={actionsItem} aria-haspopup="menu" aria-expanded={foldOpen}
    onpointerenter={hoverFold} onclick={toggleFold}>
    <span style="flex:1">{t('terminal.actions.open')}</span><Icon name="chevron-right" size={12} />
  </button>
</div>
{/if}
<style>
  @layer components {
    .cell-tools { display:flex; align-items:center; gap:2px; }

    .cell-tools button, .cell-tools :global(.tbg-open) { display:flex; align-items:center; justify-content:center; width:26px; height:var(--cell-tool-h, 26px); margin:0; padding:0; border:1px solid transparent; border-radius:3px; background:transparent; color:var(--oc-text-dim); cursor:pointer; }

    .bar-utilities { display:flex; align-items:center; align-self:stretch; gap:2px; }

    .bar-utilities :global([data-bookmarks-open]) { height:var(--cell-tool-h, var(--oc-ibtn-size, 20px)); }

    :global(.oc-frame-strip) .cell-tools { align-self:stretch; box-sizing:border-box; border-top:0; border-bottom:calc(var(--oc-border) + 5px) solid transparent; --cell-tool-h:100%; }

    button:hover, button:focus-visible, .cell-tools :global(.tbg-open:hover), .cell-tools :global(.tbg-open:focus-visible) { border-color:var(--oc-orange); background:var(--oc-ground-hover); transform:none; }

    .cell-tools :global(.tbg-open:focus-visible) { box-shadow:none; }

    button:disabled { opacity:.4; cursor:default; }

    .cell-tools button[aria-pressed='true'], .cell-options button[aria-pressed='true'], .cell-tools :global(.tbg-open[aria-expanded='true']) { color:var(--oc-orange); }

    .cell-options button.tool-zoom-armed,
    .cell-options button.tool-zoom-armed:hover { color:var(--oc-cyan); }

    .cell-options { position:fixed; inset:8px auto auto 8px; margin:0; padding:5px; width:190px; max-width:calc(100vw - 16px); box-sizing:border-box; overflow:auto; border-radius:var(--oc-radius-sm); color:var(--oc-text-primary); }

    .cell-options button {
      display:flex; align-items:center; gap:var(--oc-space-2); width:100%; padding:6px var(--oc-space-2);
      border:1px solid transparent; border-radius:var(--oc-radius-sm);
      background:transparent; color:var(--oc-text-secondary); font:inherit;
      font-size:var(--oc-fs-label); text-align:left; cursor:pointer;
    }

    .cell-options button:hover, .cell-options button:focus-visible {
      border-color:transparent; background:var(--oc-ground-hover); color:var(--oc-text-bright);
    }

    .cell-options button:disabled { opacity:.45; cursor:default; }

    .cell-options button:disabled:hover { background:transparent; }

    .overflow-utilities { display:flex; align-items:center; gap:var(--oc-space-3); padding:6px var(--oc-space-2); }

    .cell-options button.after-tools { margin-top:var(--oc-space-1); box-shadow:inset 0 var(--oc-border) 0 0 var(--oc-line-rule); }

    @media (pointer: coarse) {
      .cell-tools button, .cell-tools :global(.tbg-open) { width:44px; height:44px; }
      .cell-options button { min-height:44px; }
  }
  }
</style>
