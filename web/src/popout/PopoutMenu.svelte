<script lang="ts">
  /* pop-out window */
  import type { WidgetManifest } from '../opscenter/widgets/types';
  import { t } from '../lib/i18n/index.svelte';
  import DeclaredTabMenu from '../lib/zone-shell/DeclaredTabMenu.svelte';
  import PlacementMenuHost from '../lib/zone-shell/PlacementMenuHost.svelte';
  import { focusMainWindow, hasMainWindow } from './popout';

  let {
    hostId,
    title,
    anchor,
    onClose,
    manifest = undefined,
    view = null,
    pickView = undefined,
    win = window,
  }: {
    hostId: string;
    title: string;
    anchor: HTMLElement | null;
    onClose: () => void;
    manifest?: WidgetManifest;
    view?: string | null;
    pickView?: (view: string) => void;
    win?: Window;
  } = $props();

  const own = $derived({
    focusMain: hasMainWindow(win) ? () => void focusMainWindow(win) : null,
    close: { run: () => win.close() },
  });
</script>

{#if manifest}
  <PlacementMenuHost
    host="popout"
    bodyHost="popout"
    {manifest}
    {view}
    placementKey={manifest.id}
    {pickView}
    extras={{ popOut: null, ...own }}
    {anchor}
    label={t('opscenter.frame.options', { title })}
    {onClose}
  />
{:else}
  <DeclaredTabMenu {hostId} extras={own} {anchor} label={t('opscenter.frame.options', { title })} {onClose} />
{/if}
