
<script lang="ts">
    import { t as reactiveT, type SessionTabSession, type Translate } from '../sdk';
    import RestorePoints from './RestorePoints.svelte';
    import { pointsApi, type Answer, type PointsApi, type SessionPoints, type StoreSummary } from './points-api';

    type View =
        | { readonly kind: 'loading' }
        | { readonly kind: 'absent' }
        | { readonly kind: 'error'; readonly message: string }
        | { readonly kind: 'ready'; readonly points: SessionPoints; readonly store: StoreSummary | null };

    interface Props {
        session: SessionTabSession;
        api?: PointsApi;
        t?: Translate;
    }
    const { session, api = pointsApi, t = reactiveT }: Props = $props();

    let view = $state<View>({ kind: 'loading' });
    let busy = $state<ReadonlySet<string>>(new Set());
    let notice = $state('');

    function refusal(answer: Exclude<Answer<unknown>, { kind: 'ok' }>): string {
        return answer.kind === 'absent' ? t('cplug.save.tab.absent') : answer.message;
    }

    async function load(): Promise<void> {
        const uuid = session.session_uuid;
        const [points, store] = await Promise.all([api.points(uuid), api.summary()]);
        if (uuid !== session.session_uuid) return;
        if (points.kind === 'ok') view = { kind: 'ready', points: points.value, store: store.kind === 'ok' ? store.value : null };
        else view = points.kind === 'absent' ? { kind: 'absent' } : { kind: 'error', message: points.message };
    }

    $effect(() => {
        void session.session_uuid;
        view = { kind: 'loading' };
        notice = '';
        void load();
    });

    function mark(id: string, on: boolean): void {
        const next = new Set(busy);
        if (on) next.add(id);
        else next.delete(id);
        busy = next;
    }

    async function onPin(id: string, pinned: boolean): Promise<void> {
        mark(id, true);
        notice = '';
        try {
            const answer = await api.pin(session.session_uuid, id, pinned);
            if (answer.kind === 'ok') {
                notice = t(pinned ? 'cplug.save.tab.pinned_notice' : 'cplug.save.tab.unpinned_notice');
                await load();
            } else notice = refusal(answer);
        } finally {
            mark(id, false);
        }
    }

    async function onRestore(id: string): Promise<void> {
        mark(id, true);
        notice = '';
        try {
            const answer = await api.restore(session.session_uuid, id);
            if (answer.kind !== 'ok') {
                notice = refusal(answer);
                return;
            }
            const { sessionStatus, sessionCode, detail } = answer.value;
            if (sessionStatus === 'started') notice = t('cplug.save.tab.restored.started');
            else if (sessionStatus === 'refused') {
                notice = sessionCode === 'grant_needed' && detail ? detail : t('cplug.save.tab.restored.refused', { detail });
            } else notice = detail || t('cplug.save.tab.restored.written');
            await load();
        } finally {
            mark(id, false);
        }
    }
</script>

<div id="restore-points" class="rpt-tab" data-section="restore-points">
    <p class="rpt-hintline">{t('cplug.save.tab.hint')}</p>
    <div class="rpt-stack">
        <div class="rpt-ways">
            <div>
                <span class="ph-sub rpt-ways__ok">{t('cplug.save.tab.ways.resume_title')}</span>
                <p>{t('cplug.save.tab.ways.resume_body')}</p>
            </div>
            <div>
                <span class="ph-sub rpt-ways__rp">{t('cplug.save.tab.ways.point_title')}</span>
                <p>
                    {t('cplug.save.tab.ways.point_body')}
                    <b>{t('cplug.save.tab.resume_exact')}</b>
                    {t('cplug.save.tab.ways.point_exact')}
                </p>
            </div>
        </div>
        {#if notice}<p class="ph-hint" role="status" data-rpt-notice>{notice}</p>{/if}
        {#if view.kind === 'loading'}
            <p class="ph-hint" role="status">{t('cplug.save.tab.loading')}</p>
        {:else if view.kind === 'absent'}
            <p class="ph-hint" data-tm-absent>{t('cplug.save.tab.absent')}</p>
        {:else if view.kind === 'error'}
            <p class="ph-hint" role="alert">{view.message}</p>
        {:else if view.points.points.length === 0}
            <p class="ph-empty" data-no-points>{t('cplug.save.tab.none')}</p>
        {:else}
            <RestorePoints
                points={view.points.points}
                keep={view.store?.keep ?? null}
                usedBytes={view.store?.usedBytes ?? 0}
                capBytes={view.store?.capBytes ?? 0}
                {busy}
                {t}
                {onPin}
                {onRestore}
            />
        {/if}
    </div>
</div>

<style>
    @layer components {
        .rpt-hintline {
            margin: 0;
            font-size: var(--oc-fs-label, 11px);
            color: var(--oc-text-dim);
        }

        .rpt-stack {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-3);
            margin: 0;
        }

        .rpt-ways {
            display: grid;
            grid-template-columns: 1fr 1fr;
            border: 1px solid var(--oc-line-rule);
            border-radius: var(--oc-radius-sm);
        }

        .rpt-ways > div {
            display: flex;
            flex-direction: column;
            gap: 4px;
            padding: var(--oc-space-2) var(--oc-space-3);
        }

        .rpt-ways > div + div {
            box-shadow: inset 1px 0 0 var(--oc-line-rule);
        }

        .rpt-ways p {
            margin: 0;
            line-height: 1.5;
            color: var(--oc-text-secondary);
        }

        .rpt-ways b {
            font-weight: normal;
            color: var(--oc-text-primary);
        }

        .rpt-ways__ok {
            color: var(--oc-green);
        }

        .rpt-ways__rp {
            color: var(--oc-cyan);
        }

        @container ph (max-width: 767px) {
            .rpt-ways {
                grid-template-columns: 1fr;
            }

            .rpt-ways > div + div {
                box-shadow: inset 0 1px 0 var(--oc-line-rule);
            }
        }
    }
</style>
