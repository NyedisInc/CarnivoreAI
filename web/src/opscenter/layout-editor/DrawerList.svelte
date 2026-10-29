<script lang="ts">
  import type { ComponentProps } from 'svelte';
  import type { SlotId } from '../engine/types';
  import { t } from '../../lib/i18n/index.svelte';
  import type { CarryTarget } from './drawer-carry';
  import type { GroupRow } from './drawer-groups';
  import { buildView, isOpen, toggleFold, type ViewRow } from './drawer-view';
  import { widgetDrawerView } from './drawer-view-pref.svelte';
  import { WIDGET_TYPES, type WidgetType } from '../widgets/types';
  import Button from '../../lib/base/Button.svelte';
  import FoldChevron from '../ui/FoldChevron.svelte';
  import { watchCascadeHint } from '../../lib/sidebar-shell/cascade-hint';
  import WidgetRow from './WidgetRow.svelte';
  import WindowRows, { type WindowChoice, type WindowKind } from './WindowRows.svelte';
  import AnalyticsFamilyFold from './AnalyticsFamilyFold.svelte';

  let {
    windowKinds,
    picker,
    pickerRows,
    pickerTarget,
    pickerRefusal,
    onPickerCardDown,
    onPickerCardClick,
    onChoiceDown,
    onChoiceClick,
    view,
    query,
    needle,
    galleryOpen,
    familyOpen,
    onRowDown,
    onRowClick,
    inputs,
    onSurface,
    showAnalytics,
    pageName,
  }: {
    windowKinds: WindowKind[];
    picker: WindowKind | null;
    pickerRows: (kind: WindowKind) => WindowChoice[];
    pickerTarget: CarryTarget | null;
    pickerRefusal: string;
    onPickerCardDown: (event: PointerEvent, kind: WindowKind) => void;
    onPickerCardClick: (kind: WindowKind) => void;
    onChoiceDown: (event: PointerEvent, kind: WindowKind, choice: WindowChoice) => void;
    onChoiceClick: (kind: WindowKind, choice: WindowChoice) => void;
    view: ReturnType<typeof buildView>;
    query: string;
    needle: string;
    galleryOpen: boolean;
    familyOpen: (row: GroupRow) => boolean | null;
    onRowDown: (event: PointerEvent, row: GroupRow) => void;
    onRowClick: (row: GroupRow) => void;
    inputs: ComponentProps<typeof AnalyticsFamilyFold>['inputs'];
    onSurface: SlotId[];
    showAnalytics: boolean;
    pageName: string;
  } = $props();

  function onTypePress(event: MouseEvent, type: WidgetType): void {
    if (query.trim() !== '') return;
    widgetDrawerView.folded = toggleFold(widgetDrawerView.folded, type, WIDGET_TYPES, event.shiftKey);
  }
</script>

{#snippet widgetItem(one: ViewRow)}
  {@const row = one.row}
  <li>
    <WidgetRow
      {row}
      page={pageName}
      expanded={familyOpen(row)}
      indices={one.indices}
      onpointerdown={(event) => onRowDown(event, row)}
      onclick={() => onRowClick(row)}
    />
  </li>
  {#if row.widgetId === 'core.analytics' && row.state !== 'refused'}
    <AnalyticsFamilyFold open={galleryOpen || needle !== ''} {needle} matchesFamily={showAnalytics} {inputs} {onSurface} />
  {/if}
{/snippet}

    {#if windowKinds.length > 0}
      <li>
        <WindowRows
          kinds={windowKinds}
          open={picker}
          choices={pickerRows}
          aimed={pickerTarget !== null}
          refusal={pickerRefusal}
          onheaddown={onPickerCardDown}
          onhead={onPickerCardClick}
          onchoicedown={onChoiceDown}
          onchoice={onChoiceClick}
        />
      </li>
    {/if}
    {#if widgetDrawerView.mode === 'name'}
      {#each view.flat as one (one.row.widgetId)}
        {@render widgetItem(one)}
      {/each}
    {:else}
      {#each view.sections as section (section.type)}
        {@const open = isOpen(widgetDrawerView.folded, section.type, query)}
        <li class="le-type" data-drawer-type={section.type}>
          <div class="session-sidebar-group__headerrow le-type__head" data-band-kind="widget-type" {@attach watchCascadeHint}>
            <Button
              variant="row"
              aria-expanded={open}
              aria-controls={`le-type-${section.type}`}
              aria-label={t(open ? 'layout_editor.group.fold' : 'layout_editor.group.unfold', { group: t(`widgets.type.${section.type}`) })}
              data-drawer-type-toggle={section.type}
              onclick={(event) => onTypePress(event, section.type)}
            >
              <FoldChevron /><span class="session-sidebar-group__label">{t(`widgets.type.${section.type}`)}</span>
              <span class="le-type__count">{section.rows.length}</span>
            </Button>
          </div>
          {#if open}
            <ul class="le-type__body" id={`le-type-${section.type}`} aria-label={t('layout_editor.view.tree')}>
              {#each section.rows as one (one.row.widgetId)}
                {@render widgetItem(one)}
              {/each}
            </ul>
          {/if}
        </li>
      {/each}
    {/if}

<style>
  @layer components {
    .le-type {
      list-style: none;
    }

    [data-drawer-type-toggle] {
      flex: 1 1 auto;
      min-width: 0;
      min-height: 22px;
      padding: var(--oc-space-1) var(--oc-space-2) var(--oc-space-1) 0;
      gap: var(--sidebar-heading-inline-gap, 6px);
      align-items: center;
      font-size: var(--oc-fs-label);
      font-weight: bold;
      letter-spacing: 0.6px;
      text-transform: uppercase;
    }

    .le-type__count {
      margin-left: auto;
      font-size: var(--oc-fs-micro);
      color: var(--oc-text-muted);
    }

    .le-type__body {
      margin: 0 0 var(--oc-space-1) var(--oc-space-3);
      padding: 0;
      list-style: none;
      box-shadow: inset 1px 0 0 var(--oc-line-rule);
    }
  }
</style>
