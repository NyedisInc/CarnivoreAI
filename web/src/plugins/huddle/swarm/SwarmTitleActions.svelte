<script lang="ts">
  import { openCplugPage, t } from '../../sdk';
  import { Icon } from '../../sdk/ui';
  import HuddleViewSwitch from '../HuddleViewSwitch.svelte';
  import { swarmView } from '../huddle-swarm-view.svelte';
  import { SWARM_PAGE } from './swarm-page';

  let { popout = false }: { popout?: boolean } = $props();
  const swarmOn = $derived(swarmView.view === 'swarm');
</script>

{#if !popout}
  <HuddleViewSwitch swarmSwitch viewKeys={false} density={swarmOn} />
  <button type="button" class="oc-ibtn oc-ibtn--bare pta-page" data-huddle-settings-page
          aria-label={t('cplug.huddle.swarm.settings.open')} onclick={() => void openCplugPage('huddle')}><Icon name="gear" size={12} /></button>
  {#if swarmOn}
    <button type="button" class="oc-ibtn oc-ibtn--bare pta-page" data-huddle-swarm-page title={t('cplug.huddle.swarm.page.open_title')}
            aria-label={t('cplug.huddle.swarm.page.open')} onclick={() => void openCplugPage(SWARM_PAGE)}><Icon name="grid" size={12} /></button>
  {/if}
{/if}

<style>
  @layer components {
    .pta-page {
      --oc-ibtn-size: 22px;
      color: var(--oc-text-muted);
    }

    .pta-page:hover {
      color: var(--oc-text-bright);
    }
  }
</style>
