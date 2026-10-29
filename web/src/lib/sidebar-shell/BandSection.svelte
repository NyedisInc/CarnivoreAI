
<script lang="ts">
    import BandSection from './BandSection.svelte';
    import Band from './Band.svelte';
    import SidebarRow from './SidebarRow.svelte';
    import { bandEvents } from './row-events';
    import { sectionOfBand } from '../drawer/section-order';
    import type { SectionPlan } from './plan';
    import { BAND_PROJECT_PREFIX } from '../drawer/group-store';
    import { projectColorPreview } from '../project-colors/preview.svelte';

    let { s }: { s: SectionPlan } = $props();

    const section = $derived(s.nested ? null : sectionOfBand(s.key));
    const block = $derived(s.key.startsWith(BAND_PROJECT_PREFIX) ? (projectColorPreview(Number(s.key.slice(BAND_PROJECT_PREFIX.length))) ?? s.blockColor) : s.blockColor);
</script>

<Band kind={s.nested ? 'session-sidebar-group--nested' : ''} attrs={{ 'data-group': s.key, 'data-section': section ?? undefined, ...s.colourAttrs, 'data-collapsed': s.collapsed ? '1' : '0', 'data-count': String(s.count), 'data-block': s.blockColor ? '1' : undefined }} heading={s.heading} bodyId={s.bodyId} {block} gestures={s.nested ? null : bandEvents()}>{#each s.rows as r (r.key)}<SidebarRow {r} />{/each}{#if s.empty}<div class="session-sidebar-company__empty">{s.empty}</div>{/if}{#if s.spawned}{@const sp = s.spawned}<Band attrs={{ 'data-group': sp.key, 'data-collapsed': sp.collapsed ? '1' : '0', 'data-count': String(sp.count) }} heading={sp.heading}>{#each sp.rows as r (r.key)}<SidebarRow {r} />{/each}</Band>{/if}{#each s.children ?? [] as child (child.key)}<BandSection s={child} />{/each}</Band>
