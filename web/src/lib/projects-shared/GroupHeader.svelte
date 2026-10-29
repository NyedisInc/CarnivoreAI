
<script lang="ts">
    import Icon from '../../opscenter/ui/Icon.svelte';

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
    <button type="button" class="ph-ghead__chev" aria-expanded={!folded} aria-label={toggleLabel} onclick={(e) => { e.stopPropagation(); onToggle(); }}>
        <Icon name={folded ? 'chevron-right' : 'chevron-down'} size={10} />
    </button>
    {#if onOpen}
        <button type="button" class="ph-ghead__name ph-ghead__open" data-open-project onclick={(e) => { e.stopPropagation(); onOpen(); }}>{label}</button>
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

        .ph-ghead__chev {
            display: inline-grid;
            place-items: center;
            width: 16px;
            height: 16px;
            padding: 0;
            border: 1px solid transparent;
            background: none;
            color: var(--oc-text-dim);
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

        .ph-ghead__open {
            cursor: pointer;
        }

        .ph-ghead__open:hover {
            color: var(--oc-text-bright);
        }

        .ph-ghead__tally {
            color: var(--oc-text-dim);
        }

        .ph-ghead--muted .ph-ghead__name {
            color: var(--oc-text-dim);
        }

        @media (max-width: 1023px) {
            .ph-ghead {
                min-height: 32px;
            }

            .ph-ghead__chev {
                width: 28px;
                height: 28px;
            }
        }
    }
</style>
