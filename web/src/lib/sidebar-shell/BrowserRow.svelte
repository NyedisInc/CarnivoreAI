
<script lang="ts">
    import Icon from '../../opscenter/ui/Icon.svelte';
    import { shiftKey, watchShift } from '../../opscenter/lib/shift-held.svelte';
    import HeadingRenameEditor from './HeadingRenameEditor.svelte';
    import type { BrowserRowPlan } from './row-plan';
    import RowChip from './RowChip.svelte';
    import RowMenuTrigger from './RowMenuTrigger.svelte';
    import RowPin from './RowPin.svelte';
    import { isRowEditing } from './row-rename';

    let { p }: { p: BrowserRowPlan } = $props();

    const editing = $derived(isRowEditing(p.attrs['data-name'] || '', p.attrs['data-band']));
    $effect(() => watchShift());
    const shiftClose = $derived(shiftKey.held && !editing);

    const globe = $derived({
        width: '14', height: '14', viewBox: '0 0 24 24', stroke: 'currentColor', 'stroke-width': '2',
        fill: p.globe.live && !p.globe.page && !p.globe.file ? 'currentColor' : 'none',
        'fill-opacity': p.globe.live && !p.globe.page && !p.globe.file ? '0.35' : '0',
        'stroke-opacity': p.globe.live || p.globe.page || p.globe.file ? '1' : '0.55',
        'aria-hidden': 'true' as const,
    });
</script>

<div {...p.attrs} data-editing={editing ? '1' : undefined} data-shift-close={shiftClose ? '1' : undefined}><div class="session-sidebar-row-main"><RowChip chip={{ attrs: p.globe.attrs }}>{#if p.icon}<Icon name={p.icon} size={14} strokeWidth={2} />{:else}<svg {...globe}>{#if p.globe.file}<path d="M5 3h9l5 5v13H5Zm9 0v5h5M10 12l-2 2.5 2 2.5m4-5 2 2.5-2 2.5"></path>{:else if p.globe.page}<path d="M5 3h9l5 5v13H5Zm9 0v5h5M8 13h8m-8 4h8"></path>{:else}<circle cx="12" cy="12" r="9"></circle><path fill="none" d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18"></path>{/if}</svg>{/if}</RowChip><span {...p.name.attrs} hidden={editing}>{p.name.text}</span>{#if editing}<HeadingRenameEditor />{/if}{#if p.dirty}<RowChip chip={{ attrs: p.dirty }} />{/if}{#if p.subtitle}<RowChip chip={p.subtitle} />{/if}{#if p.popOut}<RowChip chip={{ attrs: p.popOut }}><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 4h6v6m0-6-9 9M18 14v6H4V6h6"></path></svg></RowChip>{/if}{#if p.pin}{#if p.pin}{#if p.pin}<RowPin attrs={p.pin} />{/if}{/if}{/if}{#if p.menu}<RowMenuTrigger spec={p.menu} />{/if}{#if shiftClose}<span class="session-sidebar-row-shift-close"><RowChip chip={{ attrs: p.closeKey }}><Icon name="close" size={14} strokeWidth={2} /></RowChip></span>{/if}</div></div>
