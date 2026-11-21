<script lang="ts">
  import type { Snippet } from 'svelte';
  import { t } from '../sdk';
  import { Button } from '../sdk/ui';
  import type { DrawerDock } from './lab-selection';
  import type { LabIcon } from '../sdk/widget-lab';
  import DockBar from './DockBar.svelte';
  import DrawerChrome from './DrawerChrome.svelte';

  interface Props {
    host: string;
    dock?: DrawerDock;
    title: string;
    icon?: LabIcon;
    children: Snippet;
  }

  const { host, dock = 'left', title, icon, children }: Props = $props();
</script>

<div class="dwl-chrome dwl-chrome--{host}" data-chrome={host} data-dock={host === 'drawer' ? dock : undefined}>
  {#if host === 'drawer' && dock === 'left'}
    {@render children()}
  {:else if host === 'drawer' && dock !== 'left'}
    <DrawerChrome {dock} {title} {icon}>{@render children()}</DrawerChrome>
  {:else}
    {#if host === 'popout'}
      <header class="dwl-chrome-window" inert>
        <span class="dwl-chrome-window-title">{title}</span>
        <Button size="sm" tabindex={-1}>{t('cplug.devwidgetlab.chrome.focus_main')}</Button>
      </header>
    {/if}

    <div class="dwl-chrome-body">{@render children()}</div>

    {#if host === 'terminal'}
      <DockBar edge="bottom" keys={['terminal', 'code']} />
    {/if}
  {/if}
</div>
