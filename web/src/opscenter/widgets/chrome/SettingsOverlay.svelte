<script module lang="ts">
  import type { SettingValue } from '../../../lib/item-settings/api';
  import type { WidgetSettingsSchema } from '../types';

  export interface PlacementOptionsHost {
    schema: WidgetSettingsSchema;
    values: Readonly<Record<string, SettingValue>>;
    onChange: (key: string, value: SettingValue | null) => void;
    onReset: () => void;
    onClose: () => void;
    optionLabel?: (key: string, option: string) => string | undefined;
  }
</script>

<script lang="ts">
  import type { Snippet } from 'svelte';
  import AnchoredPopup from '../../../lib/dialog-frame/AnchoredPopup.svelte';
  import Button from '../../../lib/base/Button.svelte';
  import SettingsForm from '../../../lib/item-settings/SettingsForm.svelte';
  import {
    createItemSettingsController,
    type ItemSettingsController,
  } from '../../../lib/item-settings/item-settings-controller.svelte';
  import { t } from '../../../lib/i18n/index.svelte';
  import { closeConfigure } from './configure.svelte';
  import { sheetPlacement, type SheetPlacement } from './sheet-placement';

  let {
    widgetId,
    title,
    anchor,
    hasSchema,
    panel = null,
    controller,
    placement = null,
  }: {
    widgetId: string;
    title: string;
    anchor: HTMLElement | null;
    hasSchema: boolean;
    panel?: Snippet | null;
    controller?: ItemSettingsController;
    placement?: PlacementOptionsHost | null;
  } = $props();

  function close(): void {
    if (placement) placement.onClose();
    else closeConfigure();
  }

  // svelte-ignore state_referenced_locally
  const ctl: ItemSettingsController | null = hasSchema && !placement ? (controller ?? createItemSettingsController('widget', widgetId, t)) : null;
  // svelte-ignore state_referenced_locally
  if (ctl && ctl.status === 'loading' && !ctl.item) void ctl.load();

  const schema = $derived(ctl?.item?.schema ?? null);

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

  $effect(() => {
    if (!anchor || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(anchor);
    return () => observer.disconnect();
  });
</script>


<AnchoredPopup
  bind:element={box}
  class="oc-configure"
  data-configure-sheet={widgetId}
  data-settings-overlay={widgetId}
  data-sheet-mode={place.mode}
  topLayer
  label={t('widgets.configure.title', { title })}
  tabindex={-1}
  {anchor}
  placement="manual"
  style={`left: ${Math.round(place.left)}px; top: ${Math.round(place.top)}px; width: ${Math.round(place.width)}px;${place.mode === 'overlay' ? ` height: ${Math.round(place.height)}px;` : ''}`}
  onPlace={measure}
  initialFocus={'input, select, textarea, [role="radio"], [role="switch"], button'}
  outside="none"
  returnFocus={false}
  onClose={close}
>
  <header class="oc-configure-head">
    <span class="oc-configure-label">{t('widgets.configure.label')}</span>
    <span class="oc-configure-name">{title}</span>
  </header>
  <div class="oc-configure-body oc-wso">
    {#if placement}
      <SettingsForm
        schema={placement.schema}
        values={placement.values}
        idPrefix={`wso-${widgetId.replace(/[^a-z0-9-]/gi, '-')}`}
        heading={false}
        optionLabel={placement.optionLabel}
        {t}
        onChange={placement.onChange}
      />
    {:else if ctl?.status === 'error'}
      <p class="sf__error" role="alert" data-settings-load-error>{t('item_settings.error.load_named', { reason: ctl.loadError ?? '' })}</p>
      <Button size="sm" onclick={() => void ctl?.load()}>{t('item_settings.retry')}</Button>
    {:else if ctl?.item && schema}
      {#if ctl.notice}<p class="sf__notice" role="status">{ctl.notice}</p>{/if}
      <SettingsForm
        {schema}
        values={ctl.item.values}
        dropped={ctl.item.dropped}
        busyKey={ctl.busyKey}
        error={ctl.fieldError}
        idPrefix={`wso-${widgetId.replace(/[^a-z0-9-]/gi, '-')}`}
        heading={false}
        {t}
        onChange={(key, value) => void ctl?.change(key, value)}
      />
    {/if}
    {#if panel}<div class="oc-configure-panel" data-settings-panel>{@render panel()}</div>{/if}
  </div>
  <footer class="oc-configure-foot">
    {#if placement}
      <Button data-configure-reset disabled={Object.keys(placement.values).length === 0} onclick={placement.onReset}>{t('widgets.configure.reset')}</Button>
    {:else if ctl}
      <Button data-configure-reset disabled={!ctl.hasChoices || ctl.busyKey !== null} onclick={() => void ctl?.reset()}>{t('widgets.configure.reset')}</Button>
    {/if}
    <Button variant="confirm" data-configure-done onclick={close}>{t('widgets.configure.done')}</Button>
  </footer>
</AnchoredPopup>

<style>
  @layer components {
    :global(.oc-configure) {
      position: fixed;
      inset: auto;
      margin: 0;
      z-index: 50;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr) auto;
      max-height: calc(100vh - var(--oc-space-4));
      padding: 0;
      border-radius: var(--oc-radius-sm);
      font-family: var(--oc-font);
      overflow: hidden;
    }

    .oc-configure-head {
      display: flex;
      align-items: center;
      gap: var(--oc-space-2);
      height: 26px;
      padding: 0 var(--oc-space-2);
      background: var(--oc-ground-titlerow);
      box-shadow: inset 0 -1px 0 var(--oc-line-rule);
    }

    .oc-configure-label {
      color: var(--oc-orange);
      font-size: var(--oc-fs-micro);
      letter-spacing: var(--oc-tracking-caps);
      text-transform: uppercase;
    }

    .oc-configure-name {
      min-width: 0;
      overflow: hidden;
      color: var(--oc-text-primary);
      font-size: var(--oc-fs-label);
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .oc-configure-body {
      --pl-line: var(--oc-line-rule);
      --pl-text: var(--oc-text-primary);
      --pl-muted: var(--oc-text-secondary);
      --pl-dim: var(--oc-text-muted);
      --pl-high: var(--oc-coral);
      --pl-raised: var(--oc-ground-raised);
      --pl-mono: var(--font-mono);
      min-height: 0;
      overflow: auto;
      padding: 0 var(--oc-space-2) var(--oc-space-2);
    }

    .oc-configure-panel {
      padding-top: var(--oc-space-2);
    }

    .oc-configure-foot {
      display: flex;
      justify-content: flex-end;
      gap: var(--oc-space-2);
      padding: var(--oc-space-2);
      box-shadow: inset 0 1px 0 var(--oc-line-rule);
    }
  }
</style>
