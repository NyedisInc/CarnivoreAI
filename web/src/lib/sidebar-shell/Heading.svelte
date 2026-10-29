
<script lang="ts">
    import FoldChevron from '../../opscenter/ui/FoldChevron.svelte';
    import HeadingRenameEditor from './HeadingRenameEditor.svelte';
    import { headingEvents } from './heading-events';
    import { headingRename } from './heading-rename.svelte';
    import { kebabSvg } from './kebab';
    import RowChip from './RowChip.svelte';
    import type { HeadingPlan } from './plan';

    let { h, drawn = false }: { h: HeadingPlan; drawn?: boolean } = $props();

    const editing = $derived(headingRename.spec?.key === h.key);
    const isCompany = $derived(h.key.startsWith('c:'));
    const menuAttr = $derived(h.menu ? { [`data-${h.menu.kind}-menu`]: h.menu.id } : null);
</script>

<div class="session-sidebar-group__headerrow" data-band-kind={h.bandKind} data-editing={editing ? '1' : undefined} data-tint={h.tint ? '1' : undefined} style:--sb-tint={h.tint} {@attach drawn ? null : headingEvents()}><button type="button" class="session-sidebar-group__header" class:session-sidebar-group__header--projects={isCompany} data-group-toggle={h.key} aria-expanded={h.expanded ? 'true' : 'false'} aria-controls={h.bodyId} aria-label={h.title}><FoldChevron />{@html h.iconHtml}{@html h.ledHtml}{@html h.pickedIconHtml}<span class="session-sidebar-group__label" hidden={editing}>{h.label}{#if h.fxHtml}{@html h.fxHtml}{/if}</span>{#if editing}<HeadingRenameEditor />{/if}{#if h.inactive}<RowChip chip={h.inactive} />{/if}{#if h.badge}<RowChip chip={h.badge} />{/if}{@html h.rollupHtml}</button>{#if h.menu}<button type="button" class="oc-ibtn oc-ibtn--bare session-sidebar-group__menu" {...menuAttr} data-tooltip="" aria-label={h.menu.label} aria-haspopup="menu">{@html kebabSvg()}</button>{/if}</div>
