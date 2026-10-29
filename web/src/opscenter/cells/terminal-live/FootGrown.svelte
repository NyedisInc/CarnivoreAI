<script lang="ts">
  import type { sessionUsageLabels, SessionTokenUsage } from '../../api';
  import { t } from '../../../lib/i18n/index.svelte';
  import { IconButton } from '../../../lib/base';
  import ControlCenter from '../../../lib/session-control/ControlCenter.svelte';
  import FootStats from './FootStats.svelte';
  import type { ControlSection, SessionControlOption } from '../../../lib/session-control/control-center';

  let {
    regionId,
    style,
    stacked,
    expanded,
    model,
    payload,
    sessionId,
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
    focus: ControlSection | null;
    openOption: SessionControlOption;
    onclose: () => void;
  } = $props();
</script>


<div id={regionId} class="oc-tf-grown" {style} data-stacked={stacked ? 'true' : 'false'}
  data-scroll-box role="group" aria-label={t('usage.foot.details')} hidden={!expanded}>
  {#if expanded}
    
    <span class="oc-tf-close">
      <IconButton label={t('usage.foot.close')} variant="close" icon="close" iconSize={14} onclick={() => onclose()} />
    </span>
    
    <FootStats {model} {payload} layout={stacked ? 'tiles' : 'band'} oncollapse={() => onclose()} />
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
    /*  hidden  overflow:
       hidden */
    .oc-tf-grown {
      position: absolute;
      left: 0;
      right: 0;
      bottom: 0;
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      grid-template-rows: auto minmax(0, 1fr);
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

    /* position: absolute */
    .oc-tf-close {
      position: absolute;
      top: 4px;
      right: 6px;
      z-index: 2;
      display: inline-flex;
    }

    .oc-tf-close:hover,
    .oc-tf-close:focus-visible {
      color: var(--oc-text-primary);
    }
  }
</style>
