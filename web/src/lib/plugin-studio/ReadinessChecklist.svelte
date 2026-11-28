<script lang="ts">
    import { Button, State, Tag } from '../base';
    import { t as appT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import type { ReadinessReport, ReadinessStatus } from './types';
    import './plugin-studio.css';

    interface Props {
        readiness: ReadinessReport | null;
        busy?: boolean;
        onRecheck: (runTests: boolean) => Promise<unknown>;
        t?: Translate;
    }

    const { readiness, busy = false, onRecheck, t = appT }: Props = $props();

    function statusTone(status: ReadinessStatus): 'ok' | 'danger' | 'warn' | 'neutral' {
        switch (status) {
            case 'pass':
                return 'ok';
            case 'fail':
                return 'danger';
            case 'advisory':
                return 'warn';
            default:
                return 'neutral';
        }
    }
</script>

<div class="ps-right-body" data-studio-readiness>
    <div class="ps-preview-controls">
        <div class="ps-pane__controls">
            <h3 class="ps-pane__heading">{t('plugin_studio.readiness.heading')}</h3>
            {#if readiness}
                <Tag tone={readiness.ready ? 'ok' : 'danger'}>
                    {readiness.ready
                        ? t('plugin_studio.readiness.ready_badge')
                        : t('plugin_studio.readiness.not_ready_badge')}
                </Tag>
                <Tag tone="neutral">
                    {t('plugin_studio.readiness.summary', {
                        pass: readiness.summary.pass,
                        fail: readiness.summary.fail,
                        advisory: readiness.summary.advisory,
                    })}
                </Tag>
            {/if}
        </div>

        <Button
            variant="secondary"
            disabled={busy}
            data-studio-readiness-recheck
            onclick={() => void onRecheck(true)}
        >
            {busy ? t('plugin_studio.readiness.checking') : t('plugin_studio.readiness.recheck')}
        </Button>
    </div>

    {#if !readiness}
        <State kind="empty" title={t('plugin_studio.readiness.empty')}>
            {#snippet actions()}
                <Button variant="secondary" disabled={busy} onclick={() => void onRecheck(true)}>
                    {t('plugin_studio.readiness.recheck')}
                </Button>
            {/snippet}
        </State>
    {:else}
        <div class="ps-check-list" data-studio-readiness-items>
            {#each readiness.items as item (item.id)}
                <div class="ps-check-row" data-readiness-item={item.id} data-readiness-status={item.status}>
                    <div class="ps-check-row__top">
                        <span class="ps-check-row__label">{item.label}</span>
                        <Tag tone={statusTone(item.status)}>
                            {t(`plugin_studio.readiness.status.${item.status}`)}
                        </Tag>
                    </div>
                    {#if item.detail}
                        <p class="ps-check-row__detail">{item.detail}</p>
                    {/if}
                    {#if item.findings?.length}
                        <ul class="ps-findings">
                            {#each item.findings as finding, idx (`${item.id}-${idx}`)}
                                <li>{finding.message ?? finding.detail ?? JSON.stringify(finding)}</li>
                            {/each}
                        </ul>
                    {/if}
                </div>
            {/each}
        </div>
    {/if}
</div>
