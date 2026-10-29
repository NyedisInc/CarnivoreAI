
<script lang="ts">
    import { stampLabel, type Translate } from '../sdk';
    import { Icon, buttonAttrs } from '../sdk/ui';
    import { gigabytes, megabytes } from './bytes';
    import type { RestorePoint } from './points-api';

    interface Props {
        points: readonly RestorePoint[];
        keep: number | null;
        usedBytes: number;
        capBytes: number;
        busy: ReadonlySet<string>;
        t: Translate;
        onPin: (id: string, pinned: boolean) => void;
        onRestore: (id: string) => void;
    }

    const { points, keep, usedBytes, capBytes, busy, t, onPin, onRestore }: Props = $props();

    const mine = $derived(points.reduce((sum, p) => sum + (p.sizeBytes ?? 0), 0));
    const fill = $derived(capBytes > 0 ? Math.min(100, Math.max(2, (usedBytes / capBytes) * 100)) : 0);
    const reasonKey = (r: string): string => `cplug.save.tab.reason.${['kill', 'remove', 'sleep', 'restart', 'clear'].includes(r) ? r : 'other'}`;
</script>

<div class="rpt-frame" data-restore-points>
    <div class="rpt-bar">
        <span>{t('cplug.save.tab.kept', { count: points.length, keep: keep ?? points.length, size: megabytes(mine) })}</span>
        <span class="rpt-bar__grow"></span>
        {#if capBytes > 0}
            <span class="rpt-meter" aria-hidden="true"><i style="width:{fill}%"></i></span>
            <span>{t('cplug.save.tab.of_cap', { used: gigabytes(usedBytes), cap: gigabytes(capBytes) })}</span>
        {/if}
    </div>
    <table class="rpt-table">
        <thead>
            <tr>
                <th>{t('cplug.save.tab.col.taken')}</th>
                <th>{t('cplug.save.tab.col.on')}</th>
                <th>{t('cplug.save.tab.col.turns')}</th>
                <th>{t('cplug.save.tab.col.size')}</th>
                <th>{t('cplug.save.tab.col.pin')}</th>
                <th></th>
            </tr>
        </thead>
        <tbody>
            {#each points as point (point.id)}
                <tr data-point-id={point.id}>
                    <td>{stampLabel(point.takenAt)}</td>
                    <td>
                        <span class="rpt-why">
                            <span class="rpt-why__k" class:rpt-why__k--fs={point.failsafe}>{t(reasonKey(point.reason))}</span>
                            {#if point.failsafe}<span class="ph-tag ph-tag--dash">{t('cplug.save.tab.failsafe')}</span>{/if}
                            {#if point.pinned}<span class="ph-tag rpt-tag">{t('cplug.save.tab.pinned')}</span>{/if}
                            {#if point.imported}<span class="ph-tag rpt-tag" data-imported title={t('cplug.save.tab.imported_title')}>{t('cplug.save.tab.imported')}</span>{/if}
                            {#each point.labels ?? [] as label (label)}<span class="ph-tag ph-tag--dash" data-label>{label}</span>{/each}
                        </span>
                    </td>
                    <td class="rpt-table__sz">{point.turns ?? ''}<span class="rpt-table__mo">{t('cplug.save.tab.turns_word')}</span></td>
                    <td class="rpt-table__sz">
                        {#if point.sizeBytes !== null}{t('cplug.save.tab.size', { size: megabytes(point.sizeBytes) })}{/if}
                        {#if point.rawBytes !== null}<span class="rpt-table__dim">{t('cplug.save.tab.of_raw', { raw: megabytes(point.rawBytes) })}</span>{/if}
                    </td>
                    <td>
                        
                        <button
                            type="button"
                            {...buttonAttrs('secondary', 'icon')}
                            aria-pressed={point.pinned}
                            aria-label={point.pinned ? t('cplug.save.tab.unpin') : t('cplug.save.tab.pin')}
                            title={point.pinned ? t('cplug.save.tab.unpin_title') : t('cplug.save.tab.pin_title')}
                            data-pin
                            disabled={busy.has(point.id)}
                            onclick={() => onPin(point.id, !point.pinned)}><Icon name="pin" size={12} /></button
                        >
                    </td>
                    <td class="rpt-table__acts">
                        <button type="button" class="oc-btn oc-btn--sm rpt-action" data-restore="exact" disabled={busy.has(point.id)} onclick={() => onRestore(point.id)}
                            ><Icon name="reset" size={10} />{t('cplug.save.tab.resume_exact')}</button
                        >
                    </td>
                </tr>
            {/each}
        </tbody>
    </table>
</div>

<style>
    @layer components {
        .rpt-tag {
            border-color: color-mix(in srgb, var(--oc-cyan) 45%, transparent);
            color: var(--oc-cyan);
        }

        .rpt-meter {
            display: inline-block;
            width: 90px;
            height: 5px;
            overflow: hidden;
            border-radius: 1px;
            background: color-mix(in srgb, var(--oc-text-primary) 14%, transparent);
        }

        .rpt-meter i {
            display: block;
            height: 100%;
            background: var(--oc-cyan);
        }

        .rpt-action {
            --_bd: color-mix(in srgb, var(--oc-cyan) 65%, transparent);
            border-style: dashed;
            border-color: var(--_bd);
            color: var(--oc-cyan);
        }

        .rpt-frame {
            overflow-x: auto;
            border: 1px dashed color-mix(in srgb, var(--oc-cyan) 45%, transparent);
            border-radius: var(--oc-radius-sm);
        }

        .rpt-frame :global(.oc-ibtn[aria-pressed='true']) {
            border-color: color-mix(in srgb, var(--oc-cyan) 65%, transparent);
            color: var(--oc-cyan);
        }

        .rpt-bar {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: var(--oc-space-3);
            padding: 6px var(--oc-space-3);
            box-shadow: inset 0 -1px 0 var(--oc-line-rule);
            color: var(--oc-text-muted);
        }

        .rpt-bar__grow {
            flex: 1;
        }

        .rpt-table {
            width: 100%;
            border-collapse: collapse;
        }

        .rpt-table th {
            padding: 6px var(--oc-space-2);
            box-shadow: inset 0 -1px 0 var(--oc-line-rule);
            font-size: var(--oc-fs-micro, 10px);
            font-weight: normal;
            letter-spacing: 0.8px;
            text-align: left;
            text-transform: uppercase;
            color: var(--oc-text-muted);
            white-space: nowrap;
        }

        .rpt-table td {
            padding: 5px var(--oc-space-2);
            box-shadow: inset 0 -1px 0 var(--oc-line-rule);
            vertical-align: middle;
            white-space: nowrap;
        }

        .rpt-table tr:last-child td {
            box-shadow: none;
        }

        .rpt-table__sz {
            color: var(--oc-text-secondary);
        }

        .rpt-table__dim {
            margin-left: var(--oc-space-1);
            color: var(--oc-text-dim);
        }

        .rpt-table__mo {
            display: none;
        }

        .rpt-table td.rpt-table__acts {
            text-align: right;
            white-space: normal;
        }

        .rpt-table__acts > :global(* + *) {
            margin-left: var(--oc-space-1);
        }

        .rpt-why {
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }

        .rpt-why__k {
            font-size: var(--oc-fs-micro, 10px);
            letter-spacing: var(--oc-tracking-label, 0.6px);
            text-transform: uppercase;
            color: var(--oc-cyan);
        }

        .rpt-why__k--fs {
            color: var(--oc-text-muted);
        }

        @container ph (max-width: 760px) {
            .rpt-table thead {
                display: none;
            }

            .rpt-table tr {
                display: grid;
                grid-template-columns: minmax(0, 1fr) auto;
                padding: 6px var(--oc-space-2);
                box-shadow: inset 0 -1px 0 var(--oc-line-rule);
            }

            .rpt-table tr:last-child {
                box-shadow: none;
            }

            .rpt-table td {
                padding: 1px 0;
                box-shadow: none;
                white-space: normal;
            }

            .rpt-table td.rpt-table__acts {
                grid-column: 1 / 3;
                padding-top: 4px;
                text-align: left;
            }

            .rpt-table__mo {
                display: inline;
                margin-left: var(--oc-space-1);
            }
        }
    }
</style>
