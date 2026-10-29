<script lang="ts">
  import AnchoredPopup from '../../lib/dialog-frame/AnchoredPopup.svelte';
  import Button from '../../lib/base/Button.svelte';
  import { t } from '../../lib/i18n/index.svelte';
  import { answerDuplicate, closeDuplicate, duplicatePrompt } from './duplicate-prompt.svelte';

  const WIDTH = 300;
  const EDGE = 8;
  const HEIGHT = 190;

  const ask = $derived(duplicatePrompt.ask);

  const line = $derived(
    !ask ? '' : t(`layout_editor.dupe.${ask.kind}`, { title: ask.title }),
  );
  const box = $derived.by(() => {
    if (!ask || typeof window === 'undefined') return { left: 0, top: 0 };
    return {
      left: Math.max(EDGE, Math.min(ask.x + EDGE, window.innerWidth - WIDTH - EDGE)),
      top: Math.max(EDGE, Math.min(ask.y + EDGE, window.innerHeight - HEIGHT - EDGE)),
    };
  });
</script>

{#if ask}
  
  {#key ask}
  <AnchoredPopup
    class="le-dupe"
    topLayer
    role="alertdialog"
    label={line}
    tabindex={-1}
    data-duplicate-prompt={ask.kind}
    placement="manual"
    style={`left: ${Math.round(box.left)}px; top: ${Math.round(box.top)}px; width: ${WIDTH}px`}
    initialFocus="[data-dupe-primary]"
    onClose={closeDuplicate}
  >
    <p class="le-dupe__line">{line}</p>
    <div class="le-dupe__row">
      {#if ask.kind === 'here'}
        <Button data-dupe-primary data-dupe-ok onclick={closeDuplicate}>{t('layout_editor.dupe.ok')}</Button>
      {:else}
        <Button data-dupe-cancel onclick={closeDuplicate}>{t('layout_editor.dupe.cancel')}</Button>
        {#if ask.kind === 'copy'}
          <Button data-dupe-move onclick={() => answerDuplicate('move')}>{t('layout_editor.dupe.move')}</Button>
          <Button variant="confirm" data-dupe-primary data-dupe-copy onclick={() => answerDuplicate('copy')}>{t('layout_editor.dupe.add_copy')}</Button>
        {:else}
          <Button variant="confirm" data-dupe-primary data-dupe-move onclick={() => answerDuplicate('move')}>{t('layout_editor.dupe.move')}</Button>
        {/if}
      {/if}
    </div>
  </AnchoredPopup>
  {/key}
{/if}

<style>
  @layer components {
    :global(.le-dupe) {
      position: fixed;
      inset: auto;
      margin: 0;
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: var(--oc-space-2);
      padding: var(--oc-space-3);
      box-sizing: border-box;
      background: var(--oc-ground-panel);
      border: var(--oc-border) solid var(--oc-line-frame);
      border-radius: var(--oc-radius-sm);
      color: var(--oc-text-primary);
    }

    .le-dupe__line {
      margin: 0;
      font-family: var(--font-mono);
      font-size: var(--oc-fs-label);
      line-height: 1.45;
    }

    .le-dupe__row {
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: var(--oc-space-2);
      min-width: 0;
    }

  }
</style>
