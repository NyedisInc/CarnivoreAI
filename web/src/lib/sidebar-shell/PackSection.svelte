
<script lang="ts">
    import Band from './Band.svelte';
    import Button from '../base/Button.svelte';
    import PackMarks from '../pack-machines/PackMarks.svelte';
    import PackMeter from '../pack-machines/PackMeter.svelte';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import { t } from '../i18n/index.svelte';
    import { toggleCollapsed } from '../drawer/store';
    import { announce, repaintDrawerRows } from './interaction-globals';
    import { hostOffKey } from './pack-filter';
    import { levelOf } from '../pack-machines/pack-meter-math';
    import { packStats, percentText, relayerReachable, specLine, stateWord } from './pack-stats';
    import { meshLinkOf, packSource } from './pack-source.svelte';
    import { fitRows } from './pack-fit';
    import type { PackPlan, PackRowPlan } from './plan';

    let { p }: { p: PackPlan } = $props();

    function toggleComputer(r: PackRowPlan): void {
        const off = toggleCollapsed(hostOffKey(r.id));
        repaintDrawerRows();
        announce(t(off ? 'sidebar.pack.row.now_off' : 'sidebar.pack.row.now_on', { name: r.label }));
    }

    const STATS = ['cpu', 'ram', 'disk'] as const;
    const meters = $derived(p.density === 'cozy' || p.density === 'detailed');

    let body = $state<HTMLElement | null>(null);
    $effect(() => {
        const el = body;
        if (!el) return;
        void p.rows; void p.density;
        const run = () => { if (!meters) fitRows(el); };
        run();
        const ro = new ResizeObserver(run);
        ro.observe(el);
        return () => ro.disconnect();
    });
</script>

<Band kind="session-sidebar-pack" attrs={{ 'data-section': p.key, 'data-collapsed': p.open ? '0' : '1', 'data-count': String(p.count) }} heading={p.heading} bind:body>{#each p.rows as r (r.id)}{@const m = r.machine}{@const snap = m.snapshot}{@const st = packStats(m)}{@const line = p.density === 'detailed' ? specLine(m) : ''}{#snippet stats()}{#if !snap}<span class="sb-pack-row__state">{stateWord(m.state, meshLinkOf(m), relayerReachable(packSource()))}</span>{:else if meters}<span class="sb-pack-row__stats" data-stats="meters"><PackMeter small tip={false} label={t('drawer.pack.cpu')} pct={st.cpu} text={percentText(st.cpu)} reservePct={snap.reserve?.cpu_pct} title={t('pack.meter.cpu_title', { load: snap.load.busy_cores ?? snap.load.load_1 ?? '-', cores: snap.load.cores ?? '-', reserve: snap.reserve?.cpu_pct ?? 0 })} /><PackMeter small tip={false} label={t('drawer.pack.ram')} pct={st.ram} text={percentText(st.ram)} reservePct={snap.reserve?.mem_pct} title={t('pack.meter.mem_title', { used: percentText(st.ram), reserve: snap.reserve?.mem_pct ?? 0 })} /><PackMeter small tip={false} label={t('drawer.pack.disk')} pct={st.disk} text={percentText(st.disk)} title={t('pack.meter.disk_title', { used: percentText(st.disk) })} /></span>{:else}<span class="sb-pack-row__stats sb-pack-row__stats--cols" data-stats="numbers">{#each STATS as k (k)}<span class="sb-pack-stat" data-stat={k} title={`${k.toUpperCase()} ${percentText(st[k])}`}><span class="sb-pack-stat__v" data-level={st[k] === null ? 'none' : levelOf(st[k])}>{percentText(st[k])}</span></span>{/each}</span>{/if}{/snippet}<Button variant="row" data-pack-computer={r.id} data-host-state={snap ? undefined : m.state} data-pack-off={r.off ? '' : undefined} aria-pressed={!r.off} aria-label={t('sidebar.pack.row.toggle', { name: r.label })} onclick={() => toggleComputer(r)}><span class="sb-pack-row__main">{#if r.lightHtml}<span class="sb-pack-row__light">{@html r.lightHtml}</span>{/if}<PackMarks self={r.self} link={r.link} tips={false} size={14} remoteIcon="server" />{#if r.alpha}<span class="sb-pack-row__wolf" data-mark="alpha" role="img" aria-label={t('drawer.pack.alpha')} title={t('drawer.pack.alpha')}><Icon name="wolf" size={14} /></span>{/if}<span class="sb-pack-row__name">{r.label}</span>{#if !meters}{@render stats()}{/if}</span>{#if meters}{@render stats()}{/if}{#if line}<span class="sb-pack-row__meta">{line}</span>{/if}</Button>{/each}</Band>

<style>
    @layer components {
        :global([data-pack-computer]) {
            display: flex;
            flex-direction: column;
            align-items: stretch;
            justify-content: center;
            box-sizing: border-box;
            width: 100%;
            min-width: 0;
            gap: 0;
            padding: 0;
            border: var(--oc-border) solid transparent;
            border-radius: var(--oc-radius);
            background: transparent;
            color: var(--oc-text-primary);
            font: inherit;
            text-align: start;
            cursor: pointer;
            transition: background 120ms ease, border-color 120ms ease;
        }
        :global([data-pack-computer]):hover { background: var(--oc-ground-hover); }
        :global([data-pack-computer][data-host-state]) { opacity: 0.55; }
        :global([data-pack-computer][data-pack-off]) { opacity: 0.55; }
        :global([data-pack-computer][data-pack-off]) .sb-pack-row__name { text-decoration: line-through; }
        .sb-pack-row__main {
            display: flex;
            align-items: center;
            gap: var(--sidebar-row-main-gap);
            min-width: 0;
        }
        .sb-pack-row__name {
            flex: 1;
            min-width: 3ch;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .sb-pack-row__wolf { display: inline-flex; flex: none; color: var(--oc-coral); }
        .sb-pack-row__light { display: inline-flex; flex: none; }
        .sb-pack-row__stats, .sb-pack-row__state {
            display: inline-flex;
            flex: none;
            align-items: center;
            justify-content: flex-end;
            gap: var(--oc-space-2);
            margin-inline-start: auto;
            font-family: var(--font-mono);
            font-variant-numeric: tabular-nums;
            white-space: nowrap;
        }
        .sb-pack-row__stats--cols {
            display: grid;
            grid-template-columns: repeat(3, 2.2rem);
            gap: var(--oc-space-2);
            text-align: right;
        }
        :global([data-pack-computer] > .sb-pack-row__stats), :global([data-pack-computer] > .sb-pack-row__state) {
            display: flex;
            margin-inline-start: 0;
            padding: 0 var(--oc-space-2) var(--oc-space-1-5) var(--oc-space-5);
            min-width: 0;
            overflow: hidden;
        }
        :global([data-pack-computer] > .sb-pack-row__stats[data-stats='meters']) {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: var(--oc-space-2);
        }
        .sb-pack-row__state { font-size: 0.8em; color: var(--oc-text-muted); }
        .sb-pack-stat { display: inline-flex; justify-content: flex-end; align-items: baseline; font-size: var(--oc-fs-micro); }
        .sb-pack-stat:global([data-hide]) { display: none; }
        .sb-pack-stat__v { font-weight: normal; color: var(--oc-text-muted); }
        .sb-pack-stat__v[data-level='high'] { color: var(--oc-yellow); }
        .sb-pack-stat__v[data-level='critical'] { color: var(--oc-coral); }
        .sb-pack-stat__v[data-level='none'] { color: var(--oc-text-dim); }
        .sb-pack-row__meta {
            padding: 0 var(--oc-space-2) var(--oc-space-1-5) var(--oc-space-5);
            font-family: var(--font-mono);
            font-size: 0.68em;
            color: var(--oc-text-muted);
            white-space: pre-wrap;
            overflow-wrap: anywhere;
        }

        :global(.session-sidebar-panel[data-density='compact']) :global([data-pack-computer]) { min-height: 26px; }
        :global(.session-sidebar-panel[data-density='compact']) .sb-pack-row__main {
            padding: var(--oc-space-1) var(--oc-space-2);
            line-height: 1.2;
            font-size: 0.82em;
        }
        :global(.session-sidebar-panel[data-density='cozy']) :global([data-pack-computer]) { min-height: 44px; }
        :global(.session-sidebar-panel:not([data-density='compact'])) .sb-pack-row__name { flex: none; max-width: 100%; }
        :global(.session-sidebar-panel[data-density='detailed']) :global([data-pack-computer]) { min-height: 62px; }
        :global(.session-sidebar-panel[data-density='cozy']) .sb-pack-row__main,
        :global(.session-sidebar-panel[data-density='detailed']) .sb-pack-row__main {
            padding: var(--oc-space-1-5) var(--oc-space-2) var(--oc-space-1);
            line-height: 1.35;
            font-size: 0.9em;
        }
    }
</style>
