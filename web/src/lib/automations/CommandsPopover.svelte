<!-- Escape closes it -->
<script lang="ts">
  import Button from '../base/Button.svelte';
  import { t } from '../i18n/index.svelte';
  import AutomationCommandsPanel from './AutomationCommandsPanel.svelte';
  import { data } from './page-store.svelte';
  import { claimEscape } from './logic/escape';

  let wrap = $state<HTMLElement | undefined>();
  let button = $state<HTMLElement | null>(null);
  let pop = $state<HTMLElement | undefined>();
  let shift = $state(0);

  /* the page frame */
  function keepInside(): void {
    if (!pop) return;
    const frame = wrap?.closest('.ap-page')?.getBoundingClientRect();
    const left = Math.max(frame?.left ?? 0, 0) + 8;
    const right = Math.min(frame?.right ?? window.innerWidth, window.innerWidth) - 8;
    const box = pop.getBoundingClientRect();
    const base = box.left - shift;
    shift = Math.max(0, left - base) - Math.max(0, base + box.width - right);
  }

  $effect(() => {
    if (data.commandsOpen && pop) keepInside();
  });

  function outside(event: MouseEvent): void {
    if (data.commandsOpen && wrap && !wrap.contains(event.target as Node)) data.commandsOpen = false;
  }

  function escape(event: KeyboardEvent): void {
    if (event.key !== 'Escape' || !data.commandsOpen) return;
    claimEscape(event);
    data.commandsOpen = false;
    button?.focus();
  }
</script>

<svelte:document onclick={outside} />
<svelte:window onkeydowncapture={escape} />

<span class="ap-cmd-wrap" bind:this={wrap}>
  <Button
    bind:element={button}
    data-automation-commands-toggle
    aria-expanded={data.commandsOpen}
    aria-controls="ap-cmd-pop"
    onclick={() => (data.commandsOpen = !data.commandsOpen)}>{t('automations.page.commands')}</Button
  >
  {#if data.commandsOpen}
    <div class="ap-cmd-pop" id="ap-cmd-pop" bind:this={pop} style:transform={shift ? `translateX(${shift}px)` : undefined} data-automation-commands-section>
      <span class="pl-label">{t('automations.page.commands.title')}</span>
      <AutomationCommandsPanel />
      <p class="ap-note">{t('automations.page.commands.note')}</p>
    </div>
  {/if}
</span>
