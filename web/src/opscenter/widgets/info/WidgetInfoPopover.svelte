<script lang="ts">
  /* the settings overlay the widgets page */
  import AnchoredPopup from '../../../lib/dialog-frame/AnchoredPopup.svelte';
  import Button from '../../../lib/base/Button.svelte';
  import { t } from '../../../lib/i18n/index.svelte';
  import { openWidgets } from '../../api/host';
  import { closeConfigure } from '../chrome/configure.svelte';
  import { sheetPlacement, type SheetPlacement } from '../chrome/sheet-placement';
  import type { WidgetManifest } from '../types';
  import WidgetInfoCard from './WidgetInfoCard.svelte';
  import { widgetInfo } from './widget-info';

  let { manifest, anchor }: { manifest: WidgetManifest; anchor: HTMLElement | null } = $props();

  const info = $derived(widgetInfo(manifest));
  let box = $state<HTMLElement | null>(null);
  let place = $state<SheetPlacement>({ mode: 'right', left: 0, top: 0, width: 0, height: 0 });

  function measure(): void {
    if (!anchor || typeof window === 'undefined') return;
    const rect = anchor.getBoundingClientRect();
    place = sheetPlacement(
      { left: rect.left, top: rect.top, width: rect.width, height: rect.height },
      { width: window.innerWidth, height: window.innerHeight },
      box?.offsetHeight ?? 0,
    );
  }

  function onCatalog(): void {
    closeConfigure();
    openWidgets();
  }
</script>

<AnchoredPopup
  bind:element={box}
  class="oc-winfo-pop"
  data-info-popover={manifest.id}
  topLayer
  label={t('widgets.info.title', { title: t(manifest.titleKey) })}
  tabindex={-1}
  {anchor}
  placement="manual"
  style={`left: ${Math.round(place.left)}px; top: ${Math.round(place.top)}px; width: ${Math.round(place.width)}px;`}
  onPlace={measure}
  initialFocus="button"
  onClose={closeConfigure}
>
  <div class="oc-winfo-pop-body"><WidgetInfoCard {info} hide={['sizes']} /></div>
  <footer class="oc-winfo-pop-foot">
    <Button size="sm" data-info-catalog onclick={onCatalog}>{t('widgets.info.open_catalog')}</Button>
    <Button size="sm" data-info-close onclick={closeConfigure}>{t('widgets.info.close')}</Button>
  </footer>
</AnchoredPopup>

<style>
  @layer components {
    :global(.oc-winfo-pop) {
      position: fixed;
      inset: auto;
      margin: 0;
      z-index: 50;
      display: flex;
      flex-direction: column;
      max-height: calc(100vh - var(--oc-space-4));
      padding: 0;
      border-radius: var(--oc-radius-sm);
      overflow: auto;
    }

    .oc-winfo-pop-body {
      padding: var(--oc-space-3);
    }

    .oc-winfo-pop-foot {
      display: flex;
      justify-content: flex-end;
      gap: var(--oc-space-2);
      padding: var(--oc-space-2);
      box-shadow: inset 0 1px 0 var(--oc-line-rule);
    }
  }
</style>
