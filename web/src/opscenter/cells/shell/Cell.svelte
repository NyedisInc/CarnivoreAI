<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';

  export const SHELL_WIDGET = defineWidget({ id: 'core.shell', scope: 'session', actions: [], state: {} });
</script>

<script lang="ts">
  import { untrack } from 'svelte';
  import type { CellProps } from '../../lib/cell';
  import { sessions } from '../../api';
  import { rowFor } from '../terminal-viewer/meta';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import { useWidget } from '../../widgets/shell/define-widget.svelte';
  import { inputFocus } from '../../lib/input-focus.svelte';
  import { startLiveTerminal, type LiveTerminal } from '../terminal-live/client';
  import { bindTerminalTheme } from '../terminal-live/theme';
  import { t } from '../../../lib/i18n/index.svelte';
  import State from '../../../lib/base/State.svelte';
  import { ensureShell, getShell, shellSlot, type CompanionShell } from './shell-api';

  let props: CellProps = $props();

  const widget = useWidget(SHELL_WIDGET, () => props);

  type Plate = 'no_agent' | 'starting' | 'live' | 'ended' | 'not_running' | 'remote' | 'error';

  const agentId = $derived(widget.sessionId);
  const row = $derived(rowFor(sessions.data, agentId));
  const remote = $derived(agentId.startsWith('remote:') || (!!row?.host_key && row.host_key !== 'local'));
  const absent = $derived(sessions.status === 'ok' && agentId !== '' && row === null && !agentId.startsWith('remote:'));
  const agentName = $derived((row?.label ?? '').trim() || agentId);

  let plate = $state<Plate>('no_agent');
  let shell = $state<CompanionShell | null>(null);
  let detail = $state('');
  let attempt = $state(0);
  let bodyEl = $state<HTMLDivElement | null>(null);

  $effect(() => {
    const id = agentId;
    void attempt;
    shell = null;
    detail = '';
    if (!id) { plate = 'no_agent'; return; }
    if (untrack(() => remote)) { plate = 'remote'; return; }
    if (absent) { plate = 'not_running'; return; }
    plate = 'starting';
    let stale = false;
    void ensureShell(id).then((out) => {
      if (stale) return;
      if (out.ok) { shell = out.shell; plate = 'live'; return; }
      detail = out.detail;
      plate = out.code === 'agent_not_running' ? 'not_running' : out.code === 'remote_agent' ? 'remote' : 'error';
    });
    return () => { stale = true; };
  });

  const shellKey = $derived(shell ? `${shell.session_id}\n${shell.tmux_session ?? ''}` : '');
  const slot = $derived(shell ? shellSlot(shell.session_row_id) : '');

  $effect(() => {
    if (plate !== 'live' || shellKey === '' || !bodyEl) return;
    const body = bodyEl;
    const target = untrack(() => shell);
    const owner = untrack(() => slot);
    if (!target) return;
    const el = document.createElement('div');
    el.className = 'shell-pane xterm-host';
    body.appendChild(el);
    const handle: LiveTerminal | null = startLiveTerminal(el, owner, target);
    liveClient = handle ? handle.client : null;
    if (!handle) {
      console.error('CloudeOpscenter: the terminal client is not on this page, so the shell widget drew nothing');
      return () => el.remove();
    }
    const stopTheme = bindTerminalTheme(handle.client, body, { pinnedTheme: null });
    return () => {
      liveClient = null;
      stopTheme();
      inputFocus.forget(owner);
      handle.dispose();
      el.remove();
    };
  });

  let recheckTimer: ReturnType<typeof setTimeout> | undefined;
  let liveClient: unknown = null;
  function recheck(): void {
    const id = untrack(() => agentId);
    if (plate !== 'live' || !id) return;
    clearTimeout(recheckTimer);
    recheckTimer = setTimeout(() => {
      void getShell(id).then((now) => {
        if (id === untrack(() => agentId) && plate === 'live' && now?.pane === 'dead') plate = 'ended';
      });
    }, 700);
  }
  $effect(() => {
    if (plate !== 'live') return;
    const onConnection = (event: Event): void => {
      const detail = (event as CustomEvent<{ className?: string; controller?: unknown }>).detail;
      if (detail && detail.className !== 'connected' && detail.controller === liveClient) recheck();
    };
    window.addEventListener('cloude:terminal-connection', onConnection);
    return () => { window.removeEventListener('cloude:terminal-connection', onConnection); clearTimeout(recheckTimer); };
  });

  function takeFocus(): void {
    recheck();
    if (slot) inputFocus.claim(slot);
  }

  function dropFocus(event: FocusEvent): void {
    const next = event.relatedTarget;
    if (next instanceof Node && event.currentTarget instanceof Node && event.currentTarget.contains(next)) return;
    if (slot) inputFocus.release(slot);
  }
</script>

<WidgetShell {widget} bare>
<div class="shell-cell" data-shell-cell data-plate={plate} data-agent={agentId || undefined}>
  {#if plate === 'live'}
    <div
      class="shell-cell__body"
      data-terminal-role="primary"
      data-shell-slot={slot}
      bind:this={bodyEl}
      onfocuscapture={takeFocus}
      onfocusincapture={takeFocus}
      onfocusoutcapture={dropFocus}
      onkeydowncapture={(event) => { if (event.key === 'Enter') recheck(); }}
    ></div>
  {:else}
    {#if plate === 'no_agent'}
      <State inline title={t('shell_widget.no_agent')} />
    {:else if plate === 'starting'}
      <State kind="loading" inline title={t('shell_widget.starting')} />
    {:else if plate === 'ended'}
      <State inline title={t('shell_widget.ended')} actionLabel={t('shell_widget.start_again')} onAction={() => { attempt += 1; }} />
    {:else if plate === 'not_running'}
      <State inline title={t('shell_widget.not_running', { agent: agentName })} actionLabel={t('shell_widget.retry')} onAction={() => { attempt += 1; }} />
    {:else if plate === 'remote'}
      <State inline title={t('shell_widget.remote')} />
    {:else}
      <State kind="error" inline title={t('shell_widget.error', { detail })} actionLabel={t('shell_widget.retry')} onAction={() => { attempt += 1; }} />
    {/if}
  {/if}
</div>
</WidgetShell>

<style>
  @layer components {
    .shell-cell { display: flex; flex-direction: column; height: 100%; min-height: 0; min-width: 0; }

    .shell-cell__body { position: relative; flex: 1 1 auto; min-height: 0; min-width: 0; display: flex; flex-direction: column; overflow: hidden; }

    .shell-cell__body :global(.shell-pane) { position: relative; flex: 1 1 auto; min-height: 0; min-width: 0; padding-left: var(--oc-terminal-inset); display: flex; flex-direction: column; justify-content: flex-end; }
  }
</style>
