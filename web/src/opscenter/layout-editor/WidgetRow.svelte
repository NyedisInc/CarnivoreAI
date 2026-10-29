<script lang="ts">
  /* the widgets page */
  import type { GroupRow } from './drawer-groups';
  import Icon from '../ui/Icon.svelte';
  import WidgetIcon from '../ui/WidgetIcon.svelte';
  import { hasOptions } from '../../lib/widget-menu/option-nodes';
  import { highlightParts } from './drawer-fuzzy';
  import WidgetDescriptionCard from '../widgets/info/WidgetDescriptionCard.svelte';
  import { t } from '../../lib/i18n/index.svelte';

  let {
    row,
    page,
    expanded = null,
    indices = [],
    onpointerdown,
    onclick,
  }: {
    row: GroupRow;
    page: string;
    expanded?: boolean | null;
    indices?: readonly number[];
    onpointerdown?: (event: PointerEvent) => void;
    onclick: () => void;
  } = $props();

  let describing = $state(false);

  const configurable = $derived(hasOptions(row.manifest, row.manifest, true));
  const nameParts = $derived(highlightParts(row.title, indices));
  const baseLabel = $derived(
    row.state === 'refused'
      ? t('layout_editor.card.refused', { title: row.title, reason: row.reason })
      : row.family
        ? t('layout_editor.card.add_copy', { title: row.title })
        : row.state === 'addable'
          ? t('layout_editor.card.add', { title: row.title })
          : t('layout_editor.card.placed', { title: row.title }),
  );
  const label = $derived(configurable ? `${baseLabel}, ${t('layout_editor.row.options')}` : baseLabel);
  const count = $derived(
    row.placed === 0
      ? ''
      : row.placed === 1
        ? t('layout_editor.card.on_page', { page })
        : t('layout_editor.card.on_page_count', { page, count: row.placed }),
  );
  const cardId = $derived(`le-desc-${row.widgetId.replace(/[^A-Za-z0-9_-]/g, '-')}`);
</script>

<div class="le-wrow" class:le-wrow--open={describing}>
  <button
    type="button"
    class="le-card le-row"
    class:le-row--refused={row.state === 'refused'}
    data-widget={row.widgetId}
    data-state={row.state}
    data-type={row.type}
    data-family={row.family ? '' : undefined}
    aria-disabled={row.state === 'refused'}
    aria-expanded={expanded ?? undefined}
    aria-label={label}
    title={row.sentence || undefined}
    {onpointerdown}
    {onclick}
  >
    <span class="le-ico" style={`color: var(--${row.manifest.iconTone})`} data-widget-icon={row.manifest.icon} aria-hidden="true">
      <WidgetIcon name={row.manifest.icon} widget={row.manifest.id} size={18} />
    </span>
    <span class="le-card__text">
      <span class="le-card__name">{#each nameParts as part, at (at)}{#if part.hit}<mark class="le-hit">{part.text}</mark>{:else}{part.text}{/if}{/each}{#if configurable}<span class="le-opts" data-widget-options title={t('layout_editor.row.options')}><Icon name="settings" size={11} /></span>{/if}</span>
      {#if row.state === 'refused'}
        <span class="le-card__meta le-row__reason" data-refusal={row.refusal}>{row.reason}</span>
      {:else if count}
        <span class="le-row__count">{count}</span>
      {/if}
    </span>
    {#if expanded !== null}
      <span class="le-row__chev" class:le-row__chev--open={expanded} aria-hidden="true"></span>
    {/if}
  </button>
  <button
    type="button"
    class="le-row__info"
    data-widget-info-open={row.widgetId}
    aria-expanded={describing}
    aria-controls={cardId}
    aria-label={t(describing ? 'layout_editor.row.info_close' : 'layout_editor.row.info', { title: row.title })}
    title={t('layout_editor.row.info', { title: row.title })}
    onclick={() => (describing = !describing)}
  >
    <Icon name="info" size={13} />
  </button>
</div>
{#if describing}
  <div class="le-row__card" id={cardId}>
    <WidgetDescriptionCard manifest={row.manifest} />
  </div>
{/if}

<style>
  @layer components {
  .le-wrow {
    display: flex;
    align-items: stretch;
    gap: 2px;
  }

  .le-wrow > :global(.le-row) {
    flex: 1 1 auto;
    min-width: 0;
    min-height: 30px;
    padding: 3px 6px;
    gap: var(--oc-space-2);
  }


  .le-row__reason {
    color: var(--oc-text-muted);
  }

  .le-ico {
    display: inline-flex;
    flex: none;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border: var(--oc-border, 1px) solid var(--oc-line-rule);
    border-radius: var(--oc-radius-sm, 2px);
    background: var(--oc-ground-raised);
  }

  .le-opts {
    display: inline-flex;
    vertical-align: middle;
    margin-left: var(--oc-space-1);
    color: var(--oc-cyan);
  }

  .le-hit {
    background: transparent;
    color: var(--oc-orange);
    text-decoration: underline;
    text-underline-offset: 2px;
  }

  .le-row__count {
    font-size: var(--oc-fs-micro);
    letter-spacing: var(--oc-tracking-label, 0.6px);
    color: var(--oc-green);
  }


  .le-row__info {
    display: inline-flex;
    flex: none;
    align-items: center;
    justify-content: center;
    width: 24px;
    padding: 0;
    border: var(--oc-border, 1px) solid transparent;
    border-radius: var(--oc-radius-sm, 2px);
    background: transparent;
    color: var(--oc-text-muted);
    cursor: pointer;
  }

  .le-row__info:hover,
  .le-wrow--open .le-row__info {
    border-color: var(--oc-line-rule);
    color: var(--oc-text-primary);
  }

  .le-row__card {
    margin: 2px 0 var(--oc-space-2) 0;
    padding: var(--oc-space-2) var(--oc-space-2) var(--oc-space-2) var(--oc-space-3);
    box-shadow: inset 1px 0 0 var(--oc-line-rule);
  }

  :global(.le-drawer) .le-row.le-row--refused {
    opacity: 0.5;
    background-image: repeating-linear-gradient(
      135deg,
      transparent 0 6px,
      color-mix(in srgb, var(--oc-line-rule) 45%, transparent) 6px 7px
    );
    cursor: not-allowed;
  }

  .le-row__chev {
    flex-shrink: 0;
    width: 7px;
    height: 7px;
    margin: 0 2px 0 var(--oc-space-1);
    border-right: 1px solid var(--oc-text-muted);
    border-bottom: 1px solid var(--oc-text-muted);
    transform: rotate(-45deg);
    transition: transform var(--oc-motion-fast, 120ms) ease;
  }

  .le-row__chev--open {
    transform: rotate(45deg);
  }
  }
</style>
