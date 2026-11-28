
<script lang="ts">
  import { tick, untrack } from 'svelte';
  import { t } from '../../i18n/index.svelte';
  import { closeDrawer, closePane, data } from '../page-store.svelte';
  import { claimEscape, escapeTaken } from '../logic/escape';
  import { resetDrawer } from './drawer-state.svelte';
  import AutomationDrawer from './AutomationDrawer.svelte';
  import RunDrawer from './RunDrawer.svelte';
  import './drawer.css';

  let el = $state<HTMLElement>();

  // the page frame
  // svelte-ignore state_referenced_locally
  let subject = $state(data.drawer);
  $effect(() => {
    if (data.drawer) subject = data.drawer;
  });
  const automation = $derived(subject?.kind === 'automation' ? (data.automations.find((a) => a.automation_id === subject?.id) ?? null) : null);

  $effect(() => {
    const active = typeof document !== 'undefined' ? document.activeElement : null;
    const opener = active instanceof HTMLElement && !el?.contains(active) ? active : null;
    untrack(() => {
      if (data.paneOpen) closePane();
    });
    void tick().then(() => el?.focus({ preventScroll: true }));
    return () => {
      resetDrawer();
      if (opener && typeof document !== 'undefined' && document.contains(opener)) opener.focus({ preventScroll: true });
    };
  });

  $effect(() => {
    if (data.drawer?.kind === 'automation' && data.status === 'ready' && !automation) closeDrawer();
  });

  function keys(e: KeyboardEvent): void {
    if (!subject || e.key !== 'Escape' || e.metaKey || e.ctrlKey || e.altKey) return;
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
  data-open=""
  data-kind={subject?.kind}
  onkeydown={trap}
>
  {#if subject}
    {#if subject.kind === 'run'}
      {#key subject.id}<RunDrawer id={subject.id} />{/key}
    {:else if automation}
      {#key automation.automation_id}<AutomationDrawer {automation} />{/key}
    {/if}
  {/if}
</div>
