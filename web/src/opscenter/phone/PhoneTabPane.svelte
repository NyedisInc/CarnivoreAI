<script lang="ts">
  /* the live client */
  import { untrack } from 'svelte';
  import { phoneTabSource } from '../layouts/phone.svelte';
  import { PRIMARY_SLOT } from '../engine/model';
  import { sessions } from '../api';
  import { rowFor, sessionIdOf } from '../cells/terminal-viewer/meta';
  import { startLiveTerminal } from '../cells/terminal-live/client';
  import { bindTerminalTheme } from '../cells/terminal-live/theme';
  import { followTab, rejoinTab } from '../cells/terminal-group/tab-vote';
  import { inputFocus } from '../lib/input-focus.svelte';

  const active = $derived(phoneTabSource.active());
  const sessionId = $derived(active === PRIMARY_SLOT ? '' : sessionIdOf(active, sessions.data));
  const listed = $derived(!!sessionId && rowFor(sessions.data, sessionId) !== null);

  let host = $state<HTMLElement | null>(null);

  $effect(() => {
    if (!host || !listed) return;
    const tab = active;
    const el = host;
    const id = sessionId;
    return untrack(() => {
      const row = rowFor(sessions.data, id);
      const page = (globalThis as { TerminalController?: unknown }).TerminalController;
      followTab(page, PRIMARY_SLOT, { active: false });
      const live = startLiveTerminal(el, tab, row);
      const release = live ? bindTerminalTheme(live.client, el, { pinnedTheme: row?.pinned_theme ?? null }) : () => {};
      return () =>
        untrack(() => {
          release();
          live?.dispose();
          inputFocus.release(tab);
          rejoinTab(page);
        });
    });
  });
</script>

{#if sessionId}
  <div
    class="tw:absolute tw:inset-0 tw:z-[5] tw:flex tw:flex-col tw:min-h-0 tw:p-[15px] tw:bg-[var(--oc-ground-page)]"
    data-phone-tab-pane={active}
    data-theme-scope
    bind:this={host}
  ></div>
{/if}
