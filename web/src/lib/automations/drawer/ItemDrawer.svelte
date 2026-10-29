<!-- Escape closes it -->
<script lang="ts">
  import { tick } from 'svelte';
  import { t } from '../../i18n/index.svelte';
  import Button from '../../base/Button.svelte';
  import { closeDrawer, closePane, data } from '../page-store.svelte';
  import { claimEscape, escapeTaken } from '../logic/escape';
  import { resetDrawer } from './drawer-state.svelte';
  import AutomationDrawer from './AutomationDrawer.svelte';
  import RunDrawer from './RunDrawer.svelte';
  import './drawer.css';

  let el = $state<HTMLElement>();
  let last = $state(data.drawer);
  let opener: HTMLElement | null = null;

  const open = $derived(data.drawer !== null);
  const automation = $derived(last?.kind === 'automation' ? (data.automations.find((a) => a.automation_id === last!.id) ?? null) : null);

  $effect(() => {
    const subject = data.drawer;
    if (subject) last = subject;
  });

  let was = false;
  $effect(() => {
    if (open === was) return;
    was = open;
    if (open) {
      const active = typeof document !== 'undefined' ? document.activeElement : null;
      opener = active instanceof HTMLElement && !el?.contains(active) ? active : null;
      if (data.paneOpen) closePane();
      void tick().then(() => el?.focus({ preventScroll: true }));
    } else {
      resetDrawer();
      if (opener && typeof document !== 'undefined' && document.contains(opener)) opener.focus({ preventScroll: true });
      opener = null;
    }
  });

  $effect(() => {
    if (data.drawer?.kind === 'automation' && data.status === 'ready' && !automation) closeDrawer();
  });

  function keys(e: KeyboardEvent): void {
    if (!open || e.key !== 'Escape' || e.metaKey || e.ctrlKey || e.altKey) return;
    if (escapeTaken(e)) return;
    claimEscape(e);
    closeDrawer();
  }

  function trap(e: KeyboardEvent): void {
    if (e.key !== 'Tab' || !el) return;
    const items = [...el.querySelectorAll<HTMLElement>('button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])')].filter((x) => x.offsetParent !== null);
    if (!items.length) {
      e.preventDefault();
      el.focus();
      return;
    }
    const first = items[0]!;
    const final = items[items.length - 1]!;
    const at = document.activeElement;
    if (e.shiftKey && (at === first || at === el)) {
      e.preventDefault();
      final.focus();
    } else if (!e.shiftKey && at === final) {
      e.preventDefault();
      first.focus();
    }
  }
</script>


<svelte:window onkeydowncapture={keys} />

<div
  bind:this={el}
  class="ap-dr"
  role="complementary"
  tabindex="-1"
  aria-label={t('automations.simple.dr.aria')}
  data-ap-drawer
  data-open={open ? '' : undefined}
  data-kind={last?.kind}
  onkeydown={trap}
>
  <div class="pl-titlebar ap-dr-bar">
    <Button size="sm" data-dr-back data-dr-close onclick={closeDrawer}>{t('automations.simple.dr.back')}</Button>
    <span class="pl-label ap-dr-lab">{t(last?.kind === 'run' ? 'automations.simple.dr.label_run' : 'automations.simple.dr.label_automation')}</span>
    <Button size="sm" data-dr-x data-dr-close onclick={closeDrawer}>{t('automations.simple.dr.close')}</Button>
  </div>
  <div class="ap-dr-scroll">
    {#if open && last}
      {#if last.kind === 'run'}
        {#key last.id}<RunDrawer id={last.id} />{/key}
      {:else if automation}
        {#key automation.automation_id}<AutomationDrawer {automation} />{/key}
      {/if}
    {/if}
  </div>
</div>
