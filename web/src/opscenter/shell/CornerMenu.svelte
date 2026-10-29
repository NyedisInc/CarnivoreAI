<script lang="ts">
  import type { Snippet } from 'svelte';
  import Icon from '../ui/Icon.svelte';
  import WidgetIcon from '../ui/WidgetIcon.svelte';
  import type { CellMeta } from '../engine/types';
  import type { MenuSlot } from './widget-head';
  import { t } from '../../lib/i18n/index.svelte';

  type CornerMeta = Pick<CellMeta, 'icon' | 'iconFill' | 'cornerSlot'> & { id: string };

  let {
    meta,
    title,
    editing,
    place,
    menu = null,
    icon = null,
    phone = false,
    onGripDown,
    open = $bindable(false),
    anchor = $bindable(null),
  }: {
    meta: CornerMeta;
    title: string;
    editing: boolean;
    place: 'row' | 'bare';
    menu?: Snippet<[MenuSlot]> | null;
    icon?: string | null;
    phone?: boolean;
    onGripDown?: (event: PointerEvent) => void;
    open?: boolean;
    anchor?: HTMLElement | null;
  } = $props();

  const laid = $derived(place !== 'row');
  const slot = $derived(place === 'bare' ? (meta.cornerSlot ?? null) : null);
  const side = $derived(place === 'bare' && editing ? 'right' : 'left');
  const wrapStyle = $derived(slot ? `${side}:${slot[0]}px; top:${slot[1]}px; width:${slot[2]}px; height:${slot[2]}px` : undefined);
  const drawsIcon = $derived(place !== 'bare');
</script>

{#if !menu && !laid}
  
  <span class="oc-frame-corner oc-frame-corner--still" class:oc-frame-corner--tap={phone} aria-hidden="true">
    <WidgetIcon name={icon ?? meta.icon} widget={meta.id} size={15} fill={meta.iconFill ?? 'outline'} />
  </span>
{:else if menu && (!laid || slot)}
  <div class="oc-frame-cornerwrap" class:oc-frame-cornerwrap-bare={laid} style={wrapStyle}>
    <button
      type="button"
      class="oc-frame-corner"
      class:oc-frame-corner-bare={laid}
      class:oc-frame-corner--edit={editing}
      class:oc-frame-corner--tap={phone}
      data-corner=""
      data-edit-gear={editing ? '' : undefined}
      bind:this={anchor}
      aria-haspopup="menu"
      aria-expanded={open}
      aria-label={t('opscenter.frame.options', { title })}
      title={t('opscenter.frame.options_hint', { title })}
      onpointerdown={laid ? onGripDown : undefined}
      onclick={() => (open = !open)}
      oncontextmenu={(event) => {
        event.preventDefault();
        open = true;
      }}
    >
      {#if drawsIcon}
        <WidgetIcon name={editing ? 'gear' : (icon ?? meta.icon)} widget={editing ? null : meta.id} size={15} fill={editing ? 'outline' : (meta.iconFill ?? 'outline')} />
      {:else if editing}
        <Icon name="gear" size={15} />
      {/if}
    </button>
    {#if open}
      {@render menu({ anchor, close: () => (open = false) })}
    {/if}
  </div>
{/if}

<style>
  @layer components {
    .oc-frame-cornerwrap {
      position: relative;
      display: inline-flex;
      flex: 0 0 auto;
    }

    .oc-frame-corner {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 20px;
      height: 20px;
      padding: 0;
      background: none;
      box-sizing: border-box;
      border: 1px solid transparent;
      border-radius: var(--oc-radius-sm);
      color: var(--oc-text-secondary);
      cursor: pointer;
    }

    .oc-frame-corner--still {
      flex: 0 0 auto;
      cursor: default;
    }

    .oc-frame-corner:not(.oc-frame-corner--still):hover {
      background: var(--oc-ground-hover);
      color: var(--oc-text-primary);
    }

    .oc-frame-corner--edit,
    .oc-frame-corner-bare.oc-frame-corner--edit {
      color: var(--oc-cyan);
      background: none;
      border-color: transparent;
    }

    .oc-frame-corner--edit:hover {
      background: none;
      color: color-mix(in srgb, var(--oc-cyan) 70%, var(--oc-text-primary));
    }

    .oc-frame-corner-bare.oc-frame-corner--edit {
      width: 20px;
      height: 20px;
    }

    .oc-frame-cornerwrap-bare {
      position: absolute;
      z-index: 2;
    }

    .oc-frame-corner-bare {
      cursor: grab;
      width: 100%;
      height: 100%;
      border-radius: var(--oc-radius);
    }

    .oc-frame-corner-bare:hover {
      background: none;
      outline: 1px solid var(--oc-line-panel);
    }

    .oc-frame-corner--tap {
      min-width: var(--oc-tap);
      min-height: var(--oc-tap);
    }
  }
</style>
