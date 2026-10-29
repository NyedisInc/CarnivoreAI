<script lang="ts">
  /* pop-out window */
  import type { Snippet } from 'svelte';
  import Icon from '../ui/Icon.svelte';
  import IconButton from '../../lib/base/IconButton.svelte';
  import PhoneSummaryStrip from '../ui/PhoneSummary.svelte';
  import type { CellMeta, PhoneSummary } from '../engine/types';
  import type { FrameHeader } from './frame-header.svelte';
  import { HEAD_ROW_PX, headParts } from './widget-head';
  import { t } from '../../lib/i18n/index.svelte';

  let {
    meta = null,
    header,
    title,
    label = '',
    titleShort = '',
    count = null,
    suffix = null,
    collapsed = false,
    summary = null,
    phone = false,
    tap = false,
    bodyId = '',
    corner,
    onClose,
    withRight = true,
    bare = false,
    onGripDown,
    onToggleCollapse,
    onRightControl,
  }: {
    meta?: CellMeta | null;
    header: FrameHeader;
    title: string;
    label?: string;
    titleShort?: string;
    count?: number | null;
    suffix?: string | null;
    collapsed?: boolean;
    summary?: PhoneSummary | null;
    phone?: boolean;
    tap?: boolean;
    bodyId?: string;
    corner: Snippet | null;
    onClose: ((from: DOMRect) => void) | null;
    withRight?: boolean;
    bare?: boolean;
    onGripDown?: (event: PointerEvent) => void;
    onToggleCollapse?: () => void;
    onRightControl?: () => void;
  } = $props();
  const spoken = $derived(title || label);

  const options = $derived([header.action, ...header.groups].filter((one): one is Snippet => one !== null));

  const right = $derived.by((): 'collapse' | 'view-all' | 'word' | null => {
    const control = meta?.rightControl;
    if (!control || !withRight) return null;
    if (phone) return onRightControl && control !== 'collapse' ? 'word' : null;
    if (control === 'collapse') return 'collapse';
    return control === 'view-all' ? 'view-all' : 'word';
  });

  const controlLabel = $derived(
    meta?.rightControl === 'clear'
      ? t('opscenter.frame.clear')
      : meta?.rightControl === 'view-all'
        ? t('opscenter.frame.view_all')
        : meta?.rightControl === 'refresh'
          ? t('opscenter.frame.refresh')
          : '',
  );

  const closable = $derived(!phone && onClose !== null);
  const parts = $derived(headParts([...options.map(() => true), right !== null], closable));

  let head = $state<HTMLElement | null>(null);

  function onContextMenu(event: MouseEvent): void {
    if (event.defaultPrevented || (event.target as Element | null)?.closest('input, textarea, [contenteditable]')) return;
    const door = head?.querySelector<HTMLButtonElement>('[data-corner]');
    if (!door) return;
    event.preventDefault();
    if (door.getAttribute('aria-expanded') !== 'true') door.click();
  }

  function onCloseClick(event: MouseEvent): void {
    onClose?.((event.currentTarget as HTMLElement).getBoundingClientRect());
  }
</script>

{#snippet rightControl()}
  {#if right === 'collapse'}
    <button
      type="button"
      class="oc-btn oc-btn--tool oc-frame-control"
      aria-expanded={!collapsed}
      aria-controls={bodyId}
      aria-label={collapsed ? t('opscenter.frame.expand', { title: spoken }) : t('opscenter.frame.collapse', { title: spoken })}
      onclick={() => onToggleCollapse?.()}
    >
      <Icon name={collapsed ? 'chevron-down' : 'chevron-up'} size={15} />
    </button>
  {:else if right === 'view-all' && !phone}
    <button type="button" class="oc-btn oc-btn--tool oc-frame-control" onclick={onRightControl}
      >{controlLabel} <span class="oc-frame-control-arrow" aria-hidden="true">&#8594;</span></button
    >
  {:else}
    <button type="button" class="oc-btn oc-btn--tool oc-frame-control" onclick={onRightControl}>{controlLabel}</button>
  {/if}
{/snippet}

{#snippet closeButton()}
  <IconButton label={t('opscenter.frame.close', { title: spoken })} variant="close" icon="close" iconSize={13} data-head-close=""
    onclick={onCloseClick} />
{/snippet}

{#snippet cluster()}
  {#each parts as part, at (at)}
    {#if part.kind === 'sep'}
      <span class="oc-head-sep" role="separator" aria-orientation="vertical"></span>
    {:else if part.kind === 'close'}
      {@render closeButton()}
    {:else if part.at < options.length}
      <span class="oc-head-group">{@render options[part.at]?.()}</span>
    {:else}
      {@render rightControl()}
    {/if}
  {/each}
{/snippet}


<!-- svelte-ignore a11y_no_static_element_interactions -->
<header class="oc-frame-title" class:oc-frame-title--grip={!!onGripDown} class:oc-frame-title--phone={phone || tap} class:oc-frame-title--bare={bare} data-widget-head="" data-oc-base style:--oc-head-row={`${HEAD_ROW_PX}px`} bind:this={head} onpointerdown={onGripDown} oncontextmenu={onContextMenu}>
  {#if corner}{@render corner()}{/if}
  {#if header.content}
    {@render header.content()}
    {#if closable}{@render closeButton()}{/if}
  {:else if phone}
    
    <h2 class="oc-frame-name oc-frame-name-wrap">
      <button type="button" class="oc-frame-toggle" aria-expanded={!collapsed} aria-controls={bodyId} onclick={() => onToggleCollapse?.()}>
        <span class="oc-frame-nametext">{title}</span>
        {#if meta?.showCount && count !== null}<span class="oc-frame-count">{t('opscenter.frame.count', { count })}</span>{/if}
        {#if collapsed && summary}<PhoneSummaryStrip {summary} />{/if}
        
        <span class="oc-frame-chev" aria-hidden="true">
          <Icon name={collapsed ? 'chevron-down' : 'chevron-up'} size={15} />
        </span>
      </button>
    </h2>
    {@render cluster()}
  {:else}
    {#if titleShort}
      <!-- display: none -->
      <h2 class="oc-frame-name"><span class="oc-frame-name-full">{title}</span><span class="oc-frame-name-short">{titleShort}</span></h2>
    {:else}
      <h2 class="oc-frame-name">{title}</h2>
    {/if}
    <!-- could not -->
    {#if meta?.showCount && count !== null}
      <span class="oc-frame-count oc-frame-count-narrow-drop">{t('opscenter.frame.count', { count })}</span>
    {/if}
    {#if suffix}
      <span class="oc-frame-count oc-frame-suffix">{suffix}</span>
    {/if}
    <span class="oc-frame-spacer"></span>
    {@render cluster()}
  {/if}
</header>

<style>
  @layer components {
    .oc-frame-title {
      display: flex;
      flex: none;
      align-items: center;
      gap: var(--oc-space-2);
      min-width: 0;
      min-height: var(--oc-titlerow, var(--oc-head-row));
      box-sizing: border-box;
      padding: 0 var(--oc-widget-inset);
      background: var(--oc-ground-titlerow);
      box-shadow: inset 0 -1px 0 0 var(--oc-line-rule);
    }

    .oc-frame-title--bare {
      background: none;
      box-shadow: none;
    }

    .oc-frame-title--grip {
      touch-action: none;
      cursor: grab;
    }

    .oc-frame-name {
      --oc-frame-name-min: 5ch;
      margin: 0;
      font-size: var(--oc-fs-title);
      font-weight: 400;
      letter-spacing: var(--oc-tracking-title);
      text-transform: uppercase;
      color: var(--oc-orange);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .oc-frame-name-full,
    .oc-frame-name-short {
      display: block;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .oc-frame-name-short {
      display: none;
    }

    @container oc-head (max-width: 400px) {
      .oc-frame-name-full {
        display: none;
      }

      .oc-frame-name-short {
        display: block;
      }
    }

    @container oc-head (max-width: 240px) {
      .oc-frame-count-narrow-drop {
        display: none;
      }
    }

    .oc-frame-count {
      font-size: var(--oc-fs-title);
      color: var(--oc-text-secondary);
      white-space: nowrap;
    }

    .oc-frame-suffix {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .oc-frame-spacer {
      flex: 1 1 auto;
      min-width: 0;
    }

    .oc-frame-control {
      flex: 0 0.05 auto;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .oc-head-sep {
      flex: 0 0 auto;
      width: 1px;
      height: 14px;
      background: var(--oc-line-rule);
    }

    :global([data-head-close]) {
      --oc-ibtn-size: 20px;
      flex: 0 0 auto;
    }

    .oc-head-group {
      display: contents;
    }

    @container oc-head (max-width: 340px) {
      .oc-frame-control-arrow {
        display: none;
      }
    }

    @container oc-head (max-width: 440px) {
      .oc-frame-title :global(.oc-sort-wrap) {
        display: none;
      }

      .oc-head-group:has(> :global(.oc-sort-wrap):only-child) + .oc-head-sep,
      .oc-head-sep:has(+ .oc-head-group:last-child > :global(.oc-sort-wrap):only-child) {
        display: none;
      }
    }

    @container oc-head (max-width: 300px) {
      .oc-frame-title {
        gap: var(--oc-space-1);
      }

      .oc-frame-name {
        min-width: min(var(--oc-frame-name-min), 100%);
      }

      .oc-frame-control {
        flex-shrink: 0;
      }

      .oc-frame-title :global(.oc-frame-extra) {
        display: none;
      }
    }

    .oc-frame-toggle {
      position: relative;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      align-content: center;
      column-gap: 10px;
      row-gap: 2px;
      flex: 1 1 auto;
      min-width: 0;
      min-height: var(--oc-tap);
      padding: 0 21px 0 0;
      background: none;
      border: 0;
      color: var(--oc-orange);
      font: inherit;
      font-size: var(--oc-fs-title);
      font-weight: 400;
      letter-spacing: var(--oc-tracking-title);
      text-transform: uppercase;
      text-align: left;
      cursor: pointer;
    }

    .oc-frame-name-wrap {
      display: flex;
      flex: 1 1 auto;
      min-width: 0;
      margin: 0;
      font: inherit;
    }

    .oc-frame-nametext {
      flex: 0 1 auto;
      min-width: 0;
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
    }

    .oc-frame-chev {
      position: absolute;
      top: 0;
      right: 0;
      bottom: 0;
      display: inline-flex;
      align-items: center;
    }

    .oc-frame-toggle :global(.oc-psum) {
      flex: 0 1 auto;
      min-width: 0;
    }

    .oc-frame-title--phone .oc-frame-control {
      min-width: var(--oc-tap);
      min-height: var(--oc-tap);
      justify-content: center;
    }

    .oc-frame-title--phone {
      padding: 0 var(--oc-space-1) 0 2px;
      touch-action: auto;
      cursor: default;
    }
  }
</style>
