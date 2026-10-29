<script lang="ts">
  import { timerChip } from './timers';
  import { openTimerList } from './popup';

  let {
    live,
    nextFireAt = null,
    sessionId = '',
    name = '',
  }: {
    live: number | null | undefined;
    nextFireAt?: string | null;
    sessionId?: string;
    name?: string;
  } = $props();

  const TICK_MS = 30000;

  let nowMs = $state(Date.now());
  const chip = $derived(timerChip({ timers_live: live, timers_next_fire_at: nextFireAt }, nowMs));

  const visible = $derived(chip !== null);
  $effect(() => {
    if (!visible) return;
    const handle = setInterval(() => { nowMs = Date.now(); }, TICK_MS);
    return () => clearInterval(handle);
  });

  function open(event: MouseEvent): void {
    event.stopPropagation();
    event.preventDefault();
    openTimerList(event.currentTarget as HTMLElement, sessionId, name);
  }

  function keep(event: KeyboardEvent): void {
    if (event.key === 'Enter' || event.key === ' ') event.stopPropagation();
  }
</script>

{#if chip !== null}
  <button data-base-exempt="an inline chip sized to the session row label"
    type="button"
    class="timer-chip timer-chip--button"
    aria-haspopup="dialog"
    aria-label={chip.title}
    data-timers-session-id={sessionId}
    onclick={open}
    onkeydown={keep}
  ><svg class="timer-chip__glyph" viewBox="0 0 10 10" aria-hidden="true" focusable="false"
      ><circle cx="5" cy="5" r="4" /><path d="M5 2.6V5l1.6 1" /></svg
    >{chip.text}</button>
{/if}
