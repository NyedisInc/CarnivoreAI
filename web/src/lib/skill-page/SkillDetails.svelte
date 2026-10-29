<!-- the whole file -->
<script lang="ts">
    import { latestVersion } from '../catalog/card';
    import { trustView } from '../catalog/trust';
    import type { InstalledItem, SkillAutopsy, SkillUsage } from '../catalog/types';
    import type { Tripwire } from '../skills-page/skill-state';
    import { fetchCatalogEntry, skillHost, type Fetcher } from '../skills-page/skills-api';
    import type { SkillGroupRow } from '../skills-page/skills-types';
    import type { Translate } from '../sessions/types';
    import StateShape from './StateShape.svelte';

    interface Props {
        name: string;
        group: SkillGroupRow;
        ledger: readonly InstalledItem[];
        tripwire: Tripwire | undefined;
        fetcher: Fetcher;
        t: Translate;
        everyTurn: number;
        inAll: number | null;
    }

    const { name, group, ledger, tripwire, fetcher, t, everyTurn, inAll }: Props = $props();

    let usage = $state<SkillUsage | null>(null);
    let autopsy = $state<SkillAutopsy | null>(null);
    let signer = $state<{ key: string | null; verdict: string | null } | null>(null);

    const host = $derived(skillHost(fetcher));
    const itemId = $derived(group.locations.find((l) => l.managed?.item_id)?.managed?.item_id ?? null);
    const plugin = $derived(group.locations.every((l) => l.scope === 'plugin') ? (group.locations[0]?.plugin ?? '') : null);
    const judged = $derived(tripwire ?? { state: 'not_judged' as const });

    $effect(() => {
        const skill = name;
        usage = null;
        autopsy = null;
        let cancelled = false;
        void host.skillUsage?.(skill).then((read) => { if (!cancelled) usage = read; }).catch(() => {});
        void host.skillAutopsy?.(skill).then((read) => { if (!cancelled) autopsy = read; }).catch(() => {});
        return () => { cancelled = true; };
    });

    $effect(() => {
        const id = itemId;
        signer = null;
        if (id === null) return;
        let cancelled = false;
        void fetchCatalogEntry(id, fetcher).then((entry) => {
            if (cancelled) return;
            const view = trustView(latestVersion(entry));
            signer = { key: view.signerKey, verdict: view.verdict };
        });
        return () => { cancelled = true; };
    });

    const measured = $derived(usage !== null && usage.state === 'measured' && typeof usage.fired_7d === 'number');

    function pct(part: number | null | undefined, whole: number | null | undefined): string {
        return typeof part === 'number' && typeof whole === 'number' && whole > 0 ? `${Math.round((part / whole) * 100)}%` : '-';
    }

    const dash = '-';
    const drifted = $derived(ledger.find((row) => row.drift?.state === 'drifted'));
    const driftKey = $derived(
        ledger.length === 0 ? 'skp.check.no_baseline'
        : drifted ? ''
        : ledger.some((row) => row.drift?.state === 'missing') ? 'skp.check.drift_missing'
        : ledger.every((row) => row.drift?.state === 'clean') ? 'skp.check.drift_clean'
        : 'skp.check.drift_unknown',
    );
    const changed = $derived(drifted?.drift?.changed_files ?? null);
</script>

<section class="skp-ctx skp-det" data-skill-details aria-label={t('skp.details.aria', { name })}>
    <div class="skp-ctx__head">
        <span class="skp-label">{t('skp.details.label')}</span>
        <span class="skp-ctx__tag skp-tw" data-tone={judged.state === 'flagged' ? 'flag' : null} data-tripwire={judged.state}>
            <StateShape name={judged.state === 'flagged' ? 'flagged' : 'off'} />{judged.state === 'flagged'
                ? t('skp.details.tripwire_flagged', { categories: judged.categories.map((c) => c.replace(/_/g, ' ')).join(', ') })
                : judged.state === 'clean'
                  ? t('skp.details.tripwire_clean')
                  : t('skp.details.tripwire_not_judged')}
        </span>
    </div>
    <div class="skp-ctx__body skp-det__body">
        <div class="skp-statgrp" data-group="fired">
            <span class="skp-label">{t('skp.details.fired')}</span>
            {#if measured && usage}
                <div class="skp-stats">
                    <div class="skp-stat"><b class="skp-stat__v">{usage.fired_7d}</b><span class="skp-stat__l">{t('skp.details.days', { count: 7 })}</span></div>
                    <div class="skp-stat"><b class="skp-stat__v">{usage.fired_30d ?? dash}</b><span class="skp-stat__l">{t('skp.details.days', { count: 30 })}</span></div>
                    <div class="skp-stat"><b class="skp-stat__v">{usage.fired_90d ?? dash}</b><span class="skp-stat__l">{t('skp.details.days', { count: 90 })}</span></div>
                </div>
            {:else}
                <span class="skp-dash">{dash} {t('skp.details.not_measured')}</span>
            {/if}
        </div>
        {#if measured}
            <div class="skp-statgrp" data-group="after">
                <span class="skp-label">{t('skp.details.after')}</span>
                {#if autopsy?.state === 'measured' && autopsy.spans_measured != null && autopsy.fires}
                    <div class="skp-stats">
                        <div class="skp-stat"><b class="skp-stat__v">{autopsy.spans_measured} of {autopsy.fires}</b><span class="skp-stat__l">{t('skp.details.runs_read')}</span></div>
                        <div class="skp-stat"><b class="skp-stat__v">{autopsy.tool_calls ?? dash}</b><span class="skp-stat__l">{t('skp.details.tool_calls')}</span></div>
                        <div class="skp-stat"><b class="skp-stat__v">{pct(autopsy.tool_errors, autopsy.tool_calls)}</b><span class="skp-stat__l">{t('skp.details.tool_errors')}</span></div>
                        <div class="skp-stat"><b class="skp-stat__v">{autopsy.interrupts ?? dash}</b><span class="skp-stat__l">{t('skp.details.interrupts')}</span></div>
                        <div class="skp-stat"><b class="skp-stat__v">{autopsy.corrections ?? dash} of {autopsy.corrections_measured ?? dash}</b><span class="skp-stat__l">{t('skp.details.corrections')}</span></div>
                    </div>
                {:else if autopsy?.state === 'not_measured'}
                    <span class="skp-dash">{dash} {t('skp.details.not_measured')}</span>
                {:else}
                    <span class="skp-dash">{dash} {t('skp.details.nothing_to_read')}</span>
                {/if}
            </div>
        {/if}
        <div class="skp-statgrp" data-group="size">
            <span class="skp-label">{t('skp.details.size')}</span>
            <div class="skp-stats">
                <div class="skp-stat" data-stat="every-turn"><b class="skp-stat__v">{everyTurn}</b><span class="skp-stat__l">{t('skp.details.every_turn')}</span></div>
                <div class="skp-stat" data-stat="in-all"><b class="skp-stat__v">{inAll === null ? dash : inAll}</b><span class="skp-stat__l">{t('skp.details.in_all')}</span></div>
                {#if ledger[0]?.version}
                    <div class="skp-stat"><b class="skp-stat__v">v{ledger[0].version}</b><span class="skp-stat__l">{ledger[0].update_available ? t('skp.details.latest', { version: ledger[0].latest_version ?? '' }) : t('skp.details.up_to_date')}</span></div>
                {/if}
            </div>
        </div>
        <div class="skp-statgrp" data-group="checks">
            <span class="skp-label">{t('skp.details.checks')}</span>
            <dl class="skp-kv">
                <dt>{t('skp.check.drift')}</dt>
                <dd data-check="drift">
                    {#if drifted}
                        <span class="skp-v"><StateShape name="caution" />{t('skp.check.drift_edited', { count: changed?.length ?? 0 })}</span>
                        {#if changed}<ul class="skp-warn">{#each changed as file (file)}<li>{file}</li>{/each}</ul>{/if}
                    {:else}{t(driftKey)}{/if}
                </dd>
                <dt>{t('skp.check.trust')}</dt>
                <dd data-check="trust">
                    {#if plugin !== null}{t('skp.check.trust_plugin', { plugin })}
                    {:else if itemId === null}{t('skp.check.trust_none')}
                    {:else if signer}{signer.key ? t('skp.check.trust_signed', { key: signer.key.slice(0, 12) }) : t('skp.check.trust_unsigned')}, {signer.verdict ? t('skp.check.trust_reviewed', { verdict: signer.verdict }) : t('skp.check.trust_unreviewed')}
                    {:else}{t('skp.check.trust_unknown')}{/if}
                </dd>
            </dl>
        </div>
    </div>
</section>
