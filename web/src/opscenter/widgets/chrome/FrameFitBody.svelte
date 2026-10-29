<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { LayoutStore } from '../../engine/layout.svelte';
  import type { CellMeta } from '../../engine/types';
  import { sizeOf, surfaceKeyOf } from '../../engine/observe.svelte';
  import { viewport } from '../../engine/viewport.svelte';
  import { t } from '../../../lib/i18n/index.svelte';
  import { manifestForSlot } from '../core-manifests';
  import { META, metaFor } from '../../engine/meta';
  import { rowFloor } from '../../engine/model';
  import { GUTTER } from '../../engine/tracks';
  import { layoutEditor } from '../../layout-editor/editor.svelte';
  import {
    checkFit,
    fitsForSlot,
    isPopoutWindow,
    SIZE_UNIT_PX,
    suggestedSizes,
    unitsOfBox,
    zoneOfPage,
    type FitCheck,
  } from '../fits';
  import type { FitSize } from '../types';
  import { guideCandidates, guideFloor, pickTarget, resizeGuide, widthReach, type WidthReach } from './resize-hint';
  import { provideFrameGuide } from './resize-guide.svelte';
  import ResizeGuide from './ResizeGuide.svelte';
  import SettingsOverlay from './SettingsOverlay.svelte';
  import WidgetInfoPopover from '../info/WidgetInfoPopover.svelte';
  import RefusalPlate from './RefusalPlate.svelte';
  import { settingsPanelFor } from './settings-panels.svelte';
  import { closeConfigure, configureSheet } from './configure.svelte';
  import { reportWidget } from './report';

  let {
    meta,
    store,
    frame,
    titleRowPx,
    body,
  }: {
    meta: CellMeta;
    store: LayoutStore;
    frame: HTMLElement | null;
    titleRowPx: number;
    body: Snippet;
  } = $props();

  const zone = $derived(zoneOfPage(store.page, isPopoutWindow()));
  const fits = $derived(fitsForSlot(meta.id));

  const box = $derived.by(() => {
    const measured = sizeOf(meta.id);
    return viewport.wide && measured.width > 0 ? { width: measured.width, height: measured.height + titleRowPx } : null;
  });

  const check = $derived.by((): FitCheck => (fits ? checkFit(fits, box) : { ok: true }));

  const row = $derived(store.state.layout.rows.find((one) => one.slots.some((slot) => slot.id === meta.id)));
  const pixelRow = $derived(row?.kind === 'px' ? row : undefined);

  const guideFrame = provideFrameGuide();

  const floor = $derived(fits ? guideFloor(fits.min, row ? rowFloor(row, META) : null, guideFrame.bodyFloorPx, titleRowPx) : null);

  const reach = $derived.by((): WidthReach | null => {
    const surface = sizeOf(surfaceKeyOf(store.page)).width;
    if (!row || surface <= 0) return null;
    const neighbours = row.slots.filter((slot) => slot.id !== meta.id).map((slot) => metaFor(slot.id, META).minPx);
    return widthReach(surface, GUTTER, neighbours);
  });

  const candidates = $derived(fits && floor ? guideCandidates(suggestedSizes(fits), floor, reach) : []);
  const units = $derived(box ? unitsOfBox(box) : null);
  let heldTarget: FitSize | null = null;
  const target = $derived.by(() => (heldTarget = units ? pickTarget(heldTarget, units, candidates) : null));
  $effect(() => {
    guideFrame.guide = resizeGuide(units, target);
  });

  const editing = $derived(layoutEditor.active && layoutEditor.page === store.page);
  const plateShown = $derived(!check.ok || guideFrame.plates > 0);

  const canFix = $derived(
    !check.ok && check.reason === 'too-small' && !!pixelRow && !!check.has && !!fits && check.has.w >= fits.min.w,
  );

  function fix(size: FitSize): void {
    if (!pixelRow) return;
    store.setRowHeight(pixelRow.id, (target?.h ?? size.h) * SIZE_UNIT_PX.h);
    store.announce(t('widgets.refusal.fixed', { title: meta.titleName ?? t(meta.titleKey) }));
  }

  function report(): Promise<boolean> {
    const widget = manifestForSlot(meta.id)?.id;
    if (!widget || check.ok) return Promise.resolve(false);
    return reportWidget({ widget, zone, size: check.has, reason: check.reason });
  }

  const manifest = $derived(manifestForSlot(meta.id));
  const open = $derived(configureSheet.slot === meta.id ? configureSheet.kind : null);
  const hasSchema = $derived(!!manifest?.settings && Object.keys(manifest.settings.fields).length > 0);
  const panel = $derived(open === 'settings' ? settingsPanelFor(meta.id) : null);

  $effect(() => {
    if (open === 'settings' && !hasSchema && !panel) closeConfigure();
  });
</script>

{#if check.ok}
  {@render body()}
{:else}
  <RefusalPlate {check} sizes={fits?.sizes ?? []} onFix={canFix ? fix : undefined} onReport={report} />
{/if}
{#if guideFrame.guide && (plateShown || editing)}
  <ResizeGuide guide={guideFrame.guide} message={!plateShown} />
{/if}
{#if open === 'settings' && manifest && (hasSchema || panel)}
  <SettingsOverlay widgetId={manifest.id} title={meta.titleName ?? t(meta.titleKey)} anchor={frame} {hasSchema} {panel} />
{:else if open === 'info' && manifest}
  <WidgetInfoPopover {manifest} anchor={frame} />
{/if}
