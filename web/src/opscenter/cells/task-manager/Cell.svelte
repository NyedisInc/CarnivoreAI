<script lang="ts">
  import type { CellProps } from '../../lib/cell';
  import HuddleBody from '../../../cplugs/huddle/HuddleBody.svelte';
  import { activeTerminalSessionId } from '../../lib/active-terminal';
  import { sessions } from '../../api';
  import { sessionScopeFor } from '../../widgets/session-scope';
  import { t } from '../../../lib/i18n/index.svelte';

  let { scope = null }: CellProps = $props();

  const resolved = $derived(scope ?? sessionScopeFor(sessions.data, activeTerminalSessionId()));
  const list = $derived(resolved?.projectId == null ? null : String(resolved.projectId));
</script>

<div class="oc-hdl" data-task-manager-cell={list ?? ''}>
  {#if list === null}
    <p class="oc-hdl-note" role="status">{t(resolved ? 'opscenter.cell.task_manager.no_project' : 'opscenter.cell.task_manager.no_session')}</p>
  {:else}
    {#key list}<HuddleBody {list} />{/key}
  {/if}
</div>

<style>
  @layer components {
    .oc-hdl { display: flex; flex-direction: column; height: 100%; min-height: 0; }

    .oc-hdl-note { margin: 0; padding: var(--oc-space-1) 6px; color: var(--oc-text-dim); font-family: var(--font-mono); font-size: var(--oc-fs-label); }
  }
</style>
