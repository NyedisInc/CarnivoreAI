
<script lang="ts">
    import { rowHost } from './row-host';
    import ModelMark from './ModelMark.svelte';
    import { keepAwakePlan, modelPlan, sharePlan } from './row-chips';
    import type { SidebarRow } from './legacy';

    let { info, part }: { info: Record<string, unknown>; part: 'lead' | 'tail' } = $props();

    const row = $derived({
        ...info,
        name: (info.tmux_session as string | null) ?? '',
        session_id: (info.session as { id?: string } | undefined)?.id,
    } as SidebarRow);
    const model = $derived(part === 'lead' ? modelPlan(row) : null);
    const share = $derived(part === 'tail' ? sharePlan(row) : null);
    const cup = $derived(part === 'tail' ? keepAwakePlan(row, rowHost()) : null);
    const upd = $derived(part === 'tail'
        ? (info.agent_update as { running?: unknown; installed?: unknown; ready?: boolean } | null | undefined)
        : null);
    const updateReady = $derived(!!upd && upd.ready === true
        && typeof upd.running === 'string' && typeof upd.installed === 'string');
    const updateTitle = $derived(updateReady ? `update ready: ${upd!.running} → ${upd!.installed}` : '');
    const updateSvg = $derived(updateReady
        ? ((globalThis as { SessionRowMenuIcons?: { svg(n: string, s: number): string } })
            .SessionRowMenuIcons?.svg('update-restart', 14) ?? '')
        : '');
</script>

{#if model}<ModelMark {model} />{/if}{#if share}<span class="session-sidebar-row-share oc-tab-mark-static" role="img" aria-label={share.attrs['aria-label']} title={share.attrs.title}>{@html share.svg}</span>{/if}{#if cup}<span class="session-sidebar-row-keep-awake oc-tab-mark-static" data-keep-awake={cup.attrs['data-keep-awake']} role="img" aria-label={cup.attrs['aria-label']} title={cup.attrs.title}>{@html cup.svg}</span>{/if}{#if updateReady}<span class="oc-tab-update" role="img" aria-label={updateTitle} title={updateTitle}>{@html updateSvg}</span>{/if}

<style>
    @layer components {
        .oc-tab-update { display: inline-flex; align-items: center; flex: 0 0 auto; color: var(--oc-green); }
        .oc-tab-mark-static { pointer-events: none; }
    }
</style>
