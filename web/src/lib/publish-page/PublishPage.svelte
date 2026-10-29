<!-- and the three -->
<script lang="ts">
    import { tick, untrack } from 'svelte';
    import { layerShowing, ownsEscape } from '../sidebar-widgets/escape-guards';
    import { itemMenuState } from '../item-menu/open.svelte';
    import ChecksView from './ChecksView.svelte';
    import DossierHead from './DossierHead.svelte';
    import EmptyPage from './EmptyPage.svelte';
    import ImageView from './ImageView.svelte';
    import ItemPanels from './ItemPanels.svelte';
    import KindTabs from './KindTabs.svelte';
    import ListColumn from './ListColumn.svelte';
    import LocalCheckView from './LocalCheckView.svelte';
    import NextStep from './NextStep.svelte';
    import OpenedStep from './OpenedStep.svelte';
    import PaneStrip from './PaneStrip.svelte';
    import RulesView from './RulesView.svelte';
    import SideColumn from './SideColumn.svelte';
    import StageView from './StageView.svelte';
    import type { PublishableSkill } from '../catalog/publish';
    import { realKind } from './kinds';
    import { factsUnknown } from './item-model';
    import { buildRecords, kindList, stepKindOf, submissionGroups, tabStats } from './list-model';
    import { reduced } from './motion';
    import type { PageProps } from './props';
    import './page.css';
    import './list.css';

    const { store, actions, t }: PageProps = $props();

    const twinned = (f: PublishableSkill, folders: readonly PublishableSkill[]): boolean => folders.filter((g) => realKind(g) === realKind(f) && g.name === f.name).length > 1;

    const records = $derived(
        buildRecords({
            mine: store.mine,
            folders: store.folders,
            sendsOf: (location) => store.facts[location]?.sends.map((s) => s.submission_id) ?? [],
            checkOf: (location) => {
                const check = store.checkOf(location);
                return check ? { ok: check.ok, at: check.at } : null;
            },
        }),
    );
    const stats = $derived(tabStats(records, { submissions: !!store.failure.mine, kinds: !!store.failure.folders }));
    const rec = $derived(records.find((r) => r.location === store.sel) ?? null);
    const loading = $derived(store.folders === null && !store.failure.folders);
    const settled = $derived(
        !loading &&
            (!store.signedIn || store.mine !== null || !!store.failure.mine) &&
            (store.folders ?? []).every((f) => !twinned(f, store.folders ?? []) || !!store.facts[f.location] || !!store.failure.facts),
    );
    const mode = $derived(store.rulesOpen || !rec ? 'rules' : store.mid ? 'event' : 'item');

    const askedFacts = new Set<string>();
    $effect(() => {
        const folders = store.folders ?? [];
        for (const f of folders) {
            if (askedFacts.has(f.location) || untrack(() => store.facts[f.location])) continue;
            if (!twinned(f, folders)) continue;
            askedFacts.add(f.location);
            void store.loadFacts(f.location);
        }
    });

    let root = $state<HTMLElement | null>(null);
    let paneW = $state(0);
    let flash = $state(false);
    const narrow = $derived(paneW > 0 && paneW < 720);

    function scrollParent(el: HTMLElement): HTMLElement | null {
        for (let node = el.parentElement; node; node = node.parentElement) {
            const overflow = getComputedStyle(node).overflowY;
            if (overflow === 'auto' || overflow === 'scroll') return node;
        }
        return null;
    }

    function stickyBar(el: HTMLElement): number {
        const bar = el.closest('.oc-page')?.querySelector<HTMLElement>(':scope > .oc-titlebar');
        return bar && getComputedStyle(bar).position === 'sticky' ? bar.offsetHeight : 0;
    }

    function stackBottom(el: HTMLElement, scroller: HTMLElement | null): number {
        const strip = el.querySelector<HTMLElement>('.pp-strip');
        const tabs = el.querySelector<HTMLElement>('.d-tabs');
        const top = scroller ? scroller.getBoundingClientRect().top : 0;
        return top + stickyBar(el) + (strip?.offsetHeight ?? 0) + (tabs?.offsetHeight ?? 0) + 8;
    }

    function landBelowStack(el: HTMLElement, target: HTMLElement): void {
        const scroller = scrollParent(el);
        const gap = target.getBoundingClientRect().top - stackBottom(el, scroller);
        if (gap >= 0 && target.getBoundingClientRect().top < window.innerHeight) return;
        if (scroller) scroller.scrollTop += gap;
        else window.scrollBy(0, gap);
    }

    function toDocumentTop(el: HTMLElement): void {
        const scroller = scrollParent(el);
        if (scroller) scroller.scrollTop = 0;
        window.scrollTo(0, 0);
    }

    function fit(): void {
        if (!root) return;
        const strip = root.querySelector<HTMLElement>('.pp-strip');
        const tabs = root.querySelector<HTMLElement>('.d-tabs');
        const wrap = root.querySelector<HTMLElement>('.d-wrap');
        if (!strip || !tabs || !wrap) return;
        const scroller = scrollParent(root);
        const top = scroller ? scroller.getBoundingClientRect().top : 0;
        const room = scroller ? scroller.clientHeight : window.innerHeight;
        const bar = stickyBar(root);
        const stuck = bar + strip.offsetHeight + tabs.offsetHeight;
        const at = Math.max(wrap.getBoundingClientRect().top - top, stuck);
        root.style.setProperty('--pp-stick', `${bar}px`);
        root.style.setProperty('--d-top', `${strip.offsetHeight}px`);
        root.style.setProperty('--d-tabs-h', `${tabs.offsetHeight}px`);
        root.style.setProperty('--d-list-h', `${Math.max(240, room - at)}px`);
    }

    $effect(() => {
        if (!root) return;
        const el = root;
        const scroller = scrollParent(el);
        fit();
        const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(fit);
        observer?.observe(el);
        scroller?.addEventListener('scroll', fit, { passive: true });
        window.addEventListener('resize', fit);
        return () => {
            observer?.disconnect();
            scroller?.removeEventListener('scroll', fit);
            window.removeEventListener('resize', fit);
        };
    });

    $effect(() => {
        if (!store.scrollToTop || !root) return;
        const pane = root;
        untrack(() => {
            const doss = pane.querySelector<HTMLElement>('.d-doss');
            if (narrow) toDocumentTop(pane);
            else if (doss) landBelowStack(pane, doss);
            store.scrollToTop = false;
        });
    });

    $effect(() => {
        if (!store.restoreTop || !root) return;
        untrack(() => {
            if (narrow) toDocumentTop(root as HTMLElement);
            store.restoreTop = false;
        });
    });

    $effect(() => {
        if (paneW === 0 || !settled || store.sel || store.rulesOpen) return;
        const first = store.tab === 'submissions' ? submissionGroups(records, '', t)[0]?.rows[0] : kindList(records, store.tab, '')[0];
        if (first) store.showDefault(first.location, first.subId);
    });

    let openedRulesOnEmpty = false;
    $effect(() => {
        if (paneW === 0 || !settled || openedRulesOnEmpty || store.sel || store.rulesOpen || records.length > 0 || store.failure.folders || store.failure.mine) return;
        openedRulesOnEmpty = true;
        untrack(() => store.openRules());
    });

    function onKeydown(event: KeyboardEvent): void {
        if (event.key !== 'Escape' || event.defaultPrevented || itemMenuState.open) return;
        if (layerShowing(document) || ownsEscape(event.target)) return;
        if (store.rulesOpen) store.closeRules();
        else if (store.mid) store.closeEvent();
        else return;
        event.preventDefault();
    }

    async function refresh(): Promise<void> {
        await actions.refresh();
        if (reduced()) return;
        flash = true;
        setTimeout(() => { flash = false; }, 1200);
    }

    function back(): void {
        if (store.rulesOpen) store.closeRules();
        else store.goList();
        void tick().then(() => {
            if (store.view !== 'list' || !root) return;
            const rows = root.querySelectorAll<HTMLElement>('.d-list .d-row');
            (root.querySelector<HTMLElement>('.d-list .d-row[aria-current="true"]') ?? rows[0])?.focus({ preventScroll: true });
        });
    }
</script>

<svelte:window onkeydowncapture={onKeydown} />

<div class="pledger pp-root" data-oc-base data-pp="PublishPage" bind:this={root} bind:clientWidth={paneW}>
    <PaneStrip {store} {t} onRefresh={() => void refresh()} onBack={back} />
    <div class="d-body">
    <KindTabs {store} {t} {stats} />
    <div class="d-wrap" data-view={store.view} data-rules={mode === 'rules' ? '1' : ''}>
        <ListColumn {store} {actions} {t} {records} {stats} {flash} />
        <section class="d-doss" aria-label={t('publish.page.item.aria')} data-mode={mode}>
            <div class="d-headhost">{#if rec && mode === 'item'}<DossierHead {store} {actions} {t} />{/if}</div>
            {#if rec && !store.rulesOpen && !factsUnknown(store, rec)}
                <section class="d-slot" aria-label={t('publish.page.next.label')}><NextStep {store} {actions} {t} /></section>
            {/if}
            <div class="d-main">
                {#if store.rulesOpen}
                    <RulesView {store} {actions} {t} />
                {:else if loading}
                    
                {:else if !rec && (store.failure.folders || store.failure.mine)}
                    
                {:else if !rec}
                    <EmptyPage {store} {actions} {t} />
                {:else if store.mid}
                    <OpenedStep {store} {t} name={rec.name}>
                        {@const step = stepKindOf(store.mid.ev)}
                        {#if step === 'gates'}<ChecksView {store} {actions} {t} />
                        {:else if step === 'check'}<LocalCheckView {store} {actions} {t} />
                        {:else if step === 'image'}<ImageView {store} {actions} {t} />
                        {:else}<StageView {store} {actions} {t} />{/if}
                    </OpenedStep>
                {:else}
                    <ItemPanels {store} {actions} {t} />
                {/if}
            </div>
        </section>
        <aside class="d-side">{#if rec && !store.rulesOpen}<SideColumn {store} {actions} {t} />{/if}</aside>
    </div>
    </div>
</div>
