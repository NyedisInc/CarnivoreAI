<script lang="ts">
  /*  hidden  */
  import { Icon } from '../sdk/ui';
  import { TAIL_COUNT_MAX, TAIL_ORDER, kindsPresent, tailKindLook, type TailBadge, type TailKind } from './task-manager-tail-slots';
  import { countBadges } from './task-manager-status-folds.svelte';
  import './task-manager-tail.css';

  let { scope, badges = [], kinds, packed = false, opens, onOpen, active = null }: {
    scope: string;
    badges?: TailBadge[];
    kinds?: readonly TailKind[];
    packed?: boolean;
    opens?: (kind: TailKind) => boolean;
    onOpen?: (kind: TailKind) => void;
    active?: TailKind | null;
  } = $props();

  const byKind = $derived(new Map<TailKind, TailBadge>([...badges].reverse().map((badge) => [badge.kind, badge])));

  const columns = $derived(TAIL_ORDER.filter((kind) => (packed ? (byKind.get(kind)?.count ?? 0) > 0 : byKind.has(kind) || (kinds ?? kindsPresent([badges])).includes(kind))));
</script>

{#if !countBadges.hidden}
<span class="hd-tail" data-task-manager-tail={scope} data-packed={packed ? 'on' : undefined}>
  {#each columns as kind (kind)}
    {@const badge = byKind.get(kind)}
    {#if badge && badge.count > 0}
      {#if onOpen && opens?.(kind)}
        <button type="button" class="hd-slot hd-slot-key" style:--_mark={badge.color} data-task-manager-tail-slot={kind} data-filled="on" title={badge.title} aria-label={badge.title}
                aria-pressed={active === null ? undefined : active === kind} data-active={active === kind ? 'on' : undefined} onclick={(event) => { event.stopPropagation(); onOpen(kind); }}>
          <Icon name={badge.icon} size={11} strokeWidth={1.75} />
          <span class="hd-tail-n" class:hd-tail-over={badge.count > TAIL_COUNT_MAX}>{Math.min(badge.count, TAIL_COUNT_MAX)}</span>
        </button>
      {:else}
        <span class="hd-slot" style:--_mark={badge.color} data-task-manager-tail-slot={kind} data-filled="on" title={badge.title}>
          <Icon name={badge.icon} size={11} strokeWidth={1.75} />
          <span class="hd-tail-n" class:hd-tail-over={badge.count > TAIL_COUNT_MAX}>{Math.min(badge.count, TAIL_COUNT_MAX)}</span>
          <span class="oc-visually-hidden">{badge.title}</span>
        </span>
      {/if}
    {:else if !packed}
      {@const look = tailKindLook(kind)}
      <span class="hd-slot hd-slot-zero" style:--_mark={look.color} data-task-manager-tail-slot={kind} aria-hidden="true">
        <Icon name={look.icon} size={11} strokeWidth={1.75} />
        <span class="hd-tail-n">0</span>
      </span>
    {/if}
  {/each}
</span>
{/if}
