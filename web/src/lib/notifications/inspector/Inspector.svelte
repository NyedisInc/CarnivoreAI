
<script lang="ts">
    import { onMount } from 'svelte';
    import { t as reactiveT } from '../../i18n/index.svelte';
    import type { Translate } from '../../sessions/types';
    import { Button, Segmented, Select, Switch } from '../../base';
    import Previews from './Previews.svelte';
    import '../../settings-page/panel-kit/panel-kit.css';
    import '../../notify-card/notify-card.css';
    import './inspector.css';
    import { isRateLimited } from '../destinations/api';
    import { DESKTOP, SCREEN } from '../matrix/api';
    import { groupRows } from '../matrix/logic';
    import { attach as attachMatrix, matrix, setTick } from '../matrix/store.svelte';
    import type { Fetcher } from './api';
    import { fetchComputerName, sendTypedTest } from './api';
    import { cellValue, defaultKind, isOn, kindFor, lightOf, playable, sampleFor, SHAPES, writable } from './logic';
    import { SAMPLES } from './samples';
    import { attach, inspector, setStyle } from './store.svelte';

    interface Props {
        t?: Translate;
        fetcher?: Fetcher;
    }
    const { t = reactiveT, fetcher }: Props = $props();

    onMount(() => {
        const stops = [attachMatrix(fetcher), attach(fetcher)];
        fetchComputerName(fetcher).then((name) => (computerName = name), () => undefined);
        return () => stops.forEach((stop) => stop());
    });

    const groups = $derived(groupRows(matrix.families, matrix.types));
    const iphones = $derived(Object.keys(matrix.settings.ticks).filter((id) => id.startsWith('apns:')).map((id) => ({ id, name: matrix.settings.destinations.find((d) => d.id === id)?.name ?? '' })));
    const iphoneIds = $derived(iphones.map((d) => d.id));

    let picked = $state('');
    let computerName = $state('');
    let shapes = $state<Record<string, string>>({});
    const typeId = $derived(picked && matrix.types.some((row) => row.id === picked) ? picked : (groups[0]?.rows[0]?.id ?? ''));
    const row = $derived(matrix.types.find((r) => r.id === typeId));
    const style = $derived(inspector.doc.styles[typeId]);
    const kind = $derived(kindFor(typeId, shapes[typeId]));
    const sample = $derived(row ? sampleFor(SAMPLES, kind, t(row.label_key)) : null);
    const on = $derived(isOn(matrix.settings, typeId, iphoneIds));
    const iphoneOn = $derived(iphoneIds.some((id) => cellValue(matrix.settings, id, typeId)));
    const computerOn = $derived(cellValue(matrix.settings, DESKTOP, typeId));

    const URGENCY_KEY: Record<string, string> = { passive: 'passive', active: 'active', 'time-sensitive': 'time_sensitive' };
    const urgencyLabel = (u: string): string => t(`notify.inspector.level.${URGENCY_KEY[u] ?? 'active'}`);
    const soundLabel = (s: string): string => t(`notify.inspector.sound.${s}`);
    const word = (k: string): string => t(`notify.card.word.${k}`);

    const devices = $derived([
        { column: DESKTOP, label: computerName || t('notify.inspector.device.computer') },
        { column: SCREEN, label: t('settings.notify.matrix.col.screen') },
        ...iphones.map((d) => ({ column: d.id, label: d.name || t('notify.inspector.device.iphone') })),
    ]);

    async function setOn(next: boolean): Promise<void> {
        for (const d of devices) {
            if (writable(matrix.settings, d.column, typeId) && cellValue(matrix.settings, d.column, typeId) !== next) await setTick(d.column, typeId, next);
        }
    }

    let player: HTMLAudioElement | null = null;
    function play(sound: string): void {
        if (!playable(sound)) return;
        try {
            player?.pause();
            player = new Audio(`/static/sounds/carnivore-${sound}.wav`);
            void player.play().catch(() => undefined);
        } catch {
            player = null;
        }
    }

    let test = $state<'' | 'sending' | 'ok' | 'failed' | 'wait'>('');
    async function sendTest(): Promise<void> {
        const dest = iphoneIds[0];
        if (!dest) return;
        test = 'sending';
        try {
            test = (await sendTypedTest(dest, typeId, fetcher)).ok ? 'ok' : 'failed';
        } catch (error) {
            test = isRateLimited(error) ? 'wait' : 'failed';
        }
    }
    $effect(() => { void typeId; test = ''; });
</script>

<div class="ins" data-ins="inspector">
    {#if inspector.problem || matrix.problem}<p class="tm__problem" role="alert" data-ins="problem">{inspector.problem || matrix.problem}</p>{/if}
    {#if !matrix.loaded || !inspector.loaded}
        <p class="tm__sub" data-ins="loading">{t('settings.notify.matrix.loading')}</p>
    {:else}
        <div class="ins__frame">
            <div class="ins__list" data-ins="list">
                {#each groups as group (group.family.id)}
                    <h4>{t(group.family.label_key)}</h4>
                    {#each group.rows as r (r.id)}
                        <Button variant="row" aria-pressed={r.id === typeId} data-type={r.id} onclick={() => (picked = r.id)}>
                            <span class="nc-led" data-light={lightOf(r.id)}></span>
                            <span class="ins__name">{t(r.label_key)}</span>
                            <span class="ins__st" data-st={r.id}>{isOn(matrix.settings, r.id, iphoneIds) ? t('notify.inspector.col.on') : t('notify.settings.off')}</span>
                        </Button>
                    {/each}
                {/each}
            </div>
            {#if row && style}
                <div class="ins__pane" data-ins="pane">
                    <div class="ins__title"><h3>{t(row.label_key)}</h3><span>{row.id}</span></div>
                    <div class="ins__prev" data-off={on ? undefined : ''} data-ins="preview">
                        {#if SHAPES[typeId]}
                            <Segmented label={t('notify.inspector.shape')} size="sm" value={kind} options={SHAPES[typeId].map((k) => ({ value: k, label: word(k) }))}
                                onchange={(v) => (shapes = { ...shapes, [typeId]: v })} data-ins="shapes" />
                        {/if}
                        <div class="ins__walls"><Previews {sample} {kind} iphone={iphoneOn} computer={computerOn} level={urgencyLabel(style.urgency)} /></div>
                        {#if !iphoneOn && !computerOn}<p class="tm__sub" data-ins="no-device">{t('notify.inspector.no_device')}</p>{/if}
                    </div>
                    <div class="ins__ctl">
                        <span class="ins__lab">{t('notify.inspector.col.on')}</span>
                        <span class="ins__row"><Switch bare label="" checked={on} aria-label={t(row.label_key)} data-ins="on" onchange={(next) => void setOn(next)} /><span class="ins__hint">{t('notify.settings.on.hint')}</span></span>
                        <span class="ins__lab">{t('notify.inspector.col.sound')}</span>
                        <span class="ins__row">
                            <Select size="sm" aria-label={t('notify.inspector.col.sound')} value={style.sound} data-ins="sound"
                                options={inspector.doc.sounds.map((s) => ({ value: s, label: soundLabel(s) }))}
                                onchange={(e) => void setStyle(typeId, { sound: (e.currentTarget as HTMLSelectElement).value })} />
                            <Button size="sm" data-ins="play" disabled={!playable(style.sound)} onclick={() => play(style.sound)}>{t('notify.inspector.play')}</Button>
                        </span>
                        <span class="ins__lab">{t('notify.inspector.col.urgency')}</span>
                        <span class="ins__row">
                            <Select size="sm" aria-label={t('notify.inspector.col.urgency')} value={style.urgency} data-ins="urgency"
                                options={inspector.doc.urgencies.map((u) => ({ value: u, label: urgencyLabel(u) }))}
                                onchange={(e) => void setStyle(typeId, { urgency: (e.currentTarget as HTMLSelectElement).value })} />
                            <span class="ins__hint">{t(`notify.settings.urgency.${URGENCY_KEY[style.urgency] ?? 'active'}`)}</span>
                        </span>
                        <span class="ins__lab">{t('notify.inspector.col.devices')}</span>
                        <span class="ins__dev" data-ins="devices">
                            {#each devices as d (d.column)}
                                <Button size="sm" data-dev={d.column} aria-pressed={cellValue(matrix.settings, d.column, typeId)} disabled={!writable(matrix.settings, d.column, typeId)}
                                    onclick={() => void setTick(d.column, typeId, !cellValue(matrix.settings, d.column, typeId))}>{d.label}</Button>
                            {/each}
                        </span>
                        <span class="ins__lab">{t('notify.inspector.corner')}</span>
                        <span class="ins__row"><Switch bare label="" checked={style.corner} aria-label={t('notify.inspector.corner')} data-ins="corner" onchange={(next) => void setStyle(typeId, { corner: next })} /><span class="ins__hint">{t('notify.settings.corner.hint')}</span></span>
                        {#if iphoneIds.length > 0}
                            <span class="ins__lab">{t('settings.notify.dest.test.button')}</span>
                            <span class="ins__row">
                                <Button size="sm" data-ins="test" disabled={test === 'sending'} onclick={() => void sendTest()}>{t('notify.settings.test')}</Button>
                                {#if test}<span class="ins__hint" role="status" data-ins="test-state">{t(`settings.notify.dest.test.${test === 'ok' ? 'ok' : test === 'sending' ? 'sending' : test === 'wait' ? 'wait' : 'failed'}`)}</span>{/if}
                            </span>
                        {/if}
                    </div>
                </div>
            {/if}
        </div>
    {/if}
</div>
