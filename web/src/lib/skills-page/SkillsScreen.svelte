
<script lang="ts">
    import { captureOpener, restoreOpenerFocus } from '../dialog-frame/opener-focus';
    import { onDestroy } from 'svelte';
    import ManagerFrame from '../manager-frame/ManagerFrame.svelte';
    import { createManagerController } from '../manager-frame/manager-controller.svelte';
    import { MANAGER_KEYS } from '../manager-frame/manager-model';
    import type { ManagerAdapter, ManagerFilter, ManagerItem } from '../manager-frame/types';
    import { authFetch } from '../../opscenter/api/auth.svelte';
    import { subscribe } from '../../opscenter/api/events.svelte';
    import { resourcePush } from '../resource-push/boot';
    import { openCatalog } from '../../opscenter/api/host';
    import { t as appT } from '../i18n/index.svelte';
    import type { Snippet } from 'svelte';
    import type { Translate } from '../sessions/types';
    import FacetSelect from '../../opscenter/ui/FacetSelect.svelte';
    import CensusTab from './CensusTab.svelte';
    import SkillDetailPane from './SkillDetailPane.svelte';
    import SkillPage from '../skill-page/SkillPage.svelte';
    import { createSkillActions } from './skill-actions.svelte';
    import { fetchCensus, refusalOf, type Fetcher } from './skills-api';
    import { markerWords, markersOf } from './skill-state';
    import { chipsOf } from './skill-chips';
    import { skillRatings } from './skill-ratings.svelte';
    import { browserCatalogHost, type CatalogHost } from '../catalog/catalog';
    import { createSkillsAdapter } from './skills-adapter';
    import RequiredSkills from '../skills-hub/RequiredSkills.svelte';
    import { isBundledSkill } from '../catalog/app-own';
    import { isFirstParty, offEntries, type RequiredEntry } from '../skills-hub/required-skills';
    import { skillFavorites } from '../themes-page/favorites.svelte';
    import {
        GLOBAL_CONTEXT_ID,
        contextChoices,
        type ContextChoice,
        type ProjectRef,
        type SkillItem,
    } from './skills-model';
    import type { Census, Inventory, OverrideResult } from './skills-types';

    interface Props {
        fetcher?: Fetcher;
        catalogHost?: Pick<CatalogHost, 'itemRatings'>;
        t?: Translate;
        embedded?: boolean;
        storeOnly?: boolean;
        openCatalogPage?: () => void;
        tab?: 'skills' | 'census';
        focusId?: string | null;
        onSelect?: (id: string) => void;
        onChanged?: () => void;
        highlights?: Snippet;
        skillPage?: boolean;
        onBack?: () => void;
    }

    const {
        fetcher = authFetch,
        catalogHost,
        t = appT,
        embedded = false,
        storeOnly = false,
        openCatalogPage = () => void openCatalog(),
        tab: hostTab,
        focusId = null,
        onSelect: onPick,
        onChanged,
        highlights,
        skillPage = false,
        onBack,
    }: Props = $props();

    const ECHO_MS = 1500;

    // svelte-ignore state_referenced_locally
    let open = $state(embedded);
    let opener: HTMLElement | null = null;
    let query = $state('');
    let chips = $state<string[]>([]);
    let selectedId = $state<string | null>(null);
    let lastFocusId: string | null = null;
    $effect(() => {
        if (embedded && focusId) selectedId = focusId;
        else if (embedded && lastFocusId) selectedId = null;
        lastFocusId = focusId;
    });
    let contextId = $state(GLOBAL_CONTEXT_ID);
    // svelte-ignore state_referenced_locally
    let view = $state<'skills' | 'census'>(hostTab ?? 'skills');
    const tab = $derived(hostTab ?? view);
    let census = $state<Census | null>(null);
    let censusError = $state<string | null>(null);
    let inventory = $state<Inventory | null>(null);
    let projects = $state<ProjectRef[]>([]);
    let projectsFailed = $state(false);
    let requiredEntries = $state<RequiredEntry[]>([]);
    let installing = $state<{ id: string; error: string | null } | null>(null);
    let hints = $state<{ restart: boolean; claude: string | null }>({ restart: false, claude: null });
    let globalGroupId: string | null = null;
    let lastOwnWrite = 0;
    let stopEvents: (() => void) | null = null;

    const choices = $derived(
        contextChoices(inventory?.profile_groups ?? [], globalGroupId ?? inventory?.context.group_id ?? null, projects, t),
    );
    const context: ContextChoice = $derived(choices.find((c) => c.id === contextId) ?? choices[0]!);
    const profileChoices = $derived(choices.filter((c) => c.kind === 'profile'));
    const projectChoices = $derived(choices.filter((c) => c.kind === 'project'));

    // svelte-ignore state_referenced_locally
    const adapter: ManagerAdapter = createSkillsAdapter(
        t,
        () => context,
        {
            onInventory: (next) => {
                if (contextId === GLOBAL_CONTEXT_ID) globalGroupId = next.context.group_id;
                inventory = next;
                void actions.loadHealth(next);
            },
            onWrote: (result: OverrideResult) => noteWrite(result),
            onWriting: () => (lastOwnWrite = Date.now()),
        },
        fetcher,
    );
    // svelte-ignore state_referenced_locally
    const ctl = createManagerController(adapter, t('skills.page.error'));

    let seenSig: string | null = null;
    $effect(() => {
        const sig = ctl.items.map((row) => `${row.id}:${row.enabled ?? ''}`).join('|');
        const before = seenSig;
        seenSig = sig;
        if (before !== null && before !== sig) onChanged?.();
    });
    // svelte-ignore state_referenced_locally
    const actions = createSkillActions({
        fetcher,
        t,
        context: () => context,
        inventory: () => inventory,
        reload: () => ctl.load(),
        onWriting: () => (lastOwnWrite = Date.now()),
        onWrote: (result) => noteWrite(result),
    });

    // svelte-ignore state_referenced_locally
    if (embedded) void start();

    function noteWrite(result: OverrideResult): void {
        lastOwnWrite = Date.now();
        if (!result.wrote) return;
        hints = {
            restart: hints.restart || result.restart_required,
            claude: result.harness === 'claude' ? (result.reload_hint ?? t('skills.page.hint.claude')) : hints.claude,
        };
    }

    /* nothing at all */
    function firesMetric(name: string): string | null {
        const census = actions.health.census;
        if (!census) return null;
        const fires = census.skills.find((row) => row.name === name)?.fires;
        return fires ? t('skills.card.fires', { count: fires.d30 }) : t('skills.census.not_measured');
    }

    function storeIdOf(item: ManagerItem): string | null {
        const group = (item as SkillItem).group;
        return group?.locations.map((l) => l.managed?.item_id).find((id) => Boolean(id)) ?? null;
    }

    function cornerOf(storeId: string | null): string[] {
        if (!storeId) return [t('skills.card.private')];
        const rating = skillRatings.byId[storeId];
        if (!rating) return [t('skills.card.unrated')];
        if (rating.shape === 'none') {
            return rating.comments > 0 ? [t('skills.card.unrated'), t('skills.card.comments', { count: rating.comments })] : [t('skills.card.unrated')];
        }
        return [
            t('skills.card.rating', { stars: (rating.average ?? 0).toFixed(1), count: rating.count }),
            t('skills.card.comments', { count: rating.comments }),
        ];
    }

    const markedItems = $derived(
        ctl.items.filter((item) => !storeOnly || !isBundledSkill(((item as SkillItem).group?.locations ?? []).map((l) => l.managed?.item_id))).map((item) => {
            const group = (item as SkillItem).group;
            const markers = group ? markersOf(group, actions.health) : [];
            const extra = markerWords(markers, t);
            const metric = firesMetric(item.id);
            const firstParty = group?.locations.some((l) => isFirstParty(l.managed?.item_id)) ?? false;
            const first = firstParty ? [t('skills.badge.carnivore')] : [];
            const marks = [...first, ...(item.marks ?? []), ...extra];
            const chips = group ? chipsOf(item as SkillItem, markers, firstParty, t) : [];
            return {
                ...item,
                ...(marks.length > 0 ? { marks } : {}),
                ...(metric ? { metric } : {}),
                chips,
                corner: cornerOf(storeIdOf(item)),
                starred: skillFavorites.has(item.id),
            };
        }),
    );

    const offItems = $derived(
        (storeOnly ? [] : offEntries(requiredEntries))
            .map((entry) => ({ entry, name: entry.item_id.split('/')[1] ?? entry.item_id }))
            .filter(({ name }) => !ctl.items.some((item) => item.id === name))
            .map(({ entry, name }) => ({
                id: name,
                name,
                brief: t('skills.required.brief', { name }),
                marks: [t('skills.badge.carnivore')],
                icon: 'skill',
                status: { label: t('skills.status.off'), tone: 'off' as const },
                tags: [] as string[],
                chips: [{ id: 'carnivore', label: t('skills.chip.carnivore'), icon: 'bolt' }],
                corner: cornerOf(entry.item_id),
                starred: skillFavorites.has(name),
                enabled: false,
                harnesses: [] as string[],
                off: true,
                shadowed: false,
                heavy: false,
                uninstalled: true,
            })),
    );
    $effect(() => {
        const ids = [...ctl.items.map(storeIdOf), ...offEntries(requiredEntries).map((e) => e.item_id)].filter((id): id is string => Boolean(id));
        if (ids.length > 0) skillRatings.want(ids, catalogHost ?? browserCatalogHost());
    });

    const offIds = $derived(new Set(offItems.map((item) => item.id)));

    async function loadRequired(): Promise<void> {
        try {
            requiredEntries = (await fetcher<{ items: RequiredEntry[] }>('/catalog/required-skills')).items;
        } catch {
            requiredEntries = [];
        }
    }

    async function toggleCard(id: string, next: boolean): Promise<void> {
        if (!offIds.has(id)) return void ctl.toggle(id, next);
        if (!next || installing) return;
        installing = { id, error: null };
        try {
            await fetcher(`/catalog/required-skills/carnivore/${id}/install`, { method: 'POST' });
            await Promise.all([loadRequired(), ctl.load()]);
            installing = null;
        } catch (error) {
            installing = { id, error: refusalOf(error, t('skills.required.failed')) };
        }
    }

    async function readProjects(): Promise<void> {
        try {
            projects = await fetcher<ProjectRef[]>('/projects');
            projectsFailed = false;
        } catch {
            projects = [];
            projectsFailed = true;
        }
    }

    async function start(): Promise<void> {
        stopEvents?.();
        const stopChanged = subscribe('skills.changed', () => {
            if (Date.now() - lastOwnWrite < ECHO_MS) return;
            void ctl.load();
        });
        const stopTopic = resourcePush().onChange((topics) => {
            if (topics.includes('local_skills')) void ctl.load();
        });
        skillFavorites.start();
        stopEvents = () => {
            stopChanged();
            stopTopic();
        };
        await Promise.all([readProjects(), ctl.load(), loadRequired()]);
        if (tab === 'census') void loadCensus();
    }

    export function show(): void {
        if (open) return;
        opener = captureOpener();
        open = true;
        void start();
    }

    export function close(): void {
        if (!open || embedded) return;
        open = false;
        selectedId = null;
        stopEvents?.();
        stopEvents = null;
        restoreOpenerFocus(opener);
        opener = null;
    }

    export function isOpen(): boolean {
        return open;
    }

    onDestroy(() => stopEvents?.());

    function pickContext(id: string): void {
        contextId = id;
        selectedId = null;
        actions.clearError();
        hints = { restart: false, claude: null };
        void ctl.load();
        if (tab === 'census') void loadCensus();
    }

    async function loadCensus(): Promise<void> {
        censusError = null;
        try {
            census = await fetchCensus({ projectPath: context.projectPath, profile: context.profile }, fetcher);
        } catch (error) {
            census = null;
            censusError = refusalOf(error, t('skills.census.error'));
        }
    }

    function pickTab(next: 'skills' | 'census'): void {
        view = next;
        selectedId = null;
        if (next === 'census') void loadCensus();
    }

    // svelte-ignore state_referenced_locally
    let lastHostTab = hostTab;
    $effect(() => {
        const next = hostTab;
        if (next === undefined || next === lastHostTab) return;
        lastHostTab = next;
        pickTab(next);
    });

    const filters: ManagerFilter[] = $derived(
        [
            { id: 'claude', test: (item: ManagerItem) => (item as SkillItem).harnesses.includes('claude') },
            { id: 'codex', test: (item: ManagerItem) => (item as SkillItem).harnesses.includes('codex') },
            { id: 'off', test: (item: ManagerItem) => (item as SkillItem).off },
            { id: 'favorites', test: (item: ManagerItem) => skillFavorites.has(item.id) },
        ].map((chip) => ({ ...chip, label: t(`skills.page.filter.${chip.id}`), on: chips.includes(chip.id) })),
    );

    function onFilter(id: string, on: boolean): void {
        chips = on ? [...chips, id] : chips.filter((c) => c !== id);
    }

    const contextOptions = $derived([
        { value: GLOBAL_CONTEXT_ID, label: t('skills.page.context.global') },
        ...profileChoices.map((c) => ({ value: c.id, label: c.label, group: t('skills.page.context.group_profiles') })),
        ...projectChoices.map((c) => ({ value: c.id, label: c.label, group: t('skills.page.context.group_projects') })),
    ]);

    const pageItem = $derived(
        skillPage && embedded && tab === 'skills' && selectedId ? (ctl.items.find((row) => row.id === selectedId) as SkillItem | undefined) : undefined,
    );

    $effect(() => {
        if (skillPage && selectedId && inventory && !inventory.skills.some((g) => g.name === selectedId)) {
            selectedId = null;
            onBack?.();
        }
    });

    const limits = $derived(
        [
            t('skills.page.limit.codex'),
            ...(projectsFailed ? [t('skills.page.projects_failed')] : []),
            ...(inventory && inventory.settings_unparseable.length > 0
                ? [t('skills.page.unparseable', { files: inventory.settings_unparseable.join(', ') })]
                : []),
        ],
    );
</script>

{#snippet contextSelect()}
    <FacetSelect
        id="skills-context"
        label={t('skills.page.context.label')}
        value={contextId}
        options={contextOptions}
        onChange={pickContext}
    />
{/snippet}

{#snippet tabBody()}
    {#if tab === 'census'}
        {#if censusError}
            <p class="oc-page__error-detail" role="alert">{censusError}</p>
        {:else if census}
            <CensusTab {census} {query} {t} where={contextSelect} />
        {:else}
            <p class="oc-page__state" role="status">{t(MANAGER_KEYS.loading)}</p>
        {/if}
    {/if}
{/snippet}

{#if open && pageItem}
    <div class="skp-host" data-skill-page-host>
        <SkillPage item={pageItem} {inventory} {context} {actions} {fetcher} {t} onOpenCatalog={openCatalogPage} />
    </div>
{:else if open}
    <ManagerFrame
        title={t('skills.page.title')}
        label={t('skills.page.label')}
        {limits}
        limitsMode="tip"
        items={[...markedItems, ...offItems]}
        status={ctl.status}
        {query}
        onQuery={(next) => (query = next)}
        filters={tab === 'skills' ? filters : []}
        {onFilter}
        onClearFilters={() => (chips = [])}
        viewKey={tab === "skills" ? "skills" : undefined}
        defaultView="grid"
        cardMedia
        warezCards
        warezKind="skill"
        onStar={(id) => skillFavorites.toggle(id)}
        kit
        countBeside
        selectedId={tab === 'skills' ? selectedId : null}
        onSelect={(id) => {
            if (id && offIds.has(id)) return;
            selectedId = id;
            if (id) onPick?.(id);
        }}
        onToggle={(id, next) => void toggleCard(id, next)}
        toggles={installing ? { ...ctl.toggles, [installing.id]: { busy: installing.error === null, error: installing.error } } : ctl.toggles}
        onRetry={() => void ctl.load()}
        onClose={embedded ? undefined : close}
        emptyText={t('skills.page.empty')}
        {embedded}
        class="sk-page"
        {t}
        body={tab === 'skills' ? undefined : tabBody}
        top={tab === 'skills' ? highlights : undefined}
    >
        {#snippet toolbar()}
            {#if hostTab === undefined}
            <div class="sk-tabs" role="group" aria-label={t('skills.tab.label')}>
                {#each ['skills', 'census'] as const as id (id)}
                    <button
                        type="button"
                        class="oc-chip"
                        aria-pressed={tab === id}
                        data-skills-tab={id}
                        onclick={() => pickTab(id)}>{t(`skills.tab.${id}`)}</button
                    >
                {/each}
            </div>
            {/if}
            {#if tab === 'skills'}
                {@render contextSelect()}
            {/if}
            <RequiredSkills {fetcher} {t} />
            {#if hints.restart || hints.claude}
                <p class="sk-hint" role="status" data-skills-hint>
                    {[hints.restart ? t('skills.page.hint.restart') : null, hints.claude].filter(Boolean).join('. ')}
                </p>
            {/if}
        {/snippet}
        {#snippet detail(item)}
            <SkillDetailPane item={item as SkillItem} {inventory} {context} {actions} {fetcher} {t} onOpenCatalog={openCatalogPage} />
        {/snippet}
    </ManagerFrame>
{/if}
