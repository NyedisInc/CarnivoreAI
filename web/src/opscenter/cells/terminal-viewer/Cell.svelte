<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';

  export const TERMINAL_VIEWER_WIDGET = defineWidget({ id: 'core.terminal', scope: 'global', actions: [], state: {} });
</script>

<script lang="ts">
  /* and the real */
    import type { CellProps } from '../../lib/cell';
  import { atLeast } from '../../lib/states';
  import { sessions, statusHue, statusLabel, openSession, type StatusHue } from '../../api';
  import { hostOffline, usageLimitLabel } from '../../../lib/led';
  import { createViewerSocket, type ViewerSocket, type ViewerState } from '../../lib/viewer-socket';
  import { inputFocus } from '../../lib/input-focus.svelte';
  import {
    letterbox,
    rowFor,
    sessionIdOf,
    showsReadOnlyNotice,
    VIEWER_ACCEPTS_INPUT,
    VIEWER_KEYS,
  } from './meta';
  import { showsStatusLight } from '../../../lib/sessions/agent-marks';
  import { t } from '../../../lib/i18n/index.svelte';
  import State from '../../../lib/base/State.svelte';
  import { useTabPane } from '../../shell/frame-header.svelte';
  import { viewport } from '../../engine/viewport.svelte';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import { useWidget } from '../../widgets/shell/define-widget.svelte';

  let { width, height, meta, instance, page = 'home' }: CellProps = $props();

  const widget = useWidget(TERMINAL_VIEWER_WIDGET, () => ({ width, height, meta, instance }));
  const frameHeader = widget.frame;
  const tabPane = useTabPane();
  const headUp = $derived(!!frameHeader?.drawn && !viewport.phone && (!tabPane || tabPane.active));
  $effect(() => {
    if (!frameHeader || !headUp) return;
    frameHeader.content = viewerHead;
    return () => {
      if (frameHeader.content === viewerHead) frameHeader.content = null;
    };
  });

  // the page terminal
  $effect(() => {
    const slot = instance;
    return () => inputFocus.forget(slot);
  });

  const sessionId = $derived(sessionIdOf(instance, sessions.data));

  const widthState = $derived(widget.widthState);
  const heightState = $derived(widget.heightState);

  const showsPane = $derived(atLeast(meta.heightStates, heightState, 'pane'));
  const showsStatusWord = $derived(atLeast(meta.widthStates, widthState, 'wide'));

  const row = $derived(rowFor(sessions.data, sessionId));
  const missing = $derived(sessions.status === 'ok' && sessionId !== '' && row === null);

  const hue = $derived<StatusHue>(
    row ? statusHue(row.activity_status, row.startup_gate, row.unread, hostOffline(row), usageLimitLabel(row)) : 'grey',
  );
  const statusWord = $derived(
    row ? statusLabel(row.activity_status, row.startup_gate, row.unread, hostOffline(row), row.activity_hint, usageLimitLabel(row)) : '',
  );
  const name = $derived((row?.label ?? '').trim() || sessionId);

  let socketState = $state<ViewerState>('connecting');
  let paneWidth = $state(0);
  let paneHeight = $state(0);
  let bodyHeight = $state(0);

  const dead = $derived(missing || socketState === 'gone');
  const fit = $derived(letterbox(width, bodyHeight, paneWidth, paneHeight));
  const subtitleKey = $derived(
    socketState === 'reconnecting'
      ? VIEWER_KEYS.reconnecting
      : socketState === 'connecting'
        ? VIEWER_KEYS.connecting
        : '',
  );

  let stage = $state<HTMLDivElement | null>(null);
  let bodyEl = $state<HTMLDivElement | null>(null);

  $effect(() => {
    const el = bodyEl;
    if (!el) return;
    const measure = (): void => {
      bodyHeight = el.offsetHeight || 0;
    };
    measure();
    const RO = (globalThis as { ResizeObserver?: typeof ResizeObserver }).ResizeObserver;
    const observer = typeof RO === 'function' ? new RO(measure) : null;
    observer?.observe(el);
    return () => {
      observer?.disconnect();
      bodyHeight = 0;
    };
  });

  const live = $derived(sessionId !== '' && showsPane && !dead && stage !== null);

  function monoFace(): string {
    const root = (globalThis as { document?: Document }).document?.documentElement;
    const view = root?.ownerDocument?.defaultView;
    if (!root || !view) return '';
    return view.getComputedStyle(root).getPropertyValue('--font-mono').replace(/\s+/g, ' ').trim();
  }

  const TERM_OPTIONS = {
    fontSize: 14,
    fontWeight: 'normal',
    fontWeightBold: 'bold',
    scrollback: 50000,
    disableStdin: !VIEWER_ACCEPTS_INPUT,
    cursorBlink: false,
    cursorStyle: 'bar',
    allowTransparency: true,
    theme: { background: 'rgba(0,0,0,0)' },
  };

  const acceptsInput = VIEWER_ACCEPTS_INPUT;

  $effect(() => {
    if (!live) return;
    const target = stage;
    const Ctor = (globalThis as { Terminal?: new (options: unknown) => unknown }).Terminal;
    if (!target || typeof Ctor !== 'function') return;
    const face = monoFace();
    const term = new Ctor(face ? { ...TERM_OPTIONS, fontFamily: face } : TERM_OPTIONS) as {
      open(el: HTMLElement): void;
      resize(cols: number, rows: number): void;
      write(data: Uint8Array | string): void;
      onData(handler: (data: string) => void): { dispose(): void };
      dispose(): void;
    };
    term.open(target);

    const handleWheel = (ev: WheelEvent): void => {
      if (!ev || ev.deltaY === 0) return;
      if (ev.cancelable) ev.preventDefault();
      ev.stopPropagation();
      const step = (
        globalThis as {
          TerminalScrollStep?: { rowsForWheel(ev: WheelEvent, term: unknown, root?: ParentNode): number };
        }
      ).TerminalScrollStep;
      const rows = step ? step.rowsForWheel(ev, term, target) : 0;
      if (!rows) return;
      (term as unknown as { scrollLines(amount: number): void }).scrollLines(rows);
    };
    target.addEventListener('wheel', handleWheel, { capture: true, passive: false });

    const measure = (): void => {
      paneWidth = target.offsetWidth || 0;
      paneHeight = target.offsetHeight || 0;
    };
    measure();
    const RO = (globalThis as { ResizeObserver?: typeof ResizeObserver }).ResizeObserver;
    const observer = typeof RO === 'function' ? new RO(measure) : null;
    observer?.observe(target);

    let view: ViewerSocket | null = createViewerSocket({
      sessionId,
      term,
      interactive: VIEWER_ACCEPTS_INPUT,
      onState: (next) => {
        socketState = next;
      },
      onGrid: measure,
    });
    view.start();

    const typing = term.onData((data: string) => {
      const ticket = view?.claimInput();
      if (!view || !ticket) return;
      if (inputFocus.owner !== instance) return;
      view.send(data, ticket);
    });

    return () => {
      typing.dispose();
      target.removeEventListener('wheel', handleWheel, { capture: true });
      inputFocus.release(instance);
      observer?.disconnect();
      view?.destroy();
      view = null;
      paneWidth = 0;
      paneHeight = 0;
    };
  });

  const owned = $derived(inputFocus.owner === instance);

  function takeFocus(): void {
    inputFocus.claim(instance);
  }

  function dropFocus(event: FocusEvent): void {
    const next = event.relatedTarget;
    const body = event.currentTarget;
    if (next instanceof Node && body instanceof Node && body.contains(next)) return;
    inputFocus.release(instance);
  }

  function act(): void {
    openSession(sessionId, row?.tmux_session ?? null);
  }
</script>

{#snippet viewerHead()}
  <div class="oc-tv-head" class:oc-tv-head--up={headUp}>
    {#if showsStatusLight(row?.agent_family)}
    <span class="oc-tv-dot" class:oc-tv-dot-hollow={hue === 'grey' && !row} style={`--oc-dot-color:${
      hue === 'green'
        ? 'var(--oc-green-bright)'
        : hue === 'yellow'
          ? 'var(--oc-yellow-bright)'
          : hue === 'blue'
            ? 'var(--oc-cyan)'
            : hue === 'red'
              ? 'var(--oc-coral)'
              : 'var(--oc-text-dim)'
    }`}></span>
    {/if}
    <span class="oc-tv-name">{name}</span>
    {#if showsStatusWord && statusWord && showsStatusLight(row?.agent_family)}
      <span class="oc-tv-status">{statusWord}</span>
    {:else if statusWord}
      <span class="oc-visually-hidden">{statusWord}</span>
    {/if}
    {#if subtitleKey && !dead}
      <span class="oc-tv-subtitle">{t(subtitleKey)}</span>
    {/if}
    <span class="oc-tv-tail">
      
      {#if showsReadOnlyNotice(acceptsInput, dead)}
        <span class="oc-tv-readonly" data-viewer-input="none">{t(VIEWER_KEYS.readOnly)}</span>
      {/if}
      <!-- there is nothing -->
      {#if page !== 'terminal'}
        <button class="oc-tv-action" data-btn="secondary" data-size="sm" type="button" onclick={act} disabled={sessionId === ''}
          >{t(VIEWER_KEYS.open)}</button
        >
      {/if}
    </span>
  </div>
{/snippet}

<WidgetShell {widget} bare>
<div class="oc-tv" class:oc-tv-strip={!showsPane}>
  {#if !headUp}{@render viewerHead()}{/if}

  {#if dead}
    <State inline data-viewer-state="dead" title={t(VIEWER_KEYS.gone, { action: t(VIEWER_KEYS.remove) })} />
  {:else if !showsPane}
    <State inline data-viewer-state="strip" title={t(VIEWER_KEYS.tooShort)} />
  {:else}
    
    <div
      class="oc-tv-body"
      data-viewer-state="pane"
      bind:this={bodyEl}
      data-input-owner={owned ? 'true' : null}
      onfocuscapture={takeFocus}
      onfocusincapture={takeFocus}
      onfocusoutcapture={dropFocus}
    >
      <div
        class="oc-tv-stage xterm-host"
        bind:this={stage}
        style={`transform:scale(${fit.scale});left:${fit.left}px;top:${fit.top}px`}
      ></div>
    </div>
  {/if}
</div>
</WidgetShell>

<style>
  @layer components {
    .oc-tv {
      display: flex;
      flex-direction: column;
      min-height: 0;
      height: 100%;
      gap: var(--oc-space-1);
    }

    .oc-tv-head {
      display: flex;
      align-items: center;
      gap: calc(var(--oc-space-1-5) + var(--oc-border));
      padding: var(--oc-space-1) calc(var(--oc-space-2) + var(--oc-space-0-5)) 0;
      min-width: 0;
      flex: 0 0 auto;
    }

    .oc-tv-head--up {
      flex: 1 1 auto;
      padding: 0;
    }

    .oc-tv-head--up .oc-tv-name {
      color: var(--oc-orange);
    }

    .oc-tv-dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      flex: 0 0 auto;
      background: var(--oc-dot-color);
    }

    .oc-tv-dot-hollow {
      background: transparent;
      box-shadow: inset 0 0 0 1.5px var(--oc-dot-color);
    }

    .oc-tv-name {
      font-size: var(--oc-fs-label);
      color: var(--oc-text-primary);
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
      min-width: 0;
    }

    .oc-tv-status,
    .oc-tv-subtitle {
      font-size: var(--oc-fs-label);
      color: var(--oc-text-dim);
      white-space: nowrap;
      flex: 0 0 auto;
    }

    .oc-tv-tail {
      margin-left: auto;
      flex: 0 0 auto;
      display: flex;
      align-items: center;
      gap: calc(var(--oc-space-1-5) + var(--oc-border));
    }

    .oc-tv-readonly {
      font-size: var(--oc-fs-label);
      color: var(--oc-text-dim);
      opacity: 0.75;
      white-space: nowrap;
    }

    .oc-tv-action {
      flex: 0 0 auto;
    }

    .oc-tv-body {
      position: relative;
      flex: 1 1 auto;
      min-height: 0;
      overflow: hidden;
    }

    .oc-tv-stage {
      position: absolute;
      top: 0;
      left: 0;
      transform-origin: top left;
    }

    .oc-visually-hidden {
      position: absolute;
      width: 1px;
      height: 1px;
      overflow: hidden;
      clip-path: inset(50%);
      white-space: nowrap;
    }
  }
</style>
