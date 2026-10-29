<script lang="ts">
  import type { Snippet } from 'svelte';
  import { ApiError, addTerminalCell, declareWidgetActions, useFrameHeader, forwardMenuKey, menuRightClick, openSession, promptText, sessionRow, t, terminalAvailable, type DeclaredAction, type MenuNode, type PluginMenu } from '../../sdk';
  import { IconButton, MachineBadge, SessionFace, TaskMark } from '../../sdk/ui';
  import { exportAgent, renameAgent, sleepAgent, turnOffAgent, wakeAgent, type SwarmAgentDetail } from './chat-api';
  import { menuActions, menuHasRewind, menuHasTurnOff, type ChatMenuExtra } from './chat-model';
  import type { ChatStore } from './chat-store.svelte';
  import { refreshRoster } from '../agents/agent-roster.svelte';
  import RewindPicker from './RewindPicker.svelte';
  import MemoryPanel from './MemoryPanel.svelte';

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

  let rewindOpen = $state(false);
  let bar = $state<HTMLElement | null>(null);
  let memoryOpen = $state(false);

  function failure(error: unknown, key: string): string {
    return error instanceof ApiError && error.message ? error.message : t(key);
  }

  async function run(action: 'sleep' | 'wake_fresh' | 'resume'): Promise<void> {
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
    if (agentId === null) return;
    onNotice('');
    try {
      const typed = isLeader ? await askLeaderName() : undefined;
      if (isLeader && typed === null) return;
      await turnOffAgent(agentId, typed ?? undefined);
    } catch (error) {
      onNotice(failure(error, 'cplug.huddle.chat.turn_off.failed'));
    }
    await Promise.all([chat?.refresh(), refreshRoster()]);
  }

  async function exportCraft(): Promise<void> {
    if (agentId === null) return;
    onNotice('');
    try {
      await exportAgent(agentId, name);
    } catch (error) {
      onNotice(failure(error, 'cplug.huddle.chat.export_failed'));
    }
  }

  async function openTerminal(): Promise<void> {
    const sessionId = agent?.session_id;
    if (!sessionId) return;
    onNotice('');
    if (store && typeof (store as { add?: unknown }).add === 'function') {
      onNotice(addTerminalCell(store as Parameters<typeof addTerminalCell>[0], sessionId));
    } else if (agent?.tmux_session || row?.tmux_session) {
      if (await openSession(sessionId, agent?.tmux_session ?? row?.tmux_session ?? '')) onOpenedTerminal?.();
    }
  }

  async function rename(): Promise<void> {
    if (agentId === null) return;
    const raw = await promptText({
      title: t('leader.rename.title'), label: t('leader.rename.label'), defaultValue: name,
      confirmLabel: t('leader.rename.save'), cancelLabel: t('leader.confirm.cancel'),
    });
    const next = (raw ?? '').trim();
    if (!next || next === name) return;
    onNotice('');
    try {
      await renameAgent(agentId, next);
    } catch (error) {
      onNotice(failure(error, 'leader.rename.failed'));
    }
    await Promise.all([chat?.refresh(), refreshRoster()]);
  }

  function agentMenu(): PluginMenu | null {
    if (!hasMenu) return null;
    const nodes: MenuNode[] = actions.map((action) => ({ id: action.replace('_', '-'), label: t(`cplug.huddle.chat.menu_${action}`), run: () => void run(action) }));
    if (canTerminal) nodes.push({ id: 'terminal', label: t('cplug.huddle.chat.terminal'), title: t('cplug.huddle.chat.terminal_title'), run: () => void openTerminal() });
    for (const item of extra) nodes.push({ id: item.key, label: item.label, run: item.run });
    if (canRewind) {
      nodes.push({ id: 'rewind', label: t('cplug.huddle.chat.menu_rewind'), run: () => (rewindOpen = true) });
      nodes.push({ id: 'export', label: t('cplug.huddle.chat.menu_export'), run: () => void exportCraft() });
    }
    if (canRename && agentId !== null) nodes.push({ id: 'rename-agent', label: t('leader.rename.menu'), run: () => void rename() });
    if (canTurnOff) {
      const label = t('cplug.huddle.chat.menu_turn_off');
      nodes.push(isLeader
        ? { id: 'turn-off-agent', label, danger: true, sep: true, run: () => void turnOff() }
        : { id: 'turn-off-agent', label, danger: true, sep: true, children: [
            { id: 'turn-off-confirm', label: t('cplug.huddle.chat.turn_off.confirm', { name }), danger: true, run: () => void turnOff() },
          ] });
    }
    return { label: t('cplug.huddle.chat.menu'), nodes };
  }

  const frame = useFrameHeader();
  const declared = $derived<DeclaredAction[]>((agentMenu()?.nodes ?? []).flatMap((node) => (node.run && !node.children ? [{ id: node.id, label: node.label, run: node.run, group: 'agent' }] : [])));
  $effect(() => (frame && declared.length > 0 ? declareWidgetActions(frame.hostId, 'agent', declared) : undefined));

  function barDown(event: PointerEvent): void {
    if (onBarDown && event.button === 0 && !(event.target as HTMLElement).closest('button')) onBarDown(event);
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<header class="hdc-bar" class:hdc-bar--framed={framed} class:hdc-bar--titled={titled} class:hdc-bar--drag={!!onBarDown}
        data-chat-bar onpointerdown={barDown} bind:this={bar} onkeydown={(event) => forwardMenuKey(event, hasMenu ? bar : null)}
        {...menuRightClick(agentMenu)}>
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
  {#if agentId !== null && agent && agent.state !== 'torn_down'}
    
    <span class="hdc-brain"><IconButton label={t('cplug.huddle.chat.memory.open')} icon="brain" variant="quiet" iconSize={14}
                                          pressed={memoryOpen} data-chat-memory onclick={() => (memoryOpen = !memoryOpen)} /></span>
  {/if}
  {@render trail?.()}
</header>

{#if memoryOpen && agentId !== null}
  <MemoryPanel {agentId} {name} onclose={() => (memoryOpen = false)} />
{/if}

{#if rewindOpen && agentId !== null}
  <RewindPicker {agentId} agentState={agent?.state ?? null} onClose={() => (rewindOpen = false)}
                onDone={(text) => { onNotice(text); void chat?.refresh(); }} />
{/if}

<style>
  @layer components {
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


    .hdc-brain { display: inline-flex; flex: none; }
    .hdc-brain :global([data-btn]) { color: var(--oc-pink); }

    @media (pointer: fine) {
      .hdc-bar :global(.oc-btn) { min-height: 0; }
      .hdc-bar :global(.oc-ibtn) { width: var(--oc-ibtn-size, 20px); height: var(--oc-ibtn-size, 20px); }
    }
  }
</style>
