
<script lang="ts">
    import Icon from '../../opscenter/ui/Icon.svelte';
    import { kindIcon } from './card';
    import { kindLabel } from '../../../../client/js/labels/catalog-kind.js';
    import type { Translate } from '../sessions/types';
    import './kind-band.css';

    interface Props {
        kind: string | null;
        size?: 'sm' | 'md' | 'lg';
        t: Translate;
        bare?: boolean;
    }

    const { kind, size = 'md', t, bare = false }: Props = $props();

    const GLYPH = { sm: 9, md: 14, lg: 16 } as const;
    const label = $derived(kindLabel(kind, t) ?? kind ?? '');
    const modifier = $derived(kind && /^[a-z]+$/.test(kind) ? kind : 'unknown');
    const icon = $derived(kindIcon(kind) ?? 'grid');
</script>

<span class="kind-mark kind-mark--{modifier} kind-mark--{size}" class:kind-mark--bare={bare} role="img" aria-label={label}>
    <Icon name={icon} size={GLYPH[size]} strokeWidth={1.75} />
</span>

<style>
    .kind-mark {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        flex: none;
        box-sizing: border-box;
        border: 1px solid var(--oc-line-rule);
        border-radius: 2px;
        background: transparent;
        color: var(--oc-text-secondary);
        line-height: 0;
    }

    .kind-mark--sm {
        width: 12px;
        height: 12px;
    }

    .kind-mark--md {
        width: 20px;
        height: 20px;
    }

    .kind-mark--lg {
        width: 24px;
        height: 24px;
    }

    .kind-mark--loadout {
        background: transparent;
        border-color: var(--oc-line-rule);
        color: var(--oc-text-secondary);
    }

    .kind-mark--mod {
        background: var(--oc-kind-mod);
        border-color: var(--oc-kind-mod);
        color: var(--oc-kind-ink);
    }

    .kind-mark--skill {
        background: var(--oc-kind-skill);
        border-color: var(--oc-kind-skill);
        color: var(--oc-kind-ink);
    }

    .kind-mark--theme {
        background: var(--oc-kind-theme);
        border-color: var(--oc-kind-theme);
        color: var(--oc-kind-ink);
    }

    .kind-mark--plugin {
        background: var(--oc-kind-plugin);
        border-color: var(--oc-kind-plugin);
        color: var(--oc-kind-ink);
    }

    .kind-mark.kind-mark--bare {
        width: auto;
        height: auto;
        border: 0;
        border-radius: 0;
        background: transparent;
        color: var(--oc-text-secondary);
    }

    .kind-mark--bare.kind-mark--mod {
        color: var(--oc-kind-mod);
    }

    .kind-mark--bare.kind-mark--skill {
        color: var(--oc-kind-skill);
    }

    .kind-mark--bare.kind-mark--theme {
        color: var(--oc-kind-theme);
    }

    .kind-mark--bare.kind-mark--plugin {
        color: var(--oc-kind-plugin);
    }
</style>
