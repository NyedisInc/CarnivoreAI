<script lang="ts" module>
  import type { KeyFace } from './zone-types';

  export function keyFace(words: { ariaLabel?: string; tip?: string; label?: string; icon?: string; count?: number | null }): KeyFace {
    const { ariaLabel = '', tip = '', label = '', icon = '', count } = words;
    return { title: ariaLabel || label, ariaLabel, tip, label, icon, count, chip: false, letter: '', tone: '' };
  }
</script>

<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { ClassValue } from 'svelte/elements';
  import Icon from '../../opscenter/ui/Icon.svelte';
  import WidgetIcon from '../../opscenter/ui/WidgetIcon.svelte';
  import ViewChip from '../widget-views/ViewChip.svelte';
  import PinnedKeyBadge from '../widget-bars/PinnedKeyBadge.svelte';
  import ZoneBadge from './ZoneBadge.svelte';
  import { isMenuKey } from './key-nav';
  import { buttonAttrs } from '../base/classes';
  import type { TabKeyClose, TabKeyShape, TabKeyState, TabKeyVariant } from './zone-types';

  interface KeyLook {
    key: string;
    ibtn?: boolean;
    open: string;
    label: string;
    tip: 'title' | 'data-tooltip';
    stop: 0 | null;
    zone: boolean;
  }

  const LOOK: Record<TabKeyVariant, KeyLook> = {
    bar: { key: 'rail__key', open: 'rail__key--open', label: 'rail__key-label', tip: 'title', stop: null, zone: true },
    rail: { key: 'sbr-rail__btn', open: '', label: '', tip: 'title', stop: 0, zone: false },
    strip: { key: 'oc-tab', open: 'oc-tab-active', label: 'oc-tab-name', tip: 'title', stop: 0, zone: false },
    glance: { key: 'dz-glance', open: '', label: '', tip: 'title', stop: null, zone: false },
    mini: { key: '', ibtn: true, open: '', label: '', tip: 'data-tooltip', stop: null, zone: false },
    topbar: { key: '', open: '', label: '', tip: 'title', stop: null, zone: false },
    phone: { key: '', open: '', label: '', tip: 'title', stop: null, zone: false },
  };

  interface CloseLook {
    key: string;
    ibtn?: boolean;
    armed: string;
    px: number;
    armedPx: number;
  }

  const CLOSE_LOOK: Partial<Record<TabKeyVariant, CloseLook>> = {
    strip: { key: 'oc-tab-x', armed: 'oc-tab-skull', px: 14, armedPx: 16 },
    rail: { key: 'sbr-rail__close', ibtn: true, armed: '', px: 10, armedPx: 10 },
  };

  let {
    id,
    shape = 'icon',
    variant,
    face,
    iconPx,
    labelAt = 'none',
    compact = false,
    quiet = false,
    state,
    active,
    tabbable,
    classes,
    style,
    attrs,
    frame = false,
    labelStyle,
    element = $bindable(),
    onpress,
    onfocus,
    onkey,
    onmenu,
    ondragstart,
    close,
    lead,
    tail,
    body,
  }: {
    id: string;
    shape?: TabKeyShape;
    variant: TabKeyVariant;
    face: KeyFace;
    iconPx: number;
    labelAt?: string;
    compact?: boolean;
    quiet?: boolean;
    state: TabKeyState | null;
    active: boolean;
    tabbable: boolean | null;
    classes?: ClassValue;
    style?: string;
    attrs?: Record<string, string | number | boolean | undefined>;
    frame?: boolean;
    labelStyle?: string;
    element?: HTMLElement | null;
    onpress?: (id: string, event: MouseEvent) => void;
    onfocus?: (id: string) => void;
    onkey?: (event: KeyboardEvent, id: string) => void;
    onmenu?: (id: string, anchor: HTMLElement, event: MouseEvent | KeyboardEvent) => boolean | void;
    ondragstart?: (event: PointerEvent, id: string) => void;
    close?: TabKeyClose;
    lead?: Snippet;
    tail?: Snippet;
    body?: Snippet;
  } = $props();

  const look = $derived(LOOK[variant]);
  const closeLook = $derived(CLOSE_LOOK[variant] ?? CLOSE_LOOK.rail!);
  const tip = $derived(face.tip || undefined);

  function menu(event: MouseEvent | KeyboardEvent): void {
    if (!onmenu) return;
    if (onmenu(id, event.currentTarget as HTMLElement, event) !== false) event.preventDefault();
  }

  function keydown(event: KeyboardEvent): void {
    if (isMenuKey(event)) {
      menu(event);
      return;
    }
    onkey?.(event, id);
  }
</script>

<svelte:element
  this={frame ? 'div' : 'button'}
  type={frame ? undefined : 'button'}
  class={[look.key, active && look.open, classes]}
  role={state === 'selected' ? 'tab' : undefined}
  data-zone-item={look.zone ? id : undefined}
  data-label={look.zone ? labelAt : undefined}
  aria-label={face.ariaLabel || undefined}
  aria-expanded={state === 'expanded' ? active : undefined}
  aria-pressed={state === 'pressed' ? active : undefined}
  aria-selected={state === 'selected' ? active : undefined}
  tabindex={tabbable === null ? undefined : tabbable ? look.stop : -1}
  data-tooltip-expanded={look.zone ? '' : undefined}
  title={look.tip === 'title' ? tip : undefined}
  data-tooltip={look.tip === 'data-tooltip' ? tip : undefined}
  style={look.zone ? `--rail-tone: var(--${face.tone})` : style}
  bind:this={element}
  onclick={frame ? undefined : (event: MouseEvent) => onpress?.(id, event)}
  onfocus={() => onfocus?.(id)}
  onpointerdown={(event: PointerEvent) => ondragstart?.(event, id)}
  onkeydown={keydown}
  oncontextmenu={menu}
  {...(look.ibtn ? buttonAttrs('quiet', 'icon') : {})}
  {...attrs}
>{#if shape === 'tile' && body}{@render body()}{:else if shape === 'tab'}{@render lead?.()}<span class={look.label} style={labelStyle}>{face.label}</span>{@render tail?.()}{:else}{#if body}{@render body()}{:else}<WidgetIcon name={face.icon} widget={null} size={iconPx} />{/if}{#if labelAt !== 'none'}<span class={look.label} aria-hidden="true">{face.label}</span>{/if}{/if}{#if !quiet}<ZoneBadge manifest={face.badge} options={face.options} count={face.count} global={face.global ?? false} markPx={Math.max(8, Math.round(iconPx * 0.6))} />{#if face.letter}<PinnedKeyBadge letter={face.letter} {compact} />{/if}{/if}{#if face.chip}<ViewChip />{/if}</svelte:element>
{#if close}
  <button
    type="button"
    class={[closeLook.key, close.armed && closeLook.armed]}
    tabindex="-1"
    aria-label={close.label}
    title={close.label}
    onpointerdown={close.onpress}
    onpointerup={close.onrelease}
    onpointercancel={close.onrelease}
    onpointerleave={close.onrelease}
    oncontextmenu={(event) => event.preventDefault()}
    onclick={close.run}
    {...(closeLook.ibtn ? buttonAttrs('quiet', 'icon') : {})}
    {...close.attrs}
  ><Icon name={close.armed ? 'skull' : 'close'} size={close.armed ? closeLook.armedPx : closeLook.px} /></button>
{/if}

<style>
  @layer components {
    .rail__key {
      display: inline-flex;
      flex: none;
      align-items: center;
      justify-content: center;
      box-sizing: border-box;
      width: var(--rail-key-w, 28px);
      height: var(--rail-key-h, 28px);
      min-width: var(--rail-key-minw, 0px);
      min-height: var(--rail-key-minh, 0px);
      padding: var(--rail-key-pad, 0);
      border: var(--oc-border) solid transparent;
      border-radius: var(--oc-radius-sm);
      background: transparent;
      color: var(--rail-tone, var(--oc-text-secondary));
      position: relative;
      cursor: pointer;
      transform: none;
      box-shadow: none;
    }

    .rail__key-label {
      font-family: var(--font-mono);
      color: var(--oc-text-secondary);
      text-align: center;
    }

    :global([data-axis='x']) .rail__key-label {
      margin-left: 6px;
      font-size: var(--oc-fs-label);
      line-height: 13px;
      white-space: nowrap;
    }

    :global([data-axis='y']) .rail__key[data-label='under'] {
      flex-direction: column;
    }

    :global([data-axis='y']) .rail__key-label {
      margin-top: 3px;
      max-width: var(--rail-label-maxw);
      min-width: min-content;
      font-size: var(--oc-fs-micro);
      line-height: 12px;
      overflow-wrap: normal;
      word-break: keep-all;
      hyphens: none;
      text-wrap: balance;
    }

    .rail__key:hover:not(:disabled) {
      background: var(--oc-ground-hover);
      transform: none;
      box-shadow: none;
    }

    :global(.rail__sections[data-editing='true']) .rail__key {
      cursor: grab;
    }

    .rail__key--open {
      border-color: var(--oc-orange);
      background: var(--oc-ground-hover);
    }

    .sbr-rail__btn {
      position: relative;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 34px;
      height: 34px;
      padding: 0;
      border: var(--oc-border) solid transparent;
      border-radius: var(--oc-radius-sm);
      background: transparent;
      color: var(--oc-text-secondary);
      cursor: pointer;
      -webkit-tap-highlight-color: transparent;
    }

    .sbr-rail__btn:hover {
      background: var(--oc-ground-hover);
      color: var(--oc-text-primary);
    }

    .sbr-rail__btn[aria-pressed='true'],
    .sbr-rail__btn[aria-current='page'] {
      background: var(--oc-orange-tint);
      color: var(--oc-orange-bright);
    }

    @media (max-width: 700px) {
      .sbr-rail__btn {
        width: 44px;
        height: 44px;
      }
    }

    .oc-tab {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      flex: 1 1 auto;
      min-width: 0;
      padding: 0 var(--oc-space-2);
      background: none;
      border: 0;
      color: var(--oc-text-dim);
      font: inherit;
      font-size: var(--oc-fs-label);
      cursor: pointer;
    }

    :global(.oc-tabwrap:hover) .oc-tab {
      color: var(--oc-text-primary);
    }

    .oc-tab-active,
    :global(.oc-tabwrap:hover) .oc-tab-active {
      color: var(--oc-orange);
    }

    .oc-tab-x {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      flex: 0 0 auto;
      width: 26px;
      margin-right: var(--oc-space-1);
      padding: 0;
      background: none;
      border: 0;
      color: var(--oc-text-dim);
      opacity: 0.6;
      cursor: pointer;
      -webkit-touch-callout: none;
      user-select: none;
    }

    .oc-tab-x:hover {
      opacity: 1;
      color: var(--oc-text-primary);
    }

    .oc-tab-skull,
    .oc-tab-skull:hover {
      opacity: 1;
      color: var(--oc-coral);
    }

    :global(.oc-tabrow-touch) .oc-tab-x {
      width: 44px;
      margin-right: 0;
    }

    .sbr-rail__close {
      --oc-ibtn-size: 16px;
      position: absolute;
      top: 0;
      left: 0;
      opacity: 0.6;
    }

    :global(.sbr-rail__cell:hover) .sbr-rail__close,
    :global(.sbr-rail__cell:focus-within) .sbr-rail__close,
    .sbr-rail__close:hover {
      opacity: 1;
    }

    .oc-tab-new {
      flex: 0 0 auto;
      padding: 0 var(--oc-space-3);
      background: var(--oc-tab-ground);
      border-top: 2px solid transparent;
      border-bottom: 1px solid var(--oc-line-rule);
      opacity: 0.55;
    }

    .oc-tab-new:hover,
    .oc-tab-new[aria-expanded='true'] {
      opacity: 1;
    }

    :global(.oc-tabrow-touch) .oc-tab {
      min-height: 44px;
    }

    :global(.oc-tabrow-touch) .oc-tab-new {
      min-width: 44px;
    }

    .oc-tab-name {
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
      min-width: 0;
    }

    .mr-claw {
      flex: 0 0 auto;
      --oc-ibtn-size: 36px;
    }

    /* padding */
    .oc-topbar-brand {
      position: relative;
      display: inline-flex;
      align-items: center;
      background: none;
      border: 0;
      padding: 0;
      margin: 0;
      cursor: pointer;
    }

    .oc-topbar-drawer {
      display: none;
      align-items: center;
      justify-content: center;
      width: 32px;
      height: 32px;
      margin: 0 var(--oc-space-2) 0 -10px;
      background: none;
      border: 0;
      color: var(--oc-text-secondary);
      cursor: pointer;
    }

    .oc-topbar-drawer:hover,
    .oc-topbar-drawer:focus-visible {
      color: var(--oc-text-primary);
    }

    @media (min-width: 701px) {
      :global(body:not(:has(.session-sidebar-panel--open))) .oc-topbar-drawer {
        display: inline-flex;
      }
    }

    :global(body.session-sidebar-railed) .oc-topbar-drawer {
      display: none;
    }

    .dz-glance {
      flex: 0 0 auto;
    }

    .dz-glance--icon {
      display: inline-flex;
      flex-direction: column;
      gap: var(--oc-space-1);
      align-items: center;
      justify-content: center;
      box-sizing: border-box;
      padding: 0;
      border: var(--oc-border) solid var(--oc-line-panel);
      border-radius: var(--oc-radius-sm);
      background: var(--oc-ground-field);
      cursor: pointer;
    }
  }
</style>
