
<script lang="ts">
    import Checkbox from '../base/Checkbox.svelte';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import { DEFAULT_WIDTH_PX } from '../drawer/resize';
    import { t as reactiveT } from '../i18n/index.svelte';
    import SessionRow from '../sidebar-shell/SessionRow.svelte';
    import { buildRowPlan, type SessionRowPlan } from '../sidebar-shell/row-plan';
    import type { RowHost } from '../sidebar-shell/row-host';
    import type { Translate } from '../sessions/types';
    import { previewHost, sampleRow } from './appearance/sample-row';
    import {
        ROW_DENSITIES,
        ROW_ICON_KINDS,
        rowIcons,
        type IconKind,
        type RowDensity,
    } from './row-icons-store.svelte';

    interface Props {
        t?: Translate;
        host?: RowHost;
    }
    const { t = reactiveT, host }: Props = $props();

    rowIcons.start();

    const KIND_ICON: Record<IconKind, string> = {
        agents: 'users',
        shells: 'terminal',
        timers: 'clock',
        cup: 'coffee',
        pin: 'pin',
        menu: 'kebab',
        context: 'activity',
        automations: 'status-scheduled',
    };

    const plans = $derived.by((): Record<RowDensity, SessionRowPlan> => {
        void rowIcons.value;
        const sample = sampleRow();
        const hostFor = previewHost(host);
        const out = {} as Record<RowDensity, SessionRowPlan>;
        for (const density of ROW_DENSITIES) {
            out[density] = buildRowPlan(sample as never, density, undefined, null, hostFor) as SessionRowPlan;
        }
        return out;
    });

    const densityLabel = (density: RowDensity): string => t(`settings.rowicons.density.${density}`);
    const kindLabel = (kind: IconKind): string => t(`settings.rowicons.kind.${kind}`);
</script>

<div class="rip">
    {#each ROW_DENSITIES as density (density)}
        <div class="rip__dens" data-density={density}>
            <div class="rip__sample">
                <span class="oc-sub">{densityLabel(density)} <span class="rip__lines">({t(`settings.rowicons.lines.${density}`)})</span></span>
                <div class="session-sidebar-panel rip__panel" data-density={density} style:--rip-w="{DEFAULT_WIDTH_PX}px" aria-hidden="true" inert>
                    <div class="session-sidebar-list">
                        <SessionRow p={plans[density]} />
                    </div>
                </div>
            </div>
            <div class="oc-grid-4 rip__checks">
                {#each ROW_ICON_KINDS as kind (kind)}
                    <Checkbox
                        bind:checked={() => rowIcons.effective(density, kind), (next) => rowIcons.set(density, kind, next)}
                        aria-label={t('settings.rowicons.toggle', { density: densityLabel(density), kind: kindLabel(kind) })}
                    >
                        {#snippet children()}<span class="rip__kind"><Icon name={KIND_ICON[kind]} size={12} />{kindLabel(kind)}</span>{/snippet}
                    </Checkbox>
                {/each}
            </div>
        </div>
    {/each}
</div>

<style>
    .rip {
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-3);
        width: 100%;
    }

    .rip__dens {
        display: grid;
        grid-template-columns: minmax(0, 1fr);
        gap: var(--oc-space-3);
        align-items: start;
    }

    @container oc-main (min-width: 720px) {
        .rip__dens {
            grid-template-columns: var(--rip-w, 320px) minmax(0, 1fr);
            gap: var(--oc-space-4);
        }
    }

    .rip__dens + .rip__dens {
        padding-top: var(--oc-space-3);
        box-shadow: inset 0 1px 0 var(--oc-control-line);
    }

    .rip__sample {
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-2);
        min-width: 0;
    }

    .rip__kind {
        display: inline-flex;
        align-items: center;
        gap: var(--oc-space-1-5);
    }

    .rip__lines {
        color: var(--oc-text-muted);
    }

    @container oc-main (min-width: 720px) {
        .rip__checks {
            padding-top: 20px;
        }
    }

    :global(.rip__dens .rip__panel.session-sidebar-panel) {
        position: relative;
        inset: auto;
        width: var(--rip-w, 320px);
        max-width: 100%;
        padding: 0;
        z-index: auto;
        transform: none;
        visibility: visible;
        transition: none;
        border: 1px solid var(--oc-control-line);
        border-radius: var(--oc-control-radius);
        overflow: hidden;
        pointer-events: none;
        font-size: medium;
    }

    :global(.rip__panel .session-sidebar-list) {
        flex: none;
        overflow: visible;
    }
</style>
