<!-- position: fixed -->
<script lang="ts">
  import { onMount } from 'svelte';
  import { t } from '../i18n/index.svelte';
  import { beginGesture } from '../../opscenter/engine/pointer';
  import {
    clampRect, defaultRect, loadRect, saveRect, stepRect,
    type LightboxRect, type Viewport,
  } from './lightbox-geometry';

  interface Props {
    src: string;
    alt: string;
    caption?: string;
    onClose: () => void;
  }

  const { src, alt, caption, onClose }: Props = $props();

  let closeButton: HTMLButtonElement | undefined = $state();
  let returnFocus: Element | null = null;
  let justGestured = false;

  function viewport(): Viewport {
    return { w: window.innerWidth, h: window.innerHeight };
  }

  let rect: LightboxRect = $state(clampRect(loadRect() ?? defaultRect(viewport()), viewport()));

  onMount(() => {
    returnFocus = document.activeElement;
    closeButton?.focus();
    return () => {
      if (returnFocus instanceof HTMLElement) returnFocus.focus();
    };
  });

  function commit(next: LightboxRect): void {
    rect = next;
    saveRect(next);
  }

  function onKey(e: KeyboardEvent): void {
    if (e.key !== 'Escape') return;
    e.preventDefault();
    e.stopPropagation();
    onClose();
  }

  function onWindowKey(e: KeyboardEvent): void {
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    const next = stepRect(rect, e.key, e.shiftKey, viewport());
    if (!next) return;
    e.preventDefault();
    e.stopPropagation();
    commit(next);
  }

  function gesture(handle: HTMLElement, e: PointerEvent, shape: (start: LightboxRect, dx: number, dy: number) => LightboxRect): void {
    const start = rect;
    justGestured = true;
    beginGesture(handle, e, {
      onMove: (dx, dy) => { rect = clampRect(shape(start, dx, dy), viewport()); },
      onEnd: () => {
        saveRect(rect);
        setTimeout(() => { justGestured = false; }, 0);
      },
    });
  }

  function onBarDown(e: PointerEvent): void {
    if ((e.target as HTMLElement).closest('button')) return;
    gesture(e.currentTarget as HTMLElement, e, (s, dx, dy) => ({ ...s, x: s.x + dx, y: s.y + dy }));
  }

  function onGripDown(e: PointerEvent): void {
    e.stopPropagation();
    gesture(e.currentTarget as HTMLElement, e, (s, dx, dy) => ({ ...s, w: s.w + dx, h: s.h + dy }));
  }

  function onBackdrop(e: MouseEvent): void {
    if (e.target === e.currentTarget && !justGestured) onClose();
  }

  function onResize(): void {
    rect = clampRect(rect, viewport());
  }
</script>

<svelte:window onkeydown={onKey} onresize={onResize} />


<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="sidebar-help__lightbox" onclick={onBackdrop}>
  <div
    class="sidebar-help__lightbox-body"
    role="dialog"
    aria-modal="true"
    aria-label={caption ?? alt}
    aria-keyshortcuts="ArrowLeft ArrowRight ArrowUp ArrowDown Shift+ArrowLeft Shift+ArrowRight Shift+ArrowUp Shift+ArrowDown"
    tabindex="-1"
    style:left="{rect.x}px"
    style:top="{rect.y}px"
    style:width="{rect.w}px"
    style:height="{rect.h}px"
    onkeydown={onWindowKey}
  >
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="sidebar-help__lightbox-bar" onpointerdown={onBarDown}>
      <p class="sidebar-help__lightbox-caption">{caption ?? ''}</p>
      <button
        type="button"
        class="sidebar-help__lightbox-close"
        bind:this={closeButton}
        onclick={onClose}
      >
        {t('sidebar_help.features.lightbox_close')}
      </button>
    </div>
    <div class="sidebar-help__lightbox-stage">
      <img src={src} {alt} class="sidebar-help__lightbox-img" draggable="false" />
    </div>
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      class="sidebar-help__lightbox-grip"
      title={t('sidebar_help.features.lightbox_resize')}
      onpointerdown={onGripDown}
    ></div>
  </div>
</div>
