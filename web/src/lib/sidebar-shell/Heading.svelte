
<script lang="ts">
    import FoldChevron from '../../opscenter/ui/FoldChevron.svelte';
    import HeadingRenameEditor from './HeadingRenameEditor.svelte';
    import { headingEvents } from './heading-events';
    import { headingRename } from './heading-rename.svelte';
    import { kebabSvg } from './kebab';
    import RowChip from './RowChip.svelte';
    import IconButton from '../base/IconButton.svelte';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import { t } from '../i18n/index.svelte';
    import { projects } from '../../opscenter/api/projects.svelte';
    import { openDrawerProjectTool } from './project-menu-windows.svelte';
    import { percentText } from './pack-stats';
    import type { HeadingPlan } from './plan';

    let { h, drawn = false }: { h: HeadingPlan; drawn?: boolean } = $props();

    function openMark(e: MouseEvent, projectId: string): void {
        e.stopPropagation();
        const found = (projects.data ?? []).find((p) => String(p.id) === projectId);
        if (found && found.id != null) openDrawerProjectTool({ kind: 'settings' }, { id: found.id, name: found.name });
    }

    const editing = $derived(headingRename.spec?.key === h.key);
    const isCompany = $derived(h.key.startsWith('c:'));
    const menuAttr = $derived(h.menu ? { [`data-${h.menu.kind}-menu`]: h.menu.id } : null);
</script>

<div class="session-sidebar-group__headerrow" data-band-kind={h.bandKind} data-editing={editing ? '1' : undefined} data-tint={h.tint ? '1' : undefined} style:--sb-tint={h.tint} {@attach drawn ? null : headingEvents()}><button type="button" class="session-sidebar-group__header" class:session-sidebar-group__header--projects={isCompany} data-group-toggle={h.key} aria-expanded={h.expanded ? 'true' : 'false'} aria-controls={h.bodyId} aria-label={h.title}><FoldChevron />{@html h.iconHtml}{@html h.pickedIconHtml}{@html h.ledHtml}<span class="session-sidebar-group__label" hidden={editing}>{h.label}{#if h.fxHtml}{@html h.fxHtml}{/if}</span>{#if editing}<HeadingRenameEditor />{/if}{#if h.projectCount !== undefined}<span class="sb-head-proj-count">{h.projectCount}</span>{/if}{#if h.inactive}<RowChip chip={h.inactive} />{/if}{#if h.badge}<RowChip chip={h.badge} />{/if}{@html h.rollupHtml}{#if h.featuresCount}<span class="sb-head-meta">{t('sidebar.project.features_count', { count: h.featuresCount })}</span>{:else if h.packHeaderStats}{@const ps = h.packHeaderStats}<span class="sb-head-pack-cols" data-pack-cols={ps.open ? 'labels' : 'avg'}><span title={ps.open ? 'CPU' : t('drawer.pack.avg_title', { metric: 'CPU' })}>{ps.open ? 'CPU' : percentText(ps.cpu)}</span><span title={ps.open ? 'RAM' : t('drawer.pack.avg_title', { metric: 'RAM' })}>{ps.open ? 'RAM' : percentText(ps.ram)}</span><span title={ps.open ? 'DISK' : t('drawer.pack.avg_title', { metric: 'DISK' })}>{ps.open ? 'DISK' : percentText(ps.disk)}</span></span>{:else if h.countSummary}<span class="sb-head-meta">{#if h.countSummary.live > 0}<span class="sb-head-meta__live">{h.countSummary.live} live</span>{/if}{h.countSummary.live > 0 ? ` · ${h.countSummary.total}` : h.countSummary.total}</span>{/if}</button>{#if h.packMark}{@const m = h.packMark}<IconButton variant="quiet" label={m.label} data-pack-mark={m.kind} onclick={(e) => openMark(e, m.projectId)}><Icon name="wolf" size={14} />{#if m.kind === 'leftover'}<i></i>{/if}</IconButton>{/if}{#if h.menu}<button type="button" class="oc-ibtn oc-ibtn--bare session-sidebar-group__menu" {...menuAttr} data-tooltip="" aria-label={h.menu.label} aria-haspopup="menu">{@html kebabSvg()}</button>{/if}</div>

<style>
    @layer components {
        :global([data-pack-mark]) { position: relative; color: var(--oc-coral); }
        :global([data-pack-mark='leftover']) { color: var(--oc-text-muted); }
        :global([data-pack-mark]) { margin-inline-end: calc(var(--oc-space-1) / -4); }
        :global([data-density='compact'] [data-pack-mark]) { margin-inline-end: calc(var(--oc-space-1) * -0.75); }
        :global([data-pack-mark] i) { position: absolute; top: 0; right: 0; width: var(--oc-space-1-5); height: var(--oc-space-1-5); border-radius: var(--oc-radius-circle); background: var(--oc-coral); }
        :global(.sb-head-proj-count) {
            flex: 0 0 auto;
            font-family: var(--font-mono);
            font-size: var(--oc-fs-micro);
            font-weight: normal;
            letter-spacing: normal;
            text-transform: none;
            color: var(--oc-text-dim);
            font-variant-numeric: tabular-nums;
        }
        :global(.sb-head-meta) {
            margin-left: auto;
            flex: 0 0 auto;
            font-family: var(--font-mono);
            font-size: var(--oc-fs-micro);
            font-weight: normal;
            letter-spacing: normal;
            text-transform: none;
            color: var(--oc-text-dim);
            font-variant-numeric: tabular-nums;
            white-space: nowrap;
        }
        :global([data-band-kind='company'] .sb-head-meta__live) {
            color: var(--oc-green-bright);
        }
        :global(.sb-head-pack-cols) {
            margin-left: auto;
            flex: 0 0 auto;
            display: grid;
            grid-template-columns: repeat(3, 2.2rem);
            gap: var(--oc-space-2);
            text-align: right;
            font-family: var(--font-mono);
            font-size: var(--oc-fs-micro);
            font-weight: normal;
            letter-spacing: normal;
            text-transform: none;
            color: var(--oc-text-muted);
            font-variant-numeric: tabular-nums;
        }
    }
</style>
