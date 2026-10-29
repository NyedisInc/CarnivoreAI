
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import {
        CONTEXT_SEGMENTS,
        WINDOW_SCALE_STOPS,
        filledSegments,
        windowMeterText,
        scaleStepFor,
    } from '../../../../client/js/labels/usage-panel.js';
    import LimitGauge from '../../opscenter/ui/LimitGauge.svelte';
    import { paceOf } from '../../../../client/js/labels/pace.js';
    import {
        LEDGER_KEYS,
        formatPercent,
        formatResetIn,
        formatWindowLabel,
        type LedgerTotalWindow,
        type LedgerWindow,
    } from './ledger-model';

    interface Props {
        windows: (LedgerWindow | LedgerTotalWindow)[];
        now: number;
        t: Translate;
        hero?: boolean;
    }

    const { windows, now, t, hero = false }: Props = $props();

    function measured(pct: number | null | undefined): pct is number {
        return typeof pct === 'number' && Number.isFinite(pct);
    }
</script>

{#if windows.length === 0}
    <p class="ledger-usage__none">{t(LEDGER_KEYS.windowsNone)}</p>
{:else if hero}
    <ul class="ledger-hero">
        {#each windows as window, index (window.kind + ':' + index)}
            {@const label = formatWindowLabel(window, t)}
            {@const pct = measured(window.used_pct) ? window.used_pct : null}
            {@const pace = paceOf(window, now, scaleStepFor(pct, WINDOW_SCALE_STOPS))}
            <li class="ledger-hero__win">
                <span class="ledger-hero__label">{label}</span>
                <span class="ledger-hero__figure" class:ledger-hero__figure--none={pct === null}
                    >{pct === null ? t(LEDGER_KEYS.notMeasured) : formatPercent(pct, t)}</span
                >
                <LimitGauge
                    segments={CONTEXT_SEGMENTS}
                    filled={filledSegments(pct)}
                    scale={pace.scale}
                    paceElapsedPct={pace.elapsedPct}
                    paceState={pace.state}
                    meterText={pct === null
                        ? t(LEDGER_KEYS.meterLabel, { window: label })
                        : windowMeterText(label, pct, pace, t)}
                    height={8}
                    decorative={pct === null}
                />
                <span class="ledger-hero__reset">{formatResetIn(window.resets_at, now, t)}</span>
            </li>
        {/each}
    </ul>
{:else}
    <table class="ledger-windows">
        <thead>
            <tr>
                <th scope="col" class="oc-label">{t(LEDGER_KEYS.windowHead)}</th>
                <th scope="col" class="oc-label">{t(LEDGER_KEYS.windowUsedHead)}</th>
                <th scope="col" class="oc-label ledger-windows__end">
                    {t(LEDGER_KEYS.windowResetsHead)}
                </th>
            </tr>
        </thead>
        <tbody>
            {#each windows as window, index (window.kind + ':' + index)}
                {@const label = formatWindowLabel(window, t)}
                {@const percent = formatPercent(window.used_pct, t)}
                {@const pct = measured(window.used_pct) ? window.used_pct : null}
                {@const pace = paceOf(window, now, scaleStepFor(pct, WINDOW_SCALE_STOPS))}
                <tr class="ledger-window">
                    <th scope="row" class="ledger-window__name">{label}</th>
                    <td class="ledger-window__used">
                        <span class="ledger-window__meter">
                            <LimitGauge
                                segments={CONTEXT_SEGMENTS}
                                filled={filledSegments(pct)}
                                scale={pace.scale}
                                paceElapsedPct={pace.elapsedPct}
                                paceState={pace.state}
                                meterText={pct === null
                                    ? t(LEDGER_KEYS.meterLabel, { window: label })
                                    : windowMeterText(label, pct, pace, t)}
                                height={8}
                                decorative={pct === null}
                            />
                            <span class="ledger-window__pct">{percent}</span>
                        </span>
                    </td>
                    <td class="ledger-window__reset ledger-windows__end">
                        {formatResetIn(window.resets_at, now, t)}
                    </td>
                </tr>
            {/each}
        </tbody>
    </table>
{/if}

<style>
    .ledger-hero {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(96px, 1fr));
        gap: var(--oc-space-3);
        margin: 0;
        padding: 0;
        list-style: none;
    }

    .ledger-hero__win {
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-1);
        min-width: 0;
    }

    .ledger-hero__label {
        color: var(--oc-text-secondary);
        font-size: var(--oc-fs-micro, 10px);
        letter-spacing: var(--oc-tracking-label, 0.6px);
        text-transform: uppercase;
    }

    .ledger-hero__figure {
        color: var(--oc-text-primary);
        font-family: var(--font-mono);
        font-size: var(--oc-fs-figure, 20px);
        font-variant-numeric: tabular-nums;
        line-height: 1.1;
    }

    .ledger-hero__figure--none {
        color: var(--oc-text-muted);
        font-size: var(--oc-fs-body, 12px);
        line-height: 1.8;
    }

    .ledger-hero__reset {
        color: var(--oc-text-muted);
        font-size: var(--oc-fs-micro, 10px);
    }

    .ledger-usage__none {
        margin: 0;
        font-size: var(--oc-fs-body);
        color: var(--oc-text-muted);
    }

    .ledger-windows {
        width: 100%;
        border-collapse: collapse;
        font-size: var(--oc-fs-body);
    }

    .ledger-windows th,
    .ledger-windows td {
        padding: 3px 0;
        text-align: left;
        vertical-align: middle;
        font-weight: 400;
    }

    .ledger-windows thead th {
        padding-bottom: var(--oc-space-1);
    }

    .ledger-windows tr > :first-child,
    .ledger-windows .ledger-windows__end {
        width: 1%;
        white-space: nowrap;
    }

    .ledger-windows tr > :first-child {
        padding-right: 14px;
    }

    .ledger-window__name {
        color: var(--oc-text-secondary);
        text-transform: uppercase;
        letter-spacing: var(--oc-tracking-label, 0.6px);
    }

    .ledger-windows .ledger-windows__end {
        padding-left: var(--oc-space-3);
        text-align: right;
    }

    .ledger-window__reset {
        color: var(--oc-text-secondary);
        font-variant-numeric: tabular-nums;
    }

    .ledger-window__meter {
        display: flex;
        align-items: center;
        gap: 10px;
    }


    .ledger-window__pct {
        flex: 0 0 auto;
        min-width: 4.5ch;
        text-align: right;
        font-variant-numeric: tabular-nums;
        color: var(--oc-text-primary);
    }
</style>
