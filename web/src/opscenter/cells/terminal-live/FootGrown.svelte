<script lang="ts">
  import type { sessionUsageLabels, SessionTokenUsage } from '../../api';
  import { t } from '../../../lib/i18n/index.svelte';
  import { IconButton } from '../../../lib/base';
  import ControlCenter from '../../../lib/session-control/ControlCenter.svelte';
  import FootStats from './FootStats.svelte';
  import { sessions } from '../../api';
  import { rowFor } from '../terminal-viewer/meta';
  import { argentCost } from '../../../lib/argent-cost/cost-store.svelte';
  import { agentSplitView, argentCostView } from '../../../lib/argent-cost/cost-view';
  import { useAgentWatch } from '../../../lib/argent-cost/agent-watch.svelte';
  import type { ControlSection, SessionControlOption } from '../../../lib/session-control/control-center';

  let {
    regionId,
    style,
    stacked,
    expanded,
    model,
    payload,
    sessionId,
    createdAt = null,
    focus,
    openOption,
    onclose,
  }: {
    regionId: string;
    style: string;
    stacked: boolean;
    expanded: boolean;
    model: ReturnType<typeof sessionUsageLabels>;
    payload: SessionTokenUsage | null;
    sessionId: string;
    createdAt?: string | null;
    focus: ControlSection | null;
    openOption: SessionControlOption;
    onclose: () => void;
  } = $props();

  const argent = $derived(expanded ? argentCostView(argentCost().data, rowFor(sessions.data, sessionId)?.session_row_id) : null);
  const argentAgents = $derived(expanded ? agentSplitView(argentCost().data, rowFor(sessions.data, sessionId)?.session_row_id) : null);
  useAgentWatch(() => (expanded ? rowFor(sessions.data, sessionId)?.session_row_id : null));
</script>


<div id={regionId} class="oc-tf-grown" {style} data-stacked={stacked ? 'true' : 'false'}
  data-scroll-box role="group" aria-label={t('usage.foot.details')} hidden={!expanded}>
  {#if expanded}
    
    <div class="oc-tf-head">
      <h3 class="oc-tf-title">{t('usage.foot.title')}</h3>
      <span class="oc-tf-close">
        <IconButton label={t('usage.foot.close')} variant="close" icon="close" iconSize={14} onclick={() => onclose()} />
      </span>
    </div>
    
    <FootStats {model} {payload} {createdAt} {argent} {argentAgents} layout={stacked ? 'tiles' : 'band'} oncollapse={() => onclose()} />
    <ControlCenter {sessionId} {focus} layout={
      stacked ? 'accordion'
        : openOption === 'b' ? 'tabs'
        : openOption === 'c' ? 'owner-list'
        : 'columns'
    } />
  {/if}
</div>

<style>
  @layer components {
    .oc-tf-grown {
      position: absolute;
      left: 0;
      right: 0;
      bottom: 0;
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      grid-template-rows: auto auto minmax(0, 1fr);
      overflow: hidden;
      background: var(--oc-ground-titlerow);
      border-top: 1px solid var(--oc-line-rule);
    }

    .oc-tf-grown[data-stacked='true'] {
      grid-template-rows: none;
      overflow-y: auto;
    }

    .oc-tf-grown[hidden] {
      display: none;
    }

    .oc-tf-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--oc-space-2);
      min-height: var(--oc-titlerow-h);
      padding: 0 var(--oc-space-2) 0 var(--oc-space-3);
      box-shadow: inset 0 -1px 0 0 var(--oc-line-rule);
    }

    .oc-tf-title {
      margin: 0;
      font-family: var(--font-mono, monospace);
      font-size: var(--oc-fs-title);
      font-weight: 400;
      letter-spacing: var(--oc-tracking-title, 0.8px);
      text-transform: uppercase;
      color: var(--oc-orange);
      white-space: nowrap;
    }

    .oc-tf-close {
      display: inline-flex;
    }

    .oc-tf-close:hover,
    .oc-tf-close:focus-visible {
      color: var(--oc-text-primary);
    }
  }
</style>
