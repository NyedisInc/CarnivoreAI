<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';

  export const LIVE_TERMINAL_WIDGET = defineWidget({ id: 'core.terminal', scope: 'global', actions: [], state: {} });
</script>

<script lang="ts">
  /* of its own - */
  import { untrack } from 'svelte';
  import type { CellProps } from '../../lib/cell';
  import { legacyGlobal } from '../../../lib/legacy-globals';
  import { atLeast } from '../../lib/states';
  import { sessions, statusHue, statusLabel, type StatusHue } from '../../api';
  import { hostOffline, usageLimitLabel } from '../../../lib/led';
  import { inputFocus } from '../../lib/input-focus.svelte';
  import { rowFor, sessionIdOf, VIEWER_KEYS } from '../terminal-viewer/meta';
  import { startLiveTerminal, type LiveTerminal } from './client';
  import { registerTerminalActions } from './actions';
  import type { ControllerLike } from '../../../lib/terminal-search/search-host';
  import TerminalHead from './TerminalHead.svelte';
  import TerminalFoot from './TerminalFoot.svelte';
  import { bindTerminalTheme } from './theme';
  import { pendingTheme, setPendingTheme } from './pending-theme.svelte';
  import { followTab } from '../terminal-group/tab-vote';
  import { useFrameHeader, useTabPane } from '../../shell/frame-header.svelte';
  import { layoutZoom } from '../../engine/layout-zoom.svelte';
  import { t } from '../../../lib/i18n/index.svelte';
  import MemberDown from '../../layouts/MemberDown.svelte';
  import { layoutActive } from '../../layouts/mode.svelte';
  import { terminalLayout } from '../../engine/layout.svelte';
  import { park, parkKey, shouldHoldForMove, shouldPark, unpark } from './parking';
  import SkillsDrawer from '../../../lib/session-skills/SkillsDrawer.svelte';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import { useWidget } from '../../widgets/shell/define-widget.svelte';

  let { width, height, meta, instance }: CellProps = $props();

  const widget = useWidget(LIVE_TERMINAL_WIDGET, () => ({ width, height, meta, instance }));

  const sessionId = $derived(sessionIdOf(instance, sessions.data));

  // the page terminal
  $effect(() => {
    return inputFocus.mount(instance);
  });

  const widthState = $derived(widget.widthState);
  const heightState = $derived(widget.heightState);

  const showsPane = $derived(atLeast(meta.heightStates, heightState, 'pane'));
  const showsStatusWord = $derived(atLeast(meta.widthStates, widthState, 'wide'));

  const row = $derived(rowFor(sessions.data, sessionId));

  let askedFor = $state('');

  $effect(() => {
    if (!sessionId || row || askedFor === sessionId) return;
    askedFor = sessionId;
    void sessions.refresh(true);
  });
  const dead = $derived(sessions.status === 'ok' && sessionId !== '' && row === null);

  const hue = $derived<StatusHue>(
    row ? statusHue(row.activity_status, row.startup_gate, row.unread, hostOffline(row), usageLimitLabel(row)) : 'grey',
  );
  const statusWord = $derived(
    row ? statusLabel(row.activity_status, row.startup_gate, row.unread, hostOffline(row), row.activity_hint, usageLimitLabel(row)) : '',
  );
  const name = $derived((row?.label ?? '').trim() || sessionId);

  let bodyEl = $state<HTMLDivElement | null>(null);
  let liveClient = $state<unknown>(null);

  const owned = $derived(inputFocus.owner === instance);

  /* there is nothing */
  const terminalKey = $derived(
    row === null ? '' : sessionId + '\n' + (row.tmux_session ?? ''),
  );

  const live = $derived(sessionId !== '' && showsPane && !dead && bodyEl !== null);

  const slotKey = $derived(instance);

  $effect(() => {
    if (!live || terminalKey === '') return;
    const body = bodyEl;
    const target = untrack(() => row);
    if (!body || !target) return;
    const slot = slotKey;
    const owner = untrack(() => terminalLayout.session);
    const key = parkKey(slot, terminalKey);
    const kept = unpark(owner, key);
    const el = kept?.host ?? paneElement();
    body.appendChild(el);
    let handle: LiveTerminal | null = kept?.handle ?? untrack(() => startLiveTerminal(el, slot, target));
    liveClient = handle ? handle.client : null;
    if (!handle) {
      console.error(
        'CloudeOpscenter: the terminal client is not on this page, so cell '
          + slot + ' drew nothing',
      );
      return () => el.remove();
    }
    const stopActions = untrack(() => registerTerminalActions(
      slot, handle!.client as ControllerLike, el, false, el.parentElement,
    ));
    return () => {
      stopActions();
      if (handle && shouldPark(owner, terminalLayout.session)) park(owner, key, el, handle);
      else if (handle && shouldHoldForMove()) park(owner, key, el, handle, true);
      else {
        handle?.dispose();
        el.remove();
      }
      handle = null;
      liveClient = null;
    };
  });

  function paneElement(): HTMLDivElement {
    const el = document.createElement('div');
    el.className = 'oc-tl-pane xterm-host';
    return el;
  }

  const tabPane = useTabPane();
  const frameHeader = useFrameHeader();
  const groupSlot = $derived(frameHeader?.gridSlot ?? null);
  $effect(() => {
    if (liveClient) followTab(liveClient, slotKey, tabPane, layoutZoom.isCovered(groupSlot));
  });

  const activePane = $derived(row?.tmux_session ?? null);

  $effect(() => {
    if (!owned) return;
    const name = activePane;
    if (!name) return;
    const bg = (globalThis as { TerminalBackground?: {
      setActiveSession(name: string): void;
    } }).TerminalBackground;
    bg?.setActiveSession(name);
  });

  const themePin = $derived(pendingTheme(row?.tmux_session) ?? row?.pinned_theme ?? null);
  $effect(() => {
    const tmux = row?.tmux_session;
    if (tmux && pendingTheme(tmux) === (row?.pinned_theme ?? null)) setPendingTheme(tmux, null);
  });

  $effect(() => {
    if (!liveClient || !bodyEl) return;
    return bindTerminalTheme(liveClient, bodyEl, {
      pinnedTheme: themePin,
    });
  });

  function takeFocus(): void {
    inputFocus.claim(instance);
  }

  let pointedAt = false;
  function notePointer(event: PointerEvent): void {
    pointedAt = event.target instanceof Node && (tlEl?.contains(event.target) ?? false);
  }
  let tlEl: HTMLDivElement | undefined;

  function noPaneKey(event: KeyboardEvent): void {
    if (!dead && showsPane) return;
    if (!pointedAt) return;
    const t = event.target;
    if (t instanceof HTMLElement && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
    const drops = legacyGlobal<{ record(reason: string, c: { _inputOwner: string }): void }>('TerminalInputDrops');
    drops?.record('no_live_pane', { _inputOwner: instance });
  }

  function dropFocus(event: FocusEvent): void {
    const next = event.relatedTarget;
    const body = event.currentTarget;
    if (next instanceof Node && body instanceof Node && body.contains(next)) return;
    inputFocus.release(instance);
  }

</script>

<svelte:window onkeydowncapture={noPaneKey} onpointerdowncapture={notePointer} />
<WidgetShell {widget} bare>
<div class="oc-tl" data-foot-area bind:this={tlEl}>
  <TerminalHead {hue} {name} {statusWord} {showsStatusWord} measured={row !== null}
    {sessionId} {width} slot={instance} controller={liveClient}
    agentFamily={row?.agent_family ?? null} />

  
  <div class="oc-tl-stage">
    {#if dead && layoutActive()}
      
      <MemberDown {instance} />
    {:else if dead}
      <p class="oc-tl-note" data-viewer-state="dead">
        {t(VIEWER_KEYS.gone, { action: t(VIEWER_KEYS.remove) })}
      </p>
    {:else if !showsPane}
      <p class="oc-tl-note" data-viewer-state="strip">{t(VIEWER_KEYS.tooShort)}</p>
    {:else}
      
      <div
        class="oc-tl-body"
        data-viewer-state="pane"
        data-terminal-role="primary"
        bind:this={bodyEl}
        data-input-owner={owned ? 'true' : null}
        onfocuscapture={takeFocus}
        onfocusincapture={takeFocus}
        onkeydowncapture={takeFocus}
        onpointerdowncapture={takeFocus}
        onfocusoutcapture={dropFocus}
      ></div>
    {/if}
    {#if !dead}<SkillsDrawer {sessionId} slot={instance} {width} />{/if}
  </div>

  {#if sessionId}
    <TerminalFoot {sessionId} {width} />
  {/if}
</div>
</WidgetShell>

<style>
  .oc-tl {
    display: flex;
    flex-direction: column;
    min-height: 0;
    height: 100%;
    gap: 0;
  }

  .oc-tl-note {
    margin: 0;
    padding: 2px 10px var(--oc-space-2);
    color: var(--oc-text-dim);
    font-size: var(--oc-fs-label);
  }

  .oc-tl-body {
    position: relative;
    flex: 1 1 auto;
    min-height: 0;
    min-width: 0;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .oc-tl-body :global(.oc-tl-pane) {
    position: relative;
    flex: 1 1 auto;
    min-height: 0;
    min-width: 0;
    padding-left: var(--oc-terminal-inset);
    display: flex;
    flex-direction: column;
    justify-content: flex-end;
  }

</style>
