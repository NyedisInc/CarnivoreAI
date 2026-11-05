
<script lang="ts" module>
    import type { BarPose } from './BarPicture.svelte';

    export interface Choice<V extends string = string> {
        value: V;
        name: string;
        note?: string;
        isDefault?: boolean;
        aria: string;
        pose: readonly [BarPose, BarPose];
    }
</script>

<script lang="ts" generics="V extends string">
    import { t } from '../../i18n/index.svelte';
    import BarPicture from './BarPicture.svelte';

    interface Props {
        label: string;
        choices: readonly Choice<V>[];
        value: V;
        onSelect: (value: V) => void;
        dim?: boolean;
        dimNote?: string;
    }
    const { label, choices, value, onSelect, dim = false, dimNote = '' }: Props = $props();

    function key(event: KeyboardEvent, index: number): void {
        const step = event.key === 'ArrowRight' || event.key === 'ArrowDown' ? 1 : event.key === 'ArrowLeft' || event.key === 'ArrowUp' ? -1 : 0;
        if (step === 0) return;
        event.preventDefault();
        const next = choices[(index + step + choices.length) % choices.length];
        if (next) {
            onSelect(next.value);
            queueMicrotask(() => (event.currentTarget as HTMLElement | null)?.parentElement?.querySelector<HTMLElement>(`[data-value="${next.value}"]`)?.focus());
        }
    }
</script>

<div class="wp-strip" class:wp-strip--dim={dim}>
    <span class="wp-strip__label">{label}{#if dim && dimNote}<span class="wp-strip__note"> - {dimNote}</span>{/if}</span>
    <div class="wp-strip__row" role="radiogroup" aria-label={label}>
        {#each choices as choice, index (choice.value)}
            {@const on = choice.value === value}
            <button type="button" class="wp-pic" role="radio" data-base-exempt="a picture radio: the button is the picture it picks, drawn by settings.css" aria-checked={on} aria-label={choice.aria} data-value={choice.value}
                tabindex={on ? 0 : -1} onclick={() => onSelect(choice.value)} onkeydown={(event) => key(event, index)}>
                <BarPicture side={choice.pose[0]} bottom={choice.pose[1]} />
                <span class="wp-pic__caption">
                    <span class="wp-pic__name">{choice.name}</span>
                    <span class="wp-pic__figure">{#if choice.isDefault}<span class="wp-pic__default">{t('widgets.settings.default')}</span>{/if}{#if choice.note}<span class="wp-pic__note">{choice.note}</span>{/if}</span>
                    <span class="wp-pic__check" aria-hidden="true"></span>
                </span>
            </button>
        {/each}
    </div>
</div>
