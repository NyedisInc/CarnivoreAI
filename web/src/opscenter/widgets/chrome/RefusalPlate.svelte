<script lang="ts" module>
  export const PLATE_FULL_PX = 130;
  export const PLATE_BRIEF_PX = 64;
</script>

<script lang="ts">
  import { untrack } from 'svelte';
  import { Button } from '../../../lib/base';
  import { t } from '../../../lib/i18n/index.svelte';
  import Icon from '../../ui/Icon.svelte';
  import type { FitCheck } from '../fits';
  import { sizeNameKey, type GridSizeName } from '../named-sizes';
  import type { FitSize } from '../types';
  import { useFrameGuide } from './resize-guide.svelte';

  let {
    check,
    sizes = [],
    onFix,
    onReport,
  }: {
    check: Extract<FitCheck, { ok: false }>;
    sizes?: readonly GridSizeName[];
    onFix?: (size: FitSize) => void;
    onReport: () => Promise<boolean>;
  } = $props();

  let room = $state(0);
  let plate: HTMLElement | undefined = $state();
  $effect(() => {
    if (!plate || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => { room = plate?.clientHeight ?? 0; });
    observer.observe(plate);
    return () => observer.disconnect();
  });
  const step = $derived(room === 0 || room >= PLATE_FULL_PX ? 'full' : room >= PLATE_BRIEF_PX ? 'brief' : 'icon');

  let sent = $state<'idle' | 'sending' | 'sent' | 'failed'>('idle');

  const detail = $derived.by(() => {
    if (check.reason === 'untested' && sizes.length > 0) {
      return t('widgets.unavailable.detail_untested', { sizes: sizes.map((name) => t(sizeNameKey(name))).join(', ') });
    }
    return t('widgets.refusal.detail_small');
  });

  const frameGuide = useFrameGuide();
  $effect(() => {
    if (!frameGuide) return;
    untrack(() => (frameGuide.plates += 1));
    return () => untrack(() => (frameGuide.plates -= 1));
  });
  const off = $derived(!!frameGuide?.guide);

  const plateTitle = $derived(off ? `${t('widgets.unavailable.title')}: ${t('widgets.unavailable.resize_to_fit')}` : t('widgets.unavailable.title'));

  async function report(): Promise<void> {
    if (sent === 'sending' || sent === 'sent') return;
    sent = 'sending';
    sent = (await onReport()) ? 'sent' : 'failed';
  }
</script>

<div
  class="oc-refusal"
  class:oc-refusal--brief={step === 'brief'}
  class:oc-refusal--icon={step === 'icon'}
  data-widget-refusal={check.reason}
  data-widget-unavailable
  data-plate-step={step}
  role="status"
  title={step === 'full' ? undefined : plateTitle}
  bind:this={plate}
>
  <div class="oc-refusal-plate">
    <span class="oc-refusal-icon" aria-hidden="true"><Icon name="components" size={18} /></span>
    {#if step === 'icon'}
      <span class="oc-visually-hidden">{plateTitle}</span>
    {:else if step === 'brief' && off}
      <span class="oc-refusal-hint" data-resize-hint>{t('widgets.unavailable.resize_to_fit')}</span>
    {:else}
      <span class="oc-refusal-title">{t('widgets.unavailable.title')}</span>
    {/if}
    {#if step === 'full'}
    <span class="oc-refusal-detail">{detail}</span>
    {#if off}
      <span class="oc-refusal-hint" data-resize-hint>{t('widgets.unavailable.resize_to_fit')}</span>
    {/if}
    <div class="oc-refusal-actions">
      {#if onFix && check.suggest}
        {@const size = check.suggest}
        <Button data-refusal-fix onclick={() => onFix?.(size)}
          >{t('widgets.refusal.make_it_fit')}</Button
        >
      {/if}
      <Button
        data-refusal-report
        disabled={sent === 'sending' || sent === 'sent'}
        onclick={() => void report()}
        >{sent === 'sent'
          ? t('widgets.refusal.reported')
          : sent === 'failed'
            ? t('widgets.refusal.report_failed')
            : t('widgets.refusal.report')}</Button
      >
    </div>
    {/if}
  </div>
</div>

<style>
  @layer components {
    .oc-refusal {
      position: relative;
      height: 100%;
      min-height: 0;
      display: grid;
      place-content: center;
      justify-items: center;
      padding: var(--oc-space-2);
      overflow: hidden;
      background-image: repeating-linear-gradient(
        135deg,
        transparent 0 6px,
        color-mix(in srgb, var(--oc-line-rule) 55%, transparent) 6px 7px
      );
    }

    .oc-refusal-plate {
      display: grid;
      justify-items: center;
      gap: var(--oc-space-1);
      max-width: 240px;
      padding: var(--oc-space-1) var(--oc-space-2);
      background: var(--oc-ground-field);
      border: var(--oc-border) solid var(--oc-line-rule);
      border-radius: var(--oc-radius-sm);
      text-align: center;
      font-family: var(--oc-font);
    }

    .oc-refusal-icon {
      display: inline-flex;
      color: var(--oc-text-dim);
    }

    .oc-refusal-title {
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-label);
    }

    .oc-refusal-detail {
      color: var(--oc-text-dim);
      font-size: var(--oc-fs-hint);
    }

    .oc-refusal-hint {
      display: inline-flex;
      align-items: center;
      gap: var(--oc-space-1);
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-hint);
    }

    .oc-refusal-actions {
      display: flex;
      flex-wrap: wrap;
      justify-content: center;
      gap: var(--oc-space-1);
    }

    .oc-refusal-actions [data-btn] {
      font-size: var(--oc-fs-hint);
    }

    .oc-refusal--brief .oc-refusal-plate {
      gap: 2px;
    }

    .oc-refusal--icon {
      padding: 0;
    }

    .oc-refusal--icon .oc-refusal-plate {
      padding: 1px;
    }

    .oc-visually-hidden {
      position: absolute;
      width: 1px;
      height: 1px;
      overflow: hidden;
      clip-path: inset(50%);
      white-space: nowrap;
    }
  }
</style>
