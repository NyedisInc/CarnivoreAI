
<script lang="ts">
    import Glyph from '../Glyph.svelte';
    import Button from '../base/Button.svelte';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import FoldChevron from '../../opscenter/ui/FoldChevron.svelte';
    import { providerMark } from '../sessions/agent-marks';
    import type { Translate } from '../sessions/types';
    import { LENSES, type LensGroup, type LensKey } from './lenses';

    interface Props {
        lens: LensKey;
        counts: Readonly<Record<LensKey, number>>;
        groups: readonly LensGroup[];
        inactive?: ReadonlySet<string>;
        current: string | null;
        listingDown: boolean;
        t: Translate;
        onLens: (key: LensKey) => void;
        onSection: (key: string) => void;
    }
    const { lens, counts, groups, inactive = new Set<string>(), current, listingDown, t, onLens, onSection }: Props = $props();

    const active = $derived(LENSES.findIndex((l) => l.key === lens));
    let inactiveOpen = $state(false);
    const activeGroups = $derived(groups.filter((g) => !inactive.has(g.key)));
    const inactiveGroups = $derived(groups.filter((g) => inactive.has(g.key)));
    const KEYS = ['updown', 'enter', 'space', 'leftright', 'slash'] as const;
</script>

{#snippet sub(g: LensGroup, nested = false)}
    <Button variant="row" data-sec={g.key} data-nested={nested ? '' : undefined} aria-current={g.key === current ? 'true' : undefined} data-zero={g.count === 0 ? '' : undefined} onclick={() => onSection(g.key)}>
        <span class="sp-rlab">
            {#if g.provider}<span class="sp-mark" aria-hidden="true">{@html providerMark(g.provider, 12).svg}</span>{/if}
            <span>{g.label}</span>
        </span>
        <span class="sp-n">{g.count}</span>
    </Button>
{/snippet}

<nav class="sp-rail" aria-label={t('sessions.page.lens.label')}>
    <div class="sp-label" style:order="-1">{t('sessions.page.lens.label')}</div>
    <div class="sp-rail-chips" role="group" aria-label={t('sessions.page.lens.rail')}>
        {#each LENSES as l, i (l.key)}
            {@const off = l.key === 'needs' && listingDown}
            <Button variant="row" data-lens={l.key} style="order: {i * 2}" aria-pressed={l.key === lens} data-zero={!off && counts[l.key] === 0 ? '' : undefined} disabled={off} onclick={() => onLens(l.key)}>
                <span class="sp-rlab">
                    {#if l.glyph}<Glyph name={l.icon} size={14} />{:else}<Icon name={l.icon} size={14} />{/if}
                    <span>{t(`sessions.page.lens.${l.key}`)}</span>
                </span>
                {#if off}<span class="sp-why">{t('sessions.page.lens.unavailable')}</span>{:else}<span class="sp-n">{counts[l.key]}</span>{/if}
            </Button>
        {/each}
    </div>
    <div class="sp-subs" role="group" aria-label={t('sessions.page.lens.groups')} style:order={active * 2 + 1}>
        {#if !(lens === 'needs' && listingDown)}
            {#each activeGroups as g (g.key)}
                {@render sub(g)}
            {/each}
            {#if inactiveGroups.length}
                <Button variant="row" data-inactive-toggle aria-expanded={inactiveOpen} onclick={() => (inactiveOpen = !inactiveOpen)}>
                    <span class="sp-rlab"><FoldChevron /><span>{t('sessions.page.lens.inactive')}</span></span>
                    <span class="sp-n">{inactiveGroups.length}</span>
                </Button>
                {#if inactiveOpen}
                    {#each inactiveGroups as g (g.key)}
                        {@render sub(g, true)}
                    {/each}
                {/if}
            {/if}
        {/if}
    </div>
    <div class="sp-keys" style:order="99">
        {#each KEYS as k (k)}<div><b>{t(`sessions.page.keys.${k}`)}</b> {t(`sessions.page.keys.${k}.what`)}</div>{/each}
    </div>
</nav>
