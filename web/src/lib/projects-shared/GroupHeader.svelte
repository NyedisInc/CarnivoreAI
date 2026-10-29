
<script lang="ts">
    import { Button, IconButton } from '../base';

    interface Props {
        label: string;
        tally: string;
        folded: boolean;
        onToggle: () => void;
        onOpen?: () => void;
        title?: string;
        toggleLabel: string;
        muted?: boolean;
    }

    const { label, tally, folded, onToggle, onOpen, title, toggleLabel, muted = false }: Props = $props();
</script>

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
<div class="ph-ghead" class:ph-ghead--muted={muted} {title} data-group-header onclick={onToggle}>
    <IconButton label={toggleLabel} variant="quiet" icon={folded ? 'chevron-right' : 'chevron-down'} iconSize={10} aria-expanded={!folded}
        data-group-chevron style="--_btn-ink: var(--oc-text-dim)" onclick={(e) => { e.stopPropagation(); onToggle(); }} />
    {#if onOpen}
        <Button variant="quiet" size="sm" data-open-project style="min-height: 0; padding: 0; font-weight: 700; letter-spacing: var(--oc-tracking-label, 0.6px); text-transform: uppercase; max-width: 100%; min-width: 0"
            onclick={(e) => { e.stopPropagation(); onOpen(); }}>{label}</Button>
    {:else}
        <span class="ph-ghead__name">{label}</span>
    {/if}
    {#if tally}<span class="ph-ghead__tally">{tally}</span>{/if}
</div>

<style>
    @layer components {
        .ph-ghead {
            display: flex;
            align-items: center;
            gap: var(--oc-space-1);
            min-height: 22px;
            padding: 0 var(--oc-space-3);
            background: var(--oc-ground-panel);
            box-shadow: inset 0 -1px 0 var(--oc-line-faint);
            font-size: var(--oc-fs-label, 11px);
            cursor: pointer;
        }

        .ph-ghead__name {
            padding: 0;
            border: 1px solid transparent;
            background: none;
            font: inherit;
            font-weight: 700;
            letter-spacing: var(--oc-tracking-label, 0.6px);
            text-align: left;
            text-transform: uppercase;
            color: var(--oc-text-secondary);
        }

        .ph-ghead__tally {
            color: var(--oc-text-dim);
        }

        .ph-ghead--muted .ph-ghead__name {
            color: var(--oc-text-dim);
        }

        .ph-ghead--muted [data-open-project] {
            --_btn-ink: var(--oc-text-dim);
        }

        @media (max-width: 1023px) {
            .ph-ghead {
                min-height: 32px;
            }
        }
    }
</style>
