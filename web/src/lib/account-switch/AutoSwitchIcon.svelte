<script lang="ts">
  import BotCycleMark from './BotCycleMark.svelte';
  import { t } from '../i18n/index.svelte';
  import { accountSwitch, setAutoSwitch, switchActivity } from './switch-store.svelte';

  let { size = 18 }: { size?: number } = $props();

  const known = $derived(accountSwitch.data !== null);
  const on = $derived(accountSwitch.data?.auto_switch === true);
  const label = $derived(
    !known
      ? t('account_switch.icon.unknown')
      : t(on ? 'account_switch.icon.on' : 'account_switch.icon.off', {
          percent: accountSwitch.data?.threshold_percent ?? 99,
        }),
  );
</script>

<button
  type="button"
  class="asw-icon"
  data-on={on ? '1' : '0'}
  aria-pressed={known ? on : undefined}
  aria-label={label}
  title={label}
  disabled={!known || switchActivity.busy !== null}
  onclick={() => void setAutoSwitch(!on)}
>
  <BotCycleMark {size} />
  {#if on}<span class="asw-spark" aria-hidden="true"></span>{/if}
</button>

<style>
  .asw-icon {
    position: relative;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
    padding: 0;
    flex-shrink: 0;
    background: transparent;
    border: none;
    border-radius: var(--oc-radius-sm);
    color: var(--oc-text-muted);
    cursor: pointer;
    transition: color 120ms ease, background 120ms ease;
  }

  .asw-icon[data-on='1'] {
    --asw-ink: var(--oc-violet);
    color: var(--asw-ink);
  }

  .asw-icon:hover:not(:disabled),
  .asw-icon:focus-visible {
    background: var(--oc-ground-hover);
  }

  .asw-icon:disabled {
    cursor: default;
    opacity: 0.55;
  }

  .asw-spark {
    position: absolute;
    inset: -2px;
    pointer-events: none;
  }

  .asw-spark::before,
  .asw-spark::after {
    content: '';
    position: absolute;
    width: 2px;
    height: 2px;
    border-radius: 50%;
    background: var(--asw-ink);
    opacity: 0;
    animation: asw-spark 2.4s ease-out infinite;
  }

  .asw-spark::before {
    left: 3px;
    bottom: 5px;
  }

  .asw-spark::after {
    right: 3px;
    bottom: 3px;
    animation-delay: 1.2s;
  }

  @keyframes asw-spark {
    0% { opacity: 0; transform: translateY(0) scale(0.6); }
    20% { opacity: 0.9; }
    100% { opacity: 0; transform: translateY(-9px) scale(1); }
  }

  @media (prefers-reduced-motion: reduce) {
    .asw-spark::before,
    .asw-spark::after {
      animation: none;
      opacity: 0;
    }
  }

:global(:root[data-motion="off"]) .asw-spark::before,
:global(:root[data-motion="off"]) .asw-spark::after {
  opacity: 0;
}
</style>
