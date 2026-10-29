<script lang="ts">
  /**
   * THE ONE title bar of an agent chat (#1435: "remove the second bar ... combine every kebab
   * menu into one"): the agent's status light LEFT of its name, the host's tabs, the "waiting on me" filter, ONE kebab
   * menu, and the host's trailing keys (a drawer's close).
   *
   * Description: the light is the shared `SessionFace` (light only, which draws the one `StatusLed`) handed the agent's
   *   pushed listing row WHOLE, so every signal rides together; an agent with no live row (asleep) shows the idle light, and the "asleep" words are
   *   gone. The kebab holds the agent's own actions (sleep, wake, resume, rewind, export, rename, turn off), "open
   *   terminal" where this window has a terminal, and the host's items (`extra`: pop out, agent terminal, make widget),
   *   so no host draws a second menu. COPIED, NOT INVENTED: the strip is the ledger's `.pl-titlebar` (fixed height,
   *   title-row ground, a hairline by box-shadow), the menu the cell menu's raised 1px frame with hairline rows
   *   (`client/css/session-row-menu.css`), the name the strip's one accent-colored thing.
   * Inputs: agentId; agent (the chat store's agent, null while loading); chat (the store, for a re-read after an action);
   *   waitingOnly (bindable filter); waiting (cards waiting on the owner); store (the layout store, for "open terminal"
   *   as a cell); onOpenedTerminal; onNotice (a failed action's sentence); extra (the host's menu items); tabs, trail
   *   (snippets: the host's tabs after the name, its keys after the menu); onBarDown (a press on the bare strip);
   *   framed (the frame's strip: the inactive-tab ground, so its tabs read); titled (a page already shows the name).
   */
  import { onMount, type Snippet } from 'svelte';
  import { ApiError, addTerminalCell, openSession, sessionRow, t, terminalAvailable } from '../../sdk';
  import { Icon, MachineBadge, SessionFace, TaskMark } from '../../sdk/ui';
  import { exportAgent, sleepAgent, turnOffAgent, wakeAgent, type SwarmAgentDetail } from './chat-api';
  import { menuActions, menuHasRewind, menuHasTurnOff, type ChatMenuExtra } from './chat-model';
  import type { ChatStore } from './chat-store.svelte';
  import { refreshRoster } from '../agents/agent-roster.svelte';
  import LeaderRename from './LeaderRename.svelte';
  import RewindPicker from './RewindPicker.svelte';

  interface Props {
    agentId: number | null;
    agent: SwarmAgentDetail | null;
    chat: ChatStore | null;
    waitingOnly?: boolean;
    waiting?: number;
    store?: unknown;
    onOpenedTerminal?: () => void;
    onNotice?: (text: string) => void;
    extra?: ChatMenuExtra[];
    tabs?: Snippet;
    trail?: Snippet;
    onBarDown?: (event: PointerEvent) => void;
    framed?: boolean;
    titled?: boolean;
  }

  let {
    agentId, agent, chat, waitingOnly = $bindable(false), waiting = 0, store, onOpenedTerminal, onNotice = () => {},
    extra = [], tabs, trail, onBarDown, framed = false, titled = false,
  }: Props = $props();

  const name = $derived(agent?.display_name ?? '');
  const actions = $derived(menuActions(agent?.state ?? null));
  const canRewind = $derived(menuHasRewind(agent?.state ?? null));
  const canTurnOff = $derived(menuHasTurnOff(agent?.state ?? null, agent?.rank ?? null));
  const isLeader = $derived(agent?.rank === 'alpha' || agent?.rank === 'company' || agent?.rank === 'project');
  const row = $derived(sessionRow(agent?.session_id ?? null) as (ReturnType<typeof sessionRow> & { unread?: boolean; status_source?: string | null }) | undefined);
  const canTerminal = $derived(terminalAvailable() && !!agent?.session_id && !extra.some((item) => item.key === 'terminal'));
  const canRename = $derived(!!agent && agent.state !== 'torn_down');
  const hasMenu = $derived(actions.length > 0 || canRewind || canTurnOff || canTerminal || extra.length > 0 || canRename);
  const status = $derived(row?.activity_status ?? (agent ? 'idle' : null));

  let menuOpen = $state(false);
  let rewindOpen = $state(false);
  let confirmOff = $state(false);

  onMount(() => {
    const close = (): void => { menuOpen = false; confirmOff = false; };
    document.addEventListener('click', close);
    return () => document.removeEventListener('click', close);
  });

  function failure(error: unknown, key: string): string {
    return error instanceof ApiError && error.message ? error.message : t(key);
  }

  async function run(action: 'sleep' | 'wake_fresh' | 'resume'): Promise<void> {
    menuOpen = false;
    if (agentId === null) return;
    onNotice('');
    try {
      if (action === 'sleep') await sleepAgent(agentId);
      else await wakeAgent(agentId, action === 'resume' ? 'resume' : 'fresh');
    } catch (error) {
      onNotice(failure(error, 'cplug.huddle.chat.action_failed'));
    }
    await Promise.all([chat?.refresh(), refreshRoster()]);
  }

  async function askLeaderName(): Promise<string | null> {
    const ask = (globalThis as { CloudeWeb?: { askLeaderConfirm?: (a: { name: string; rank: string; action: string }) => Promise<string | null> } }).CloudeWeb?.askLeaderConfirm;
    return ask ? ask({ name, rank: agent?.rank ?? '', action: 'turn off' }) : null;
  }

  async function turnOff(): Promise<void> {
    menuOpen = false;
    confirmOff = false;
    if (agentId === null) return;
    onNotice('');
    try {
      // project leader
      const typed = isLeader ? await askLeaderName() : undefined;
      if (isLeader && typed === null) return;
      await turnOffAgent(agentId, typed ?? undefined);
    } catch (error) {
      onNotice(failure(error, 'cplug.huddle.chat.turn_off.failed'));
    }
    await Promise.all([chat?.refresh(), refreshRoster()]);
  }

  async function exportCraft(): Promise<void> {
    menuOpen = false;
    if (agentId === null) return;
    onNotice('');
    try {
      await exportAgent(agentId, name);
    } catch (error) {
      onNotice(failure(error, 'cplug.huddle.chat.export_failed'));
    }
  }

  async function openTerminal(): Promise<void> {
    menuOpen = false;
    const sessionId = agent?.session_id;
    if (!sessionId) return;
    onNotice('');
    if (store && typeof (store as { add?: unknown }).add === 'function') {
      onNotice(addTerminalCell(store as Parameters<typeof addTerminalCell>[0], sessionId));
    } else if (agent?.tmux_session || row?.tmux_session) {
      if (await openSession(sessionId, agent?.tmux_session ?? row?.tmux_session ?? '')) onOpenedTerminal?.();
    }
  }

  function barDown(event: PointerEvent): void {
    if (onBarDown && event.button === 0 && !(event.target as HTMLElement).closest('button')) onBarDown(event);
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<header class="hdc-bar" class:hdc-bar--framed={framed} class:hdc-bar--titled={titled} class:hdc-bar--drag={!!onBarDown}
        data-chat-bar onpointerdown={barDown}>
  {#if !titled}
    <span class="hdc-who-led" data-chat-bar-led={status ?? 'none'}>
      <SessionFace row={{ ...(row ?? {}), activity_status: status }} />
    </span>
    <span class="hdc-name"><TaskMark rank={agent?.rank} />{name || t('cplug.huddle.chat.title')}</span>
  {/if}
  <MachineBadge hostKey={agent?.host_key} label={agent?.host_label} state={row?.host_state} />
  
  {#if agent?.state === 'torn_down'}<span class="hdc-state" data-agent-state="torn_down">{t('cplug.huddle.chat.state.torn_down')}</span>{/if}
  {@render tabs?.()}
  <span class="hdc-spacer"></span>
  <button type="button" class="oc-btn oc-btn--sm hdc-filter" aria-pressed={waitingOnly} title={t('cplug.huddle.chat.filter_label')}
          disabled={waiting === 0 && !waitingOnly} onclick={() => (waitingOnly = !waitingOnly)}>
    {waitingOnly ? t('cplug.huddle.chat.filter_all') : t('cplug.huddle.chat.filter_waiting', { count: waiting })}
  </button>
  {#if hasMenu}
    <div class="hdc-menu-wrap">
      <button type="button" class="oc-ibtn hdc-menu-key" aria-haspopup="menu" aria-expanded={menuOpen} data-chat-menu
              aria-label={t('cplug.huddle.chat.menu')}
              onclick={(event) => { event.stopPropagation(); menuOpen = !menuOpen; }}>
        <Icon name="kebab" size={14} />
      </button>
      {#if menuOpen}
        <ul class="hdc-menu" role="menu">
          {#each actions as action (action)}
            <li role="none"><button type="button" role="menuitem" class="hdc-menu-item" onclick={() => run(action)}>{t(`cplug.huddle.chat.menu_${action}`)}</button></li>
          {/each}
          {#if canTerminal}
            <li role="none"><button type="button" role="menuitem" class="hdc-menu-item hdc-terminal" title={t('cplug.huddle.chat.terminal_title')} onclick={openTerminal}>{t('cplug.huddle.chat.terminal')}</button></li>
          {/if}
          {#each extra as item (item.key)}
            <li role="none"><button type="button" role="menuitem" class="hdc-menu-item" data-chat-menu-extra={item.key}
                                    onclick={() => { menuOpen = false; item.run(); }}>{item.label}</button></li>
          {/each}
          {#if canRewind}
            <li role="none"><button type="button" role="menuitem" class="hdc-menu-item" onclick={() => { menuOpen = false; rewindOpen = true; }}>{t('cplug.huddle.chat.menu_rewind')}</button></li>
            <li role="none"><button type="button" role="menuitem" class="hdc-menu-item" onclick={exportCraft}>{t('cplug.huddle.chat.menu_export')}</button></li>
          {/if}
          {#if canRename && agentId !== null}
            <LeaderRename {agentId} {name} onDone={() => { menuOpen = false; void Promise.all([chat?.refresh(), refreshRoster()]); }} onFail={(error) => onNotice(failure(error, 'leader.rename.failed'))} />
          {/if}
          {#if canTurnOff}
            {#if confirmOff && !isLeader}
              <li role="none" class="hdc-confirm">
                <span class="hdc-confirm-text">{t('cplug.huddle.chat.turn_off.confirm', { name })}</span>
                <span class="hdc-confirm-row">
                  <button type="button" class="oc-btn oc-btn--sm hdc-confirm-no" onclick={(event) => { event.stopPropagation(); confirmOff = false; }}>{t('cplug.huddle.chat.turn_off.cancel')}</button>
                  <button type="button" class="oc-btn oc-btn--sm oc-btn--danger hdc-confirm-yes" onclick={turnOff}>{t('cplug.huddle.chat.turn_off.yes')}</button>
                </span>
              </li>
            {:else}
              <li role="none"><button type="button" role="menuitem" class="hdc-menu-item hdc-turn-off" onclick={(event) => { event.stopPropagation(); if (isLeader) void turnOff(); else confirmOff = true; }}>{t('cplug.huddle.chat.menu_turn_off')}</button></li>
            {/if}
          {/if}
        </ul>
      {/if}
    </div>
  {/if}
  {@render trail?.()}
</header>

{#if rewindOpen && agentId !== null}
  <RewindPicker {agentId} agentState={agent?.state ?? null} onClose={() => (rewindOpen = false)}
                onDone={(text) => { onNotice(text); void chat?.refresh(); }} />
{/if}

<style>
  @layer components {
    /* box-shadow */
    .hdc-bar {
      flex: none;
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
      height: 32px;
      padding: 0 8px;
      background: var(--oc-ground-titlerow);
      box-shadow: inset 0 -1px 0 var(--oc-line-rule);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-label);
    }

    .hdc-bar--framed { background: var(--oc-ground-tab-inactive); }
    .hdc-bar--drag { cursor: grab; }

    .hdc-bar--titled { background: transparent; }

    .hdc-who-led { display: inline-flex; flex: none; align-items: center; }

    .hdc-state {
      flex: none;
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-micro);
    }

    .hdc-name {
      flex: 0 1 auto;
      min-width: 0;
      overflow: hidden;
      color: var(--oc-orange);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.1em;
      text-overflow: ellipsis;
      text-transform: uppercase;
      white-space: nowrap;
    }

    .hdc-spacer { flex: 1; min-width: 0; }

    .hdc-filter {
      flex: 0 1 auto;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .hdc-menu-wrap { position: relative; flex: none; }

    .hdc-menu {
      position: absolute;
      top: 100%;
      right: 0;
      z-index: 5;
      min-width: 160px;
      margin: 4px 0 0;
      padding: 4px 0;
      list-style: none;
      border: 1px solid var(--oc-line-rule);
      border-radius: var(--oc-radius-sm, 2px);
      background: var(--oc-ground-raised);
    }

    .hdc-menu-item {
      display: block;
      width: 100%;
      padding: 4px 8px;
      border: 0;
      background: none;
      color: var(--oc-text-secondary);
      font: inherit;
      text-align: left;
      white-space: nowrap;
      cursor: pointer;
    }

    .hdc-menu > li + li { box-shadow: inset 0 1px 0 var(--oc-line-rule); }
    .hdc-menu-item:hover { color: var(--oc-text-bright); background: var(--oc-ground-field); }

    .hdc-confirm { width: 208px; display: flex; flex-direction: column; gap: 6px; padding: 6px 8px; border-top: 1px solid var(--oc-line-rule); }
    .hdc-confirm-text { color: var(--oc-text-secondary); }
    .hdc-confirm-no, .hdc-confirm-yes { flex: none; }
    .hdc-turn-off { color: var(--oc-coral); }
    .hdc-confirm-row { display: flex; gap: 6px; justify-content: flex-end; }

    @media (pointer: fine) {
      .hdc-bar :global(.oc-btn) { min-height: 0; }
      .hdc-bar :global(.oc-ibtn) { width: var(--oc-ibtn-size, 20px); height: var(--oc-ibtn-size, 20px); }
    }
  }
</style>
