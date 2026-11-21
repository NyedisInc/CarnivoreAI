
<script lang="ts">
    import { onMount } from 'svelte';
    import { t as reactiveT } from '../../i18n/index.svelte';
    import type { Translate } from '../../sessions/types';
    import { Segmented } from '../../base';
    import Check from '../../../opscenter/ui/Check.svelte';
    import '../../settings-page/panel-kit/panel-kit.css';
    import '../../notify-card/notify-card.css';
    import './inspector.css';
    import { groupRows } from '../matrix/logic';
    import { attach as attachMatrix, matrix } from '../matrix/store.svelte';
    import type { Fetcher, Target } from './api';
    import ComputerBlocks from './ComputerBlocks.svelte';
    import GroupRail from './GroupRail.svelte';
    import Housekeeping from './Housekeeping.svelte';
    import { anyTarget, cornerAllowed, groupState, kindOf, known, sampleFor, targetsOn } from './logic';
    import Previews from './Previews.svelte';
    import { SAMPLES } from './samples';
    import Sections from './Sections.svelte';
    import { attach, inspector, setMaster, setRoute, setStyles } from './store.svelte';

    interface Props {
        t?: Translate;
        fetcher?: Fetcher;
    }
    const { t = reactiveT, fetcher }: Props = $props();

    const VIEW_KEY = 'carnivore.notify.view';
    type View = 'basic' | 'advanced';
    function savedView(): View {
        try { return localStorage.getItem(VIEW_KEY) === 'advanced' ? 'advanced' : 'basic'; } catch { return 'basic'; }
    }
    let view = $state<View>(savedView());
    let selection = $state<{ family: string; type: string | null }>({ family: '', type: null });
    let open = $state<Record<string, boolean>>({});
    let showAs = $state<'app' | 'desk' | 'phone'>('phone');

    function setView(next: View): void {
        view = next;
        try { localStorage.setItem(VIEW_KEY, next); } catch {  }
        open = next === 'advanced' ? Object.fromEntries(groups.map((g) => [g.family.id, true])) : {};
    }

    onMount(() => {
        const stops = [attachMatrix(fetcher), attach(fetcher)];
        if (view === 'advanced') open = Object.fromEntries(groups.map((g) => [g.family.id, true]));
        return () => stops.forEach((stop) => stop());
    });

    const routes = $derived(inspector.routes);
    const groups = $derived(groupRows(matrix.families, matrix.types).map((g) => ({ ...g, rows: g.rows.filter((r) => routes?.types[r.id] !== undefined) })).filter((g) => g.rows.length > 0));
    const family = $derived(groups.find((g) => g.family.id === selection.family) ?? groups[0]);
    const row = $derived(selection.type ? matrix.types.find((r) => r.id === selection.type) : undefined);
    const ids = $derived(row ? [row.id] : (family?.rows.map((r) => r.id) ?? []));
    const live = $derived(known(routes, ids));
    const on = $derived(groupState(routes, ids));
    const style = $derived(inspector.doc.styles[ids[0] ?? '']);
    const name = $derived(row ? t(row.label_key) : family ? t(family.family.label_key) : '');
    const sample = $derived(family ? sampleFor(SAMPLES, kindOf(row?.id ?? null, family.family.id), name) : null);
    const when = $derived(row ? t(row.description_key) : family ? t(`notify.routing.group.when.${family.family.id}`) : '');
    const level = $derived(style ? t(`notify.inspector.level.${style.urgency === 'time-sensitive' ? 'time_sensitive' : style.urgency}`) : '');
    const cornerOn = $derived(!!style && cornerAllowed(style.urgency) && anyTarget(routes, ids, 'corner'));
    const SHOW_TARGET = { app: 'app', desk: 'desk', phone: 'phone' } as const;
    const ticked = $derived(anyTarget(routes, ids, SHOW_TARGET[showAs]));
    const WORD: Record<string, string> = { app: 'notify.routing.show.app', desk: 'notify.routing.show.desk', phone: 'notify.routing.show.phone' };
    const where = $derived((routes?.computers ?? []).map((c) => ({ c, tg: targetsOn(routes, ids, c.install_id) })).filter((x) => x.tg.length > 0)
        .map((x) => `${x.c.label}: ${x.tg.map((tg) => t(WORD[tg] ?? '')).join(', ')}`).join('; '));
    const count = $derived(view === 'advanced' ? t('notify.routing.rail.types', { count: groups.reduce((n, g) => n + g.rows.length, 0) }) : t('notify.routing.rail.groups', { count: groups.length }));
    const paneCount = $derived(row && family ? t('notify.routing.pane.type', { group: t(family.family.label_key) }) : family ? t('notify.routing.pane.group', { count: family.rows.length, blurb: t(`notify.routing.group.blurb.${family.family.id}`) }) : '');

    const onGroup = (familyId: string, next: boolean): void => void setMaster(groups.find((g) => g.family.id === familyId)?.rows.map((r) => r.id) ?? [], next);
    const onRoute = (computer: string, target: Target, next: boolean): void => void setRoute(live, computer, target, next);
</script>

<div class="ins" data-ins="inspector">
    {#if inspector.problem || matrix.problem}<p class="tm__problem" role="alert" data-ins="problem">{inspector.problem || matrix.problem}</p>{/if}
    {#if !matrix.loaded || !inspector.loaded || !routes}
        <p class="tm__sub" data-ins="loading">{t('notify.routing.loading')}</p>
    {:else}
        <div class="ins-viewswitch">
            <Segmented label={t('notify.routing.view')} size="sm" value={view} data-ins="view" onchange={(v) => setView(v as View)}
                options={[{ value: 'basic', label: t('notify.routing.view.basic') }, { value: 'advanced', label: t('notify.routing.view.advanced') }]} />
        </div>
        <div class="ins-main">
            <div class="ins-left">
                <GroupRail {groups} {routes} {selection} {open} {count} {t}
                    onSelect={(f, ty) => (selection = { family: f, type: ty })}
                    onToggleOpen={(f) => (open = { ...open, [f]: !open[f] })}
                    {onGroup} onType={(id, next) => void setMaster([id], next)} />
                <Housekeeping advanced={view === 'advanced'} onAdvanced={() => setView('advanced')} {t} />
            </div>
            {#if family && live.length > 0 && style}
                <section class="ins-panel ins-pane" data-ins="pane">
                    <div class="ins-bar ins-bar--hot"><h2>{name}</h2><span class="ins-count">{paneCount}</span></div>
                    <div class="ins-two">
                        <div class="ins-ctl">
                            <div class="ins-master" data-v={on} data-ins="master">
                                <Check role="switch" label="" ariaLabel={name} checked={on === 'all'} mixed={on === 'some'} data-ins="master-switch" onToggle={() => void setMaster(live, on !== 'all')} />
                                <span class="ins-master__w">{t(`notify.routing.master.${on === 'all' ? 'on' : on === 'none' ? 'off' : 'some'}`)}</span>
                                <span class="ins-dim">{name}</span>
                            </div>
                            <Sections disabled={on === 'none'} sound={style.sound} urgency={style.urgency} sounds={inspector.doc.sounds} urgencies={inspector.doc.urgencies}
                                testType={live[0] ?? ''} onStyle={(patch) => void setStyles(live, patch)} {fetcher} {t}>
                                {#snippet children()}<ComputerBlocks {routes} ids={live} urgency={style.urgency} {onRoute} {t} />{/snippet}
                            </Sections>
                        </div>
                        <div class="ins-side">
                            <Previews {name} {when} {sample} bind:showAs on={on !== 'none'} {ticked} {where} corner={cornerOn} {level} {t} />
                        </div>
                    </div>
                </section>
            {/if}
        </div>
    {/if}
</div>
