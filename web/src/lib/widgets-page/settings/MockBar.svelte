
<script lang="ts">
    import type { Snippet } from 'svelte';
    import Icon from '../../../opscenter/ui/Icon.svelte';
    import type { BarSize } from '../../widget-bars/bar-settings.svelte';
    import { BAR_SIZES } from '../../widget-bars/bar-size';
    import PinnedKeyBadge from '../../widget-bars/PinnedKeyBadge.svelte';
    import type { RailEdge } from '../../session-rail/rail-model';
    import type { MockKey } from './mock-model';

    interface Props {
        edge: RailEdge;
        size: BarSize;
        keys: readonly MockKey[];
        label: string;
        selected?: string | null;
        open?: string | null;
        onPress?: (key: string) => void;
        badge?: (key: string) => string;
        nameOf?: (key: MockKey) => string;
        end?: Snippet;
    }
    const { edge, size, keys, label, selected = null, open = null, onPress, badge, nameOf, end }: Props = $props();
    const m = $derived(BAR_SIZES[size][edge]);
    const px = (n: number | null): string => (n === null ? 'auto' : `${n}px`);
</script>

<div role="group" class="wp-mockbar wp-mockbar--{edge}" data-bar-size={size} aria-label={label}
    style:--mb-thick="{m.bar}px" style:--mb-key-w={px(m.keyW)} style:--mb-key-h={px(m.keyH)} style:--mb-key-minw="{m.keyMinW}px" style:--mb-key-minh="{m.keyMinH}px" style:--mb-pad="{m.pad}px" style:--mb-gap="{m.gap}px" style:--mb-keypad={m.keyPad} style:--mb-label-maxw={m.labelMaxW > 0 ? `${m.labelMaxW}px` : 'none'}>
    {#each keys as one (one.key)}
        <button type="button" class="wp-key wp-key--{m.label}" data-key={one.key} data-btn="quiet" data-size="bare"
            aria-label={nameOf ? nameOf(one) : one.title} aria-pressed={selected === null ? undefined : selected === one.key} aria-expanded={open === null ? undefined : open === one.key} onclick={() => onPress?.(one.key)}>
            <span class="wp-key__icon" style:color="var(--{one.tone})"><Icon name={one.icon} size={m.icon} /></span>
            {#if m.label !== 'none'}<span class="wp-key__label">{one.title}</span>{/if}
            {#if badge}<PinnedKeyBadge letter={badge(one.key)} compact={size === 'compact'} />{/if}
        </button>
    {/each}
    {#if end}<span class="wp-mockbar__end">{@render end()}</span>{/if}
</div>
