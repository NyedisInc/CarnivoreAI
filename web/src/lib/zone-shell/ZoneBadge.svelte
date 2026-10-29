<script lang="ts">
  import { untrack } from 'svelte';
  import type { WidgetManifest } from '../../opscenter/widgets/types';
  import type { PlacementOptions } from '../../opscenter/widgets/placement-options';
  import { activeScopeFor } from '../../opscenter/widgets/active-scope';
  import Icon from '../../opscenter/ui/Icon.svelte';
  import { alertBadgeEnabled, alertBadgeText, alertCountSource } from '../session-rail/alert-counts';
  import { BadgeCue } from '../sidebar-widgets/rail-keys.svelte';
  import { t } from '../i18n/index.svelte';

  let {
    manifest,
    options,
    count: given,
    global = false,
    markPx = 8,
  }: { manifest?: WidgetManifest; options?: PlacementOptions; count?: number | null; global?: boolean; markPx?: number } = $props();

  const source = $derived(manifest ? alertCountSource(manifest.id) : null);
  const enabled = $derived(manifest ? alertBadgeEnabled(manifest.id) : false);
  const scope = $derived(manifest ? activeScopeFor(manifest) : null);

  const heldSessionId = $derived(scope?.sessionId ?? null);

  $effect(() => {
    const held = source;
    void heldSessionId;
    if (!held || !enabled) return;
    return untrack(() => held.hold?.(scope));
  });

  const count = $derived(given !== undefined ? given : source && enabled ? source.read(scope, options) : null);
  const text = $derived(alertBadgeText(count));

  const cue = new BadgeCue();
  $effect(() => {
    cue.note([{ id: 'badge', count: count ?? 0 }]);
  });
  $effect(() => () => cue.dispose());
</script>

{#if text}
  <span class="zone-badge" data-rail-badge={count} data-cue={cue.id !== null ? 'on' : undefined} role="status" aria-label={t('session_rail.badge', { count: count ?? 0 })}>{text}</span>
{/if}
{#if global}
  <span class="zone-badge-globe" data-widget-globe style={`width: ${markPx}px; height: ${markPx}px`} aria-hidden="true"><Icon name="globe" size={markPx} strokeWidth={2} /></span>
{/if}

<style>
  @layer components {
    .zone-badge {
      position: absolute;
      top: -2px;
      right: -2px;
      box-sizing: border-box;
      min-width: 14px;
      height: 14px;
      padding: 0 2px;
      border: var(--oc-border) solid var(--oc-yellow);
      border-radius: var(--oc-radius-sm);
      background: color-mix(in oklab, var(--oc-yellow) 16%, var(--oc-ground-titlerow));
      color: var(--oc-yellow);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-micro, 10px);
      font-variant-numeric: tabular-nums;
      line-height: 12px;
      text-align: center;
      pointer-events: none;
    }

    .zone-badge[data-cue='on'] {
      animation: zone-badge-cue 0.9s ease-out 2;
    }

    @keyframes zone-badge-cue {
      0%, 100% { box-shadow: 0 0 0 0 transparent; }
      40% { box-shadow: 0 0 10px 0 color-mix(in srgb, var(--oc-yellow) 55%, transparent); }
    }

    @media (prefers-reduced-motion: reduce) {
      .zone-badge[data-cue='on'] { animation: none; }
    }

    :global([data-bar-size='compact']) .zone-badge {
      top: -1px;
      right: -1px;
      min-width: 6px;
      width: 6px;
      height: 6px;
      padding: 0;
      font-size: 0;
      line-height: 0;
      background: var(--oc-yellow);
    }

    .zone-badge-globe {
      position: absolute;
      right: 1px;
      bottom: 1px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border-radius: 50%;
      background: var(--oc-ground-panel);
      color: currentColor;
      pointer-events: none;
    }
  }
</style>
