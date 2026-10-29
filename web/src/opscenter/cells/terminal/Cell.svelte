<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';

  export const TERMINAL_WIDGET = defineWidget({ id: 'core.terminal', scope: 'global', actions: [], state: {} });
</script>

<script lang="ts">
  import type { CellProps } from '../../lib/cell';
  import { sessions, statusHue, statusLabel, type StatusHue } from '../../api';
  import { hostOffline, usageLimitLabel } from '../../../lib/led';
  import { atLeast } from '../../lib/states';
  import { primarySessionId } from '../../api/host';
  import { PRIMARY_BIND_EVENT } from '../../engine/primary-bind';
  import { rowFor } from '../terminal-viewer/meta';
  import TerminalHead from '../terminal-live/TerminalHead.svelte';
  import TerminalFoot from '../terminal-live/TerminalFoot.svelte';
  import { adoptPane } from './adopt';
  import { registerTerminalActions } from '../terminal-live/actions';
  import type { ControllerLike } from '../../../lib/terminal-search/search-host';
  import { bindTerminalTheme } from '../terminal-live/theme';
  import { followTab, rejoinTab } from '../terminal-group/tab-vote';
  import { useFrameHeader, useTabPane } from '../../shell/frame-header.svelte';
  import { layoutZoom } from '../../engine/layout-zoom.svelte';
  import { isPrimaryInstance } from './meta';
  import ViewerCell from '../terminal-viewer/Cell.svelte';
  import LiveCell from '../terminal-live/Cell.svelte';
  import SkillsDrawer from '../../../lib/session-skills/SkillsDrawer.svelte';
  import { drivesItsOwnSession } from '../terminal-live/meta';
  import { inputFocus } from '../../lib/input-focus.svelte';
  import { t } from '../../../lib/i18n/index.svelte';
  import State from '../../../lib/base/State.svelte';
  import { layoutMode } from '../../layouts/mode.svelte';

  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import { useWidget } from '../../widgets/shell/define-widget.svelte';

  let { width, height, meta, instance, page = 'home' }: CellProps = $props();

  const widget = useWidget(TERMINAL_WIDGET, () => ({ width, height, meta, instance }));

  // the page terminal
  $effect(() => {
    const slot = instance;
    return () => inputFocus.forget(slot);
  });

  let boundSession = $state(primarySessionId());

  $effect(() => {
    boundSession = primarySessionId();
    const onBind = (event: Event): void => {
      const id = (event as CustomEvent<{ sessionId?: string }>).detail?.sessionId;
      if (id) boundSession = id;
    };
    globalThis.addEventListener(PRIMARY_BIND_EVENT, onBind);
    return () => globalThis.removeEventListener(PRIMARY_BIND_EVENT, onBind);
  });
  const shownSession = $derived(
    layoutMode.holding && layoutMode.anchorSessionId ? layoutMode.anchorSessionId : boundSession,
  );
  const boundRow = $derived(rowFor(sessions.data, shownSession));
  const boundHue = $derived<StatusHue>(
    boundRow
      ? statusHue(boundRow.activity_status, boundRow.startup_gate, boundRow.unread, hostOffline(boundRow), usageLimitLabel(boundRow))
      : 'grey',
  );
  const boundWord = $derived(
    boundRow ? statusLabel(boundRow.activity_status, boundRow.startup_gate, boundRow.unread, hostOffline(boundRow), boundRow.activity_hint, usageLimitLabel(boundRow)) : '',
  );
  const boundName = $derived((boundRow?.label ?? '').trim() || shownSession);

  const widthState = $derived(widget.widthState);
  const showsStatusWord = $derived(atLeast(meta.widthStates, widthState, 'wide'));

  let paneHost = $state<HTMLElement | null>(null);

  let hasPane = $state(false);

  const primary = $derived(isPrimaryInstance(instance));

  const heightState = $derived(widget.heightState);

  const strip = $derived(heightState === 'strip');

  $effect(() => {
    const host = paneHost;
    if (!host || !primary) return;
    const release = adoptPane(host);
    if (!release) return;
    hasPane = true;
    const named = nameTheSlot(instance);
    const controller = (globalThis as { TerminalController?: ControllerLike }).TerminalController;
    const container = host.querySelector<HTMLElement>('#terminal-container');
    const stopActions = controller && container
      ? registerTerminalActions(instance, controller, container, true) : () => {};
    return () => {
      hasPane = false;
      stopActions();
      if (named) nameTheSlot(null);
      inputFocus.release(instance);
      release();
    };
  });

  const tabPane = useTabPane();
  const frameHeader = useFrameHeader();
  const groupSlot = $derived(frameHeader?.gridSlot ?? null);
  $effect(() => {
    if (!hasPane) return;
    followTab(
      (globalThis as { TerminalController?: unknown }).TerminalController,
      instance,
      tabPane,
      layoutZoom.isCovered(groupSlot) || layoutMode.holding,
    );
  });
  $effect(() => {
    if (!hasPane) return;
    const controller = (globalThis as { TerminalController?: unknown }).TerminalController;
    return () => rejoinTab(controller);
  });

  const themePin = $derived(boundRow?.pinned_theme ?? null);

  $effect(() => {
    if (!hasPane || !paneHost) return;
    const client = (globalThis as { TerminalController?: unknown }).TerminalController;
    return bindTerminalTheme(client, paneHost, {
      pinnedTheme: themePin,
    });
  });

  function nameTheSlot(slot: string | null): boolean {
    const controller = (globalThis as { TerminalController?: unknown }).TerminalController as
      | { setInputOwner?: (slot: string | null) => void }
      | undefined;
    if (typeof controller?.setInputOwner !== 'function') return false;
    controller.setInputOwner(slot);
    return true;
  }

  function takeFocus(): void {
    if (!hasPane) return;
    inputFocus.claim(instance);
  }

  function dropFocus(event: FocusEvent): void {
    const next = event.relatedTarget;
    const host = event.currentTarget;
    if (next instanceof Node && host instanceof Node && host.contains(next)) return;
    inputFocus.release(instance);
  }
</script>

<WidgetShell {widget} bare>
{#if primary}
  <div class="oc-tl" data-foot-area>
    
    <TerminalHead
      sessionId={shownSession}
      slot={instance}
      controller={hasPane ? (globalThis as { TerminalController?: unknown }).TerminalController : null}
      hue={boundHue}
      name={boundName}
      statusWord={boundWord}
      {showsStatusWord}
      {width}
      measured={boundRow !== null}
      agentFamily={boundRow?.agent_family ?? null}
    />
    
    
    <div class="oc-tl-stage">
      <div
        class="cc-pane"
        bind:this={paneHost}
        hidden={strip}
        data-terminal-role="primary"
        data-input-owner={inputFocus.owner === instance ? 'true' : null}
        onfocuscapture={takeFocus}
        onfocusincapture={takeFocus}
        onfocusoutcapture={dropFocus}
      ></div>
      {#if strip}
        <State inline title={t('opscenter.cell.terminal.too_short')} />
      {/if}
      <SkillsDrawer sessionId={shownSession} slot={instance} {width} />
    </div>
    {#if shownSession}
      <TerminalFoot sessionId={shownSession} {width} />
    {/if}
  </div>
{:else if drivesItsOwnSession(page)}
  <LiveCell {width} {height} {meta} {instance} {page} />
{:else}
  <ViewerCell {width} {height} {meta} {instance} {page} />
{/if}
</WidgetShell>

<style>
  @layer components {
    .oc-tl {
      display: flex;
      flex-direction: column;
      min-height: 0;
      height: 100%;
      gap: 0;
    }

    .cc-pane {
      display: flex;
      flex-direction: column;
      flex: 1;
      min-width: 0;
      min-height: 0;
    }

    .cc-pane[hidden] {
      display: none;
    }

  }
</style>
