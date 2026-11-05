<!-- the phone collapse toggle -->
<script lang="ts">
  import { onMount } from 'svelte';
  import { t } from '../i18n/index.svelte';
  import { openAttachmentLightbox } from '../attachment-lightbox/open';
  import { attach as attachMute } from '../notifications/mute/mute-control';
  import type { ToastCardView, ToastRecord, ToastStackManager } from './types';

  let { card, manager }: { card: ToastCardView; manager: ToastStackManager } = $props();

  let el: HTMLDivElement | undefined = $state();
  let entering = $state(true);
  let expanded = $state<boolean | undefined>(undefined);

  onMount(() => {
    void el?.offsetWidth;
    requestAnimationFrame(() => {
      entering = false;
    });
  });

  const muteKey = $derived(card.winner);
  const muteType = $derived(card.winner['notify_type']);
  $effect(() => {
    void muteType;
    if (el) attachMute(el, muteKey);
  });

  function open(): void {
    manager.openGroup(card.key);
  }

  function onKeydown(evt: KeyboardEvent): void {
    if (evt.target !== evt.currentTarget) return;
    if (!card.clickable) return;
    if (evt.key === 'Enter' || evt.key === ' ') {
      evt.preventDefault();
      open();
    }
  }

  function onMousedown(evt: MouseEvent): void {
    if (evt.button === 1) evt.preventDefault();
  }

  function onAuxclick(evt: MouseEvent): void {
    if (evt.button !== 1) return;
    evt.preventDefault();
    manager.dismissGroup(card.key);
  }

  function alone(evt: Event, run: () => void): void {
    evt.stopPropagation();
    run();
  }

  const dismissLabel = $derived(card.count > 1 ? t('toast.dismiss.many', { count: card.count }) : t('toast.dismiss.one'));
  const toggleLabel = $derived(expanded === true ? t('toast.collapse.hide') : t('toast.collapse.show'));

  function openFull(evt: MouseEvent, toast: ToastRecord, name: string): void {
    evt.stopPropagation();
    openAttachmentLightbox(toast.full_blob as Blob, name, evt.currentTarget as HTMLElement);
  }
</script>


<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
<div
  bind:this={el}
  class="toast"
  class:toast--entering={entering}
  class:toast--dismissing={card.dismissing}
  class:toast--clickable={card.clickable}
  data-group-key={card.key}
  data-toast-id={card.id}
  data-kind={card.kind}
  data-severity={card.severity}
  data-alert-severity={card.alertSeverity ?? undefined}
  data-count={card.count}
  data-mode={card.mode}
  data-session-id={card.sessionId}
  data-themed={card.color ? '1' : undefined}
  data-expanded={expanded === undefined ? undefined : expanded ? '1' : '0'}
  style:--toast-accent={card.color}
  role={card.role}
  tabindex={card.clickable ? 0 : undefined}
  onclick={card.clickable ? open : undefined}
  onkeydown={onKeydown}
  onmousedown={onMousedown}
  onauxclick={onAuxclick}
>
  <div class="toast__title">
    {#if card.sleepIcon !== null}<span class="toast__title-icon">{@html card.sleepIcon}</span>{/if}
    
    <span class="toast__title-text">{card.title || t('toast.untitled')}</span>
    
    {#if card.badgeCount > 1}
      <span class="toast__count" aria-label={t('toast.count.label', { count: card.badgeCount })}>{t('toast.count.badge', { count: card.badgeCount })}</span>
    {/if}
    {#if card.canExpand}
      <button type="button" class="toast__toggle" data-btn="quiet" data-size="bare" data-overflow="visible"
        aria-expanded={expanded === true} aria-label={toggleLabel} title={toggleLabel}
        onclick={(evt: MouseEvent) => alone(evt, () => (expanded = expanded !== true))}>
        <span class="toast__toggle-chevron" aria-hidden="true">
          <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 2l4 4-4 4"></path></svg>
        </span>
      </button>
    {/if}
  </div>

  
  {#if card.session.canNavigate}
    <button type="button" class="toast__session" data-btn="quiet" data-size="bare" data-overflow="visible"
      data-unknown={card.session.unknown ? '1' : undefined} onclick={() => manager.clickSession(card.key)}>{card.session.text}</button>
  {:else}
    <div class="toast__session" data-unknown={card.session.unknown ? '1' : undefined}>{card.session.text}</div>
  {/if}

  {#if card.body}<div class="toast__body">{card.body}</div>{/if}

  {#if card.actionLabel}
    <button type="button" class="modal-btn modal-btn-secondary toast__action" data-btn="secondary" data-size="sm"
      onclick={(evt: MouseEvent) => alone(evt, () => manager.runCardAction(card.key))}>{card.actionLabel}</button>
  {/if}

  
  {#if card.thumbs}
    <div class="toast__thumbs">
      {#each card.thumbs as toast (toast.id)}
        {@const name = String(toast.attachment_name ?? '')}
        <div class="toast__thumb-row">
          <div class="toast__thumb" data-no-preview={toast.thumb_url ? undefined : '1'}>
            {#if toast.thumb_url}
              {#if toast.full_blob}
                <button type="button" class="toast__thumb-btn" data-btn="quiet" data-size="bare" data-overflow="visible"
                  aria-label={t('toast.attachment.open_full', { name })} onclick={(evt: MouseEvent) => openFull(evt, toast, name)}>
                  <img class="toast__thumb-img" alt={name || t('toast.attachment.preview_alt')} src={String(toast.thumb_url)} />
                </button>
              {:else}
                <img class="toast__thumb-img" alt={name || t('toast.attachment.preview_alt')} src={String(toast.thumb_url)} />
              {/if}
            {:else}
              <span class="toast__thumb-ext" aria-hidden="true">{String(toast.thumb_label || 'FILE')}</span>
            {/if}
          </div>
          <div class="toast__thumb-name">{name || t('toast.attachment.unnamed')}</div>
        </div>
      {/each}
    </div>
  {/if}

  <button type="button" class="toast__dismiss" data-btn="quiet" data-size="bare" data-overflow="visible"
    aria-label={dismissLabel} title={dismissLabel} onclick={(evt: MouseEvent) => alone(evt, () => manager.dismissGroup(card.key))}>×</button>
</div>
