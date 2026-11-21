<script lang="ts">
  /* there is nothing */
  import { setContext, type Snippet } from 'svelte';
  import { t } from '../sdk';
  import { RailResizeHandle } from '../sdk/ui';
  import type { DrawerDock } from './lab-selection';
  import type { LabIcon } from '../sdk/widget-lab';
  import DockBar from './DockBar.svelte';
  import { KEY_MENU_CONTEXT, createKeyMenuBridge } from './key-menu-bridge';

  interface Props {
    dock: Exclude<DrawerDock, 'left'>;
    title: string;
    icon?: LabIcon;
    children: Snippet;
  }

  const { dock, title, icon, children }: Props = $props();

  const keyMenu = createKeyMenuBridge();
  setContext(KEY_MENU_CONTEXT, keyMenu);
</script>

{#snippet grip(edge: 'side' | 'bottom')}
  <div class="dwl-dock-grip" inert><RailResizeHandle {edge} label={t('widget_bars.edge')} /></div>
{/snippet}

{#if dock === 'right'}
  <div class="dwl-dock dwl-dock--right" data-dock="right">
    <div class="dwl-dock-panel dwl-dock-panel--side">
      {@render grip('side')}
      <div class="dwl-chrome-body dwl-dock-slot">{@render children()}</div>
    </div>
    <DockBar edge="side" keys={['files']} lit={icon?.name ?? null} litTone={icon?.tone ?? null} litLabel={title} onlitmenu={keyMenu.request} />
  </div>
{:else}
  <div class="dwl-dock dwl-dock--bottom" data-dock="bottom">
    <div class="dwl-dock-panel dwl-dock-panel--bottom">
      {@render grip('bottom')}
      <div class="dwl-chrome-body dwl-dock-slot">{@render children()}</div>
    </div>
    <DockBar edge="bottom" keys={['terminal', 'code']} lit={icon?.name ?? null} litTone={icon?.tone ?? null} litLabel={title} onlitmenu={keyMenu.request} />
  </div>
{/if}
