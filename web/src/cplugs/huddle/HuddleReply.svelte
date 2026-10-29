<script lang="ts">
  import { getContext } from 'svelte';
  import { t } from '../sdk';
  import { BODY_OPTIONS, DEFAULT_BODY_OPTIONS, type BodyOptions } from './task-manager-body-options';
  import { markRead, reply } from './huddle.svelte';
  import type { HuddleItem } from './huddle-model';
  import { submitNow } from './task-submit';
  import { createSentFlash, submitLook } from './task-submit-state.svelte';
  import { hasFormAsk, hasNumberedAsk } from './task-manager-posts';
  import { Icon, SplitButton } from '../sdk/ui';
  import TaskManagerChips from './TaskManagerChips.svelte';
  import { autogrow, fitHeight } from './autogrow';
  import { createAttachments } from './task-manager-attachments.svelte';
  import { carriesFiles, filesOf } from './task-manager-files';
  import { uploadFile } from './task-manager-files-api';

  let { item, onRow = false, agentName = '', noSend = false, iconSend = false }: { item: HuddleItem; onRow?: boolean; agentName?: string; noSend?: boolean; iconSend?: boolean } = $props();

  const options: Readonly<BodyOptions> = getContext<BodyOptions | undefined>(BODY_OPTIONS) ?? DEFAULT_BODY_OPTIONS;

  const inTabs = $derived(options.tabbedDetail && !onRow);
  const base = options.baseFields;

  let mode = $state<'reply' | 'comment'>('reply');
  const split = $derived(options.replySplit && !noSend && !iconSend);
  const MODES = $derived([
    { value: 'reply', label: t('cplug.huddle.thread.send') },
    { value: 'comment', label: t('cplug.huddle.thread.comment') },
  ]);

  let draft = $state('');
  let box = $state<HTMLTextAreaElement | undefined>();
  $effect(() => { void draft; if (box) fitHeight(box); });
  $effect(() => (box ? autogrow(box) : undefined));
  let sending = $state(false);
  const sent = createSentFlash();
  const attached = createAttachments((file) => uploadFile(item.id, file));
  let dropping = $state(false);
  const look = $derived(submitLook(!!draft.trim() || attached.ids.length > 0, sent.on));
  const submitLabel = $derived(t(look === 'sent' ? 'cplug.huddle.submit.sent' : 'cplug.huddle.thread.send'));
  const submitOff = $derived(look === 'idle' ? true : (look === 'ready' && (sending || attached.busy)));
  const hint = $derived(t(hasFormAsk(item) ? 'cplug.huddle.thread.reply_comment' : hasNumberedAsk(item) ? 'cplug.huddle.thread.reply_numbered' : 'cplug.huddle.thread.reply_placeholder'));
  const placeholder = $derived(agentName ? t('cplug.huddle.chat.reply_placeholder', { name: agentName }) : split && mode === 'comment' ? t('cplug.huddle.thread.comment_placeholder') : hint);
  async function send(quiet = false): Promise<void> {
    const text = draft.trim();
    const ids = attached.ids;
    if ((!text && ids.length === 0) || sending || attached.busy) return;
    sending = true;
    mode = 'reply';
    const save = async (): Promise<boolean | 'kept'> => {
      if (ids.length === 0) { draft = ''; sent.flash(); }
      const ok = await reply(item, text, ids, !noSend, quiet);
      if (ok && ids.length > 0) { draft = ''; attached.clear(); sent.flash(); }
      if (!ok && ids.length === 0 && !draft) draft = text;
      return ok;
    };
    await (noSend || quiet ? save() : submitNow(item.list, save));
    sending = false;
  }

  const comment = (): Promise<void> => send(true);

  const sendPicked = (): Promise<void> => send(mode === 'comment');

  function onPaste(event: ClipboardEvent): void {
    const files = filesOf(event.clipboardData);
    if (files.length === 0) return;
    event.preventDefault();
    attached.add(files);
  }

  function onDragOver(event: DragEvent): void {
    if (!carriesFiles(event.dataTransfer)) return;
    event.preventDefault();
    dropping = true;
  }

  function onDrop(event: DragEvent): void {
    dropping = false;
    const files = filesOf(event.dataTransfer);
    if (files.length === 0) return;
    event.preventDefault();
    attached.add(files);
  }

  function onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      void sendPicked();
    }
  }
</script>

{#if base}
  
  <form class="oc-inline-field oc-focus-host" class:hdt-actions--row={onRow} class:hdt-actions--drop={dropping} data-task-manager-actions={item.id}
        ondragover={onDragOver} ondragleave={() => (dropping = false)} ondrop={onDrop} data-task-manager-reply-on-row={onRow ? item.id : undefined} onsubmit={(event) => { event.preventDefault(); void sendPicked(); }}>
    {#if attached.chips.length}<TaskManagerChips chips={attached.chips} onRemove={attached.remove} />{/if}
    <textarea class="oc-inline-field__input" data-field rows="1" bind:value={draft} bind:this={box} onkeydown={onKeydown} onpaste={onPaste}
              {placeholder} title={t('cplug.huddle.thread.keys_title')} aria-label={placeholder}
              data-huddle-reply={item.id}></textarea>
    <button type="submit" class="oc-inline-field__key" onclick={(event) => { event.preventDefault(); void sendPicked(); }} data-ready={look !== 'idle' ? '' : undefined}
            data-task-manager-submit-look={look} data-task-manager-split={split ? item.id : undefined} data-mode={mode} disabled={submitOff}
            aria-label={split && mode === 'comment' ? t('cplug.huddle.thread.comment') : submitLabel} title={t(split && mode === 'comment' ? 'cplug.huddle.thread.comment_title' : 'cplug.huddle.thread.keys_title')}><Icon name={split && mode === 'comment' ? 'chat' : 'send'} size={14} /></button>
    {#if split}
      <span class="oc-inline-field__key" data-task-manager-mode-key={item.id}>
        <Icon name="chevron-down" size={10} />
        <select class="oc-inline-field__select" aria-label={t('cplug.huddle.thread.mode')} value={mode} onchange={(event) => (mode = (event.currentTarget as HTMLSelectElement).value === 'comment' ? 'comment' : 'reply')}>
          {#each MODES as option (option.value)}<option value={option.value} selected={option.value === mode}>{option.label}</option>{/each}
        </select>
      </span>
    {/if}
  </form>
{:else}
<form class="hdt-actions oc-focus-host" class:hdt-actions--row={onRow} class:hdt-actions--drop={dropping} data-task-manager-actions={item.id}
      ondragover={onDragOver} ondragleave={() => (dropping = false)} ondrop={onDrop} data-task-manager-reply-on-row={onRow ? item.id : undefined} onsubmit={(event) => { event.preventDefault(); void sendPicked(); }}>
  {#if attached.chips.length}<TaskManagerChips chips={attached.chips} onRemove={attached.remove} />{/if}
  <textarea class="hdt-input" class:hdt-input--rows3={split} data-field={base ? '' : undefined} rows="1" bind:value={draft} bind:this={box} onkeydown={onKeydown} onpaste={onPaste}
            {placeholder} title={t('cplug.huddle.thread.keys_title')} aria-label={placeholder}
            data-huddle-reply={item.id}></textarea>
  {#if split}
    <SplitButton label={t(mode === 'comment' ? 'cplug.huddle.thread.comment' : look === 'sent' ? 'cplug.huddle.submit.sent' : 'cplug.huddle.thread.send')} options={MODES} value={mode}
                 onChange={(next) => (mode = next === 'comment' ? 'comment' : 'reply')} onMain={() => void sendPicked()} disabled={submitOff} variant={look === 'idle' ? 'quiet' : 'confirm'}
                 selectLabel={t('cplug.huddle.thread.mode')} title={t(mode === 'comment' ? 'cplug.huddle.thread.comment_title' : 'cplug.huddle.thread.keys_title')}
                 attrs={{ 'data-task-manager-submit-look': look, 'data-task-manager-split': item.id, 'data-mode': mode }} />
  {:else if iconSend}
    <button type="submit" class="oc-ibtn hdt-send hdt-send--icon" onclick={(event) => { event.preventDefault(); void send(); }} class:oc-ibtn--bare={look === 'idle'} class:hdt-send--ready={look !== 'idle'}
            data-task-manager-submit-look={look} disabled={submitOff} aria-label={submitLabel} title={submitLabel}><Icon name="send" size={14} /></button>
  {:else}
    <button type="submit" class="oc-btn oc-btn--sm hdt-send" onclick={(event) => { event.preventDefault(); void send(); }} class:oc-btn--ghost={look === 'idle'} class:oc-btn--confirm={look !== 'idle'}
            data-task-manager-submit-look={look} disabled={submitOff}>{submitLabel}</button>
  {/if}
  {#if split}
    
  {:else if !noSend && iconSend}
    
    <button type="button" class="oc-ibtn oc-ibtn--bare" onclick={() => void comment()} disabled={submitOff || look === 'idle'}
            aria-label={t('cplug.huddle.thread.comment')} title={t('cplug.huddle.thread.comment_title')} data-task-manager-comment={item.id}><Icon name="chat" size={14} /></button>
    {#if item.unread && !inTabs}
      <button type="button" class="oc-ibtn oc-ibtn--bare" onclick={() => void markRead(item)}
              aria-label={t('cplug.huddle.thread.mark_read')} title={t('cplug.huddle.thread.mark_read_title')} data-task-manager-mark-read={item.id}><Icon name="check" size={14} /></button>
    {/if}
  {:else if !noSend}
    <button type="button" class="oc-btn oc-btn--sm oc-btn--ghost" data-btn="quiet" data-size="sm" onclick={() => void comment()} disabled={submitOff || look === 'idle'}
            title={t('cplug.huddle.thread.comment_title')} data-task-manager-comment={item.id}>{t('cplug.huddle.thread.comment')}</button>
    {#if item.unread && !inTabs}
      <button type="button" class="oc-btn oc-btn--sm oc-btn--ghost" data-btn="quiet" data-size="sm" onclick={() => void markRead(item)}
              title={t('cplug.huddle.thread.mark_read_title')} data-task-manager-mark-read={item.id}>{t('cplug.huddle.thread.mark_read')}</button>
    {/if}
  {/if}
</form>
{/if}

<style>
  @layer components {
    .hdt-actions {
      display: flex;
      align-items: flex-end;
      flex-wrap: wrap;
      gap: 4px;
      min-width: 0;
      margin-left: 8px;
      padding: 2px 2px 2px 8px;
      border: 1px solid var(--oc-control-line);
      border-radius: var(--oc-control-radius);
      background: var(--oc-ground-field);
    }

    .hdt-actions--drop {
      border-color: var(--oc-orange);
    }

    .hdt-input {
      flex: 1 1 0;
      min-width: 0;
      height: 20px;
      min-height: 20px;
      max-height: 120px;
      padding: 2px 0;
      border: 0;
      background: none;
      color: var(--oc-text-primary);
      font: inherit;
      line-height: 16px;
      resize: none;
      outline: none;
    }

    .hdt-input--rows3 {
      max-height: calc(3lh + 2 * var(--oc-space-0-5));
      overflow-y: auto;
    }

    .hdt-input::placeholder {
      color: var(--oc-text-dim);
    }

    .hdt-send {
      flex: none;
    }

    .hdt-send--ready {
      --_bd: var(--oc-orange);
      border-color: var(--oc-orange);
      color: var(--oc-text-bright);
    }

    .oc-inline-field.hdt-actions--drop {
      border-color: var(--oc-orange);
    }

    .hdt-actions--row {
      margin-left: 0;
    }
  }
</style>
