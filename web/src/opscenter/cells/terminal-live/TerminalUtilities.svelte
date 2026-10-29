<script lang="ts">
  import { untrack } from 'svelte';
  import TerminalActions from './TerminalActions.svelte';
  import KeepAwakeIcon from '../../../lib/auto-sleep/KeepAwakeIcon.svelte';
  import { SLEEPABLE_FAMILIES } from '../../../lib/auto-sleep/auto-sleep-store.svelte';
  import BookmarkButtons from '../../../lib/bookmarks/BookmarkButtons.svelte';
  import { t } from '../../../lib/i18n/index.svelte';
  import { noteConnection, type Connection } from './connection.svelte';
  interface Controller {
    connectionStatus?: Connection;
    _currentTmuxName?(): string | null;
    _cellThemeManifest?(): { xterm?: Record<string, string> } | null;
    term?: { options?: { theme?: Record<string, string> } };
  }
  let { sessionId, controller, slot, width = 0, showsConnection = true, agentFamily = null, groupSlot = null, inHeader = false }:
    { sessionId: string; controller: unknown; slot: string; width?: number; showsConnection?: boolean; inHeader?: boolean;
      agentFamily?: string | null; groupSlot?: string | null } = $props();
  const client = $derived(controller as Controller | null);
  let connection: Connection | null = $state(null);
  const sessionName = $derived.by(() => {
    void connection;
    return client?._currentTmuxName?.() ?? null;
  });

  $effect(() => {
    const owner = client;
    void sessionId;
    connection = owner?.connectionStatus ?? null;
    const update = (event: Event): void => {
      const detail = (event as CustomEvent<Connection & { controller: unknown }>).detail;
      if (detail?.controller === owner) connection = { text: detail.text, className: detail.className };
    };
    window.addEventListener('cloude:terminal-connection', update);
    return () => window.removeEventListener('cloude:terminal-connection', update);
  });

  $effect(() => {
    const id = sessionId;
    const reported = connection;
    untrack(() => noteConnection(id, reported));
  });
  $effect(() => {
    const id = sessionId;
    return () => noteConnection(id, null);
  });
</script>

{#snippet utilityButtons()}
  
  {#if agentFamily === 'claude'}<BookmarkButtons {sessionName} />{/if}
  {#if agentFamily && SLEEPABLE_FAMILIES.includes(agentFamily)}<KeepAwakeIcon {sessionName} />{/if}
{/snippet}
<div class="oc-terminal-utilities" data-session-id={sessionId}>
  <TerminalActions
    {slot} {sessionId} {width} {groupSlot} {inHeader} {agentFamily} utilities={utilityButtons}
    {sessionName}
    getPalette={() => client?._cellThemeManifest?.()?.xterm ?? client?.term?.options?.theme}
  />
  {#if showsConnection}
  <span class="oc-connection" class:connected={connection?.className === 'connected'}
    class:error={connection?.className === 'error'} role="status"
    title={connection?.text ?? t('opscenter.topbar.connection.unknown')}
    aria-label={connection?.text ?? t('opscenter.topbar.connection.unknown')}>
    <span class="oc-connection-dot"></span>
    <span class="oc-connection-label">{connection?.text ?? t('opscenter.topbar.connection.unknown')}</span>
  </span>
  {/if}
</div>

<style>
  @layer components {
    .oc-terminal-utilities { display:flex; align-items:center; gap:5px; flex-shrink:0; }

    :global(.oc-frame-strip) .oc-terminal-utilities { align-self:stretch; }

    .oc-connection { display:inline-flex; align-items:center; gap:5px; color:var(--oc-text-dim); font-size:var(--oc-fs-micro); white-space:nowrap; }

    .oc-connection-dot { width:7px; height:7px; border-radius:50%; background:var(--oc-text-dim); }

    .connected .oc-connection-dot { background:var(--oc-green-bright); }

    .error .oc-connection-dot { background:var(--oc-coral); }

    @container (max-width:700px) { .oc-connection-label { display:none; } }
  }
</style>
