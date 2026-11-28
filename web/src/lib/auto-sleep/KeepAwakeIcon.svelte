<script lang="ts">
  import Glyph from '../Glyph.svelte';
  import { t } from '../i18n/index.svelte';
  import { autoSleepActivity, isKeptAwake, setKeepAwake } from './auto-sleep-store.svelte';
  import { sessions } from '../../opscenter/api';
  import { sleepHoldParts, sleepVerdictLine } from './sleep-hold';

  let { sessionName }: { sessionName: string | null } = $props();

  const kept = $derived(isKeptAwake(sessionName));
  const known = $derived(kept !== null);
  const on = $derived(kept === true);
  const held = $derived(
    on || !sessionName
      ? null
      : sleepHoldParts((sessions.data ?? []).find((row) => row.tmux_session === sessionName), Date.now()),
  );
  const verdict = $derived(
    on || !sessionName
      ? null
      : sleepVerdictLine((sessions.data ?? []).find((row) => row.tmux_session === sessionName), Date.now()),
  );
  const label = $derived(
    !known
      ? t('auto_sleep.keep_awake.unknown')
      : verdict
        ? t('auto_sleep.keep_awake.off_verdict', { line: verdict })
        : held
        ? t('auto_sleep.keep_awake.off_held', { reason: held })
        : t(on ? 'auto_sleep.keep_awake.on' : 'auto_sleep.keep_awake.off', { name: sessionName ?? '' }),
  );
</script>

<button
  type="button"
  class="kaw-icon"
  data-keep-awake={on ? '1' : '0'}
  aria-pressed={known ? on : undefined}
  aria-label={label}
  title={label}
  disabled={!known || autoSleepActivity.busy !== null}
  onclick={() => { if (sessionName) void setKeepAwake(sessionName, !on); }}
>
  <Glyph name="coffee" />
</button>

<style>
  .kaw-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: var(--cell-tool-h, 26px);
    padding: 0;
    flex-shrink: 0;
    position: relative;
    top: 0;
    background: transparent;
    border: 1px solid transparent;
    border-radius: var(--oc-radius-sm);
    color: var(--oc-text-muted);
    opacity: 0.6;
    cursor: pointer;
    transition: color 120ms ease, background 120ms ease, opacity 120ms ease;
  }

  .kaw-icon[data-keep-awake='1'] {
    color: var(--oc-violet);
    opacity: 1;
    animation: amb-join-sparks-steam 1ms;
  }

  .kaw-icon:hover:not(:disabled),
  .kaw-icon:focus-visible {
    background: var(--oc-ground-hover);
    opacity: 1;
  }

  .kaw-icon:disabled {
    cursor: default;
    opacity: 0.4;
  }

  .kaw-icon :global(svg) {
    overflow: visible;
  }

  .kaw-icon :global(.kaw-steam) {
    opacity: 0;
  }

  .kaw-icon[data-keep-awake='1'] :global(.kaw-steam) {
    opacity: var(--amb-steam-op-1, 0);
    transform: translateY(calc(var(--amb-steam-y-1) * 1px * var(--kaw-u)));
  }

  .kaw-icon[data-keep-awake='1'] :global(.kaw-steam-2) {
    opacity: var(--amb-steam-op-2, 0);
    transform: translateY(calc(var(--amb-steam-y-2) * 1px * var(--kaw-u)));
  }

  .kaw-icon[data-keep-awake='1'] :global(.kaw-steam-3) {
    opacity: var(--amb-steam-op-3, 0);
    transform: translateY(calc(var(--amb-steam-y-3) * 1px * var(--kaw-u)));
  }

  @media (prefers-reduced-motion: reduce) {
    .kaw-icon[data-keep-awake='1'] {
      animation: none;
    }

    .kaw-icon[data-keep-awake='1'] :global(.kaw-steam) {
      animation: none;
      opacity: 0.6;
      transform: none;
    }
  }

:global(:root[data-motion="off"]) .kaw-icon[data-keep-awake='1'] :global(.kaw-steam) {
  opacity: 0.6;
  transform: none;
}
</style>
