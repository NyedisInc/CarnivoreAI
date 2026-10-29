<script lang="ts">
  import type { Zone } from '../../engine/tab-split';
  import { t } from '../../../lib/i18n/index.svelte';

  let { zone }: { zone: Zone | null } = $props();

  const PLACE: Record<Zone, string> = {
    left: 'tw:inset-y-0 tw:left-0 tw:w-1/2',
    right: 'tw:inset-y-0 tw:right-0 tw:w-1/2',
    top: 'tw:inset-x-0 tw:top-0 tw:h-1/2',
    bottom: 'tw:inset-x-0 tw:bottom-0 tw:h-1/2',
    center: 'tw:inset-0',
  };
</script>

{#if zone}
  <div
    class="tw:pointer-events-none tw:absolute tw:inset-0 tw:z-20"
    data-drop-zone={zone}
    aria-hidden="true"
  >
    <div
      class={`tw:absolute tw:flex tw:items-center tw:justify-center tw:border-2 tw:border-[var(--oc-orange)] tw:bg-[color-mix(in_srgb,var(--oc-orange)_18%,transparent)] tw:text-xs tw:text-[var(--oc-orange)] ${PLACE[zone]}`}
    >
      {t(`opscenter.tabs.drop_${zone}`)}
    </div>
  </div>
{/if}
