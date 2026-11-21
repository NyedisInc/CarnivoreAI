<script lang="ts">
  /* the CHECKS block the viewer page the widget tree */
  import { onDestroy, onMount } from 'svelte';
  import { t } from '../sdk';
  import { activeThemeId, themeChoices } from '../sdk/themes';
  import { LAB_CATEGORIES, labWidgets } from '../sdk/widget-lab';
  import { draftsTreeGroup, draftWidget, revisionContext, type DraftRequest } from './drafts-model';
  import { DraftStore } from './drafts-store.svelte';
  import { labStatus, runCapture, type LabStatus } from './lab-api';
  import { LabLink } from './lab-channel.svelte';
  import { captureRequest, distinctWidgets, DRAFT_KEY_PREFIX, failingCount, filterGroups, OTHER_GROUP, treeGroups, uncheckedCount, type ResultFilter, type TreeGroup } from './lab-model';
  import { appliedRoutes, declaredZones, FALLBACK_THEME, framesOnShow, placementsOn, PREVIEW_WIDTHS_SHOWN, selectWidget, sizeOptions, type CheckScope, type LabIntent } from './lab-selection';
  import { placementSummary } from './placement-label';
  import { MatrixRunner } from './matrix-runner.svelte';
  import CaptureFooter from './CaptureFooter.svelte';
  import ChecksSection from './ChecksSection.svelte';
  import DraftActions from './DraftActions.svelte';
  import DraftForm from './DraftForm.svelte';
  import DraftPanel from './DraftPanel.svelte';
  import FindRow from './FindRow.svelte';
  import LabControls from './LabControls.svelte';
  import MenuSection from './MenuSection.svelte';
  import ScenarioBox from './ScenarioBox.svelte';
  import WidgetTree from './WidgetTree.svelte';
  import './lab.css';

  const { trailing = [] }: { trailing?: TreeGroup[] } = $props();

  const widgets = labWidgets();
  const themes = themeChoices();
  const groups = treeGroups(widgets, (id) => (id === OTHER_GROUP ? t('cplug.devwidgetlab.tree.other') : t(`widgets.page.category.${id}`)), LAB_CATEGORIES);

  function heard(intent: LabIntent): void {
    if (intent.intent === 'fixture' && fixtureJson === '') fixtureJson = intent.json;
  }

  const link = new LabLink('menu', widgets, activeThemeId() ?? themes[0]?.id ?? FALLBACK_THEME, heard);
  const drafts = new DraftStore();
  drafts.onchange = () => link.announceDrafts();
  const runner = new MatrixRunner(() => link.setLive({ matrixSeq: link.live.matrixSeq + 1 }));

  let status = $state<LabStatus>({ available: false, reason: 'unknown', captures_dir: '' });
  let query = $state('');
  let result = $state<ResultFilter>('all');
  let scope = $state<CheckScope>('all');
  let scenarioText = $state(link.selection.scenario ?? '');
  let fixtureJson = $state('');
  let lastBatch = $state<{ ok: number; failed: number } | null>(null);
  let form = $state<'new' | 'revision' | null>(null);
  let revisionOpen = $state(true);

  const sel = $derived(link.selection);
  const widget = $derived(widgets.find((one) => one.key === sel.widget));
  const draft = $derived(drafts.find(sel.draft));
  const onShow = $derived((draft ? draftWidget(draft, widgets) : undefined) ?? widget);
  const table = $derived(runner.state?.table ?? null);
  const shown = $derived(filterGroups(groups, query, result, table));
  const draftsGroup = $derived(draftsTreeGroup(drafts.state.drafts, t, widgets, LAB_CATEGORIES));
  const shownTrailing = $derived(filterGroups(drafts.state.available || draftsGroup.leaves.length > 0 ? [...trailing, draftsGroup] : trailing, query, result, table));
  const frames = $derived(framesOnShow(onShow, sel));
  const filtering = $derived(query.trim() !== '' || result !== 'all');
  const failing = $derived(failingCount(table));
  const unchecked = $derived(uncheckedCount(groups, table));
  const total = distinctWidgets(groups.flatMap((group) => group.leaves));

  const placements = $derived(placementsOn(sel));
  const previewValue = $derived(
    [
      placementSummary(placements),
      ...(PREVIEW_WIDTHS_SHOWN ? [sel.sizes.join(' ')] : []),
      t(`cplug.devwidgetlab.fixture.${sel.fixture}`),
    ].join(' / '),
  );
  const checkTarget = $derived(sel.view === 'fit' || sel.draft !== null || widget === undefined ? null : widget.key);
  const scenarioValue = $derived(
    sel.scenario === null ? t('cplug.devwidgetlab.scenario.none') : sel.scenario !== scenarioText ? t('cplug.devwidgetlab.scenario.edited') : t('cplug.devwidgetlab.scenario.routes', { count: appliedRoutes(sel.scenario) }),
  );
  const captureValue = $derived.by(() => {
    const running = link.live.capturing;
    if (running) return t('cplug.devwidgetlab.capture.progress', { done: running.done, total: running.total });
    if (lastBatch) return lastBatch.failed === 0 ? t('cplug.devwidgetlab.capture.done', { ok: lastBatch.ok }) : t('cplug.devwidgetlab.capture.some_failed', { ok: lastBatch.ok, failed: lastBatch.failed });
    return frames.length === 1 ? t('cplug.devwidgetlab.capture.count_one') : t('cplug.devwidgetlab.capture.count', { count: frames.length });
  });
  const checksValue = $derived.by(() => {
    if (runner.state?.running) return t('cplug.devwidgetlab.fit.header_running');
    if (!table) return t('cplug.devwidgetlab.fit.header_none');
    return t('cplug.devwidgetlab.fit.header_last', { pass: table.counts.pass, fail: table.counts.fail });
  });

  onMount(() => {
    void drafts.refresh();
    labStatus().then(
      (next) => (status = next),
      (error: unknown) => console.warn('[widget lab] status', error),
    );
    void runner.refresh();
  });
  onDestroy(() => {
    drafts.destroy();
    runner.destroy();
    link.destroy();
  });

  function resetFixture(): void {
    fixtureJson = '';
  }

  function showFit(): void {
    link.set({ view: 'fit', draft: null, focus: null });
  }

  function pick(key: string): void {
    if (key.startsWith(DRAFT_KEY_PREFIX)) return pickDraft(key.slice(DRAFT_KEY_PREFIX.length));
    link.replace(selectWidget(sel, widgets.find((one) => one.key === key)));
    resetFixture();
  }

  function pickDraft(slug: string): void {
    const picked = drafts.find(slug);
    const target = picked?.kind === 'revision' ? widgets.find((one) => one.key === picked.widget) : undefined;
    link.replace({ ...(target ? selectWidget(sel, target) : sel), draft: slug, view: 'compare', focus: null });
  }

  async function submitDraft(request: DraftRequest): Promise<void> {
    const made = await drafts.create(request);
    if (!made.ok || !made.draft) return;
    form = null;
    pickDraft(made.draft.slug);
  }

  async function discardDraft(slug: string): Promise<void> {
    if ((await drafts.discard(slug)).ok) link.set({ draft: null, view: 'widget', focus: null });
  }

  async function captureAll(): Promise<void> {
    const todo = frames;
    let ok = 0;
    let failed = 0;
    link.setLive({ capturing: { done: 0, total: todo.length } });
    try {
      for (const [index, frame] of todo.entries()) {
        const outcome = await runCapture(
          captureRequest({ widget: sel.widget, host: frame.host, size: frame.size, theme: sel.theme, fixture: sel.fixture }, sel.scenario, 'normal',
            frame.host === 'drawer' && frame.dock === 'left' ? sel.sidebar : null),
        );
        if (outcome.ok) ok += 1;
        else failed += 1;
        link.setLive({ captures: [outcome, ...link.live.captures], capturing: { done: index + 1, total: todo.length } });
      }
    } finally {
      lastBatch = { ok, failed };
      link.setLive({ capturing: null });
    }
  }
</script>

<div class="dwl-menu">
  <div class="dwl-scroll">
    {#if form}
      <DraftForm mode={form} widget={sel.widget} context={revisionContext({ ...sel, scenarioRoutes: appliedRoutes(sel.scenario) })} busy={drafts.busy} error={drafts.error}
        onsubmit={(request) => void submitDraft(request)} oncancel={() => (form = null)} />
    {:else}
      <FindRow bind:query bind:result hasTable={table !== null} {failing} {unchecked} />
      <WidgetTree groups={shown} trailing={shownTrailing} picked={sel.draft ? `${DRAFT_KEY_PREFIX}${sel.draft}` : sel.widget} {table} {total} {filtering} fitOnShow={sel.view === 'fit'} onpick={pick}
        onfit={showFit} />
    {/if}
    <DraftActions available={drafts.state.available} canRevise={widget !== undefined && sel.draft === null} source={drafts.state.source}
      onnew={() => { drafts.error = ''; form = 'new'; }}
      onrevise={() => { drafts.error = ''; form = 'revision'; }} />

    <MenuSection label={t('cplug.devwidgetlab.section.preview')} value={previewValue} open={link.folds.preview} ontoggle={(open) => link.setFold('preview', open)}>
      <LabControls {sel} {themes} hosts={declaredZones(onShow)} sizes={sizeOptions(onShow)} onset={(patch) => link.set(patch)} onfixture={resetFixture}
        draftSlug={draft?.kind === 'new' ? draft.slug : null} added={draft ? drafts.added[draft.slug] ?? [] : []}
        onadd={async (host) => (draft ? (await drafts.addHost(draft.slug, host)).ok : false)} />
    </MenuSection>
    <MenuSection label={t('cplug.devwidgetlab.scenario.title')} value={scenarioValue} tone={sel.scenario !== null && sel.scenario !== scenarioText ? 'warn' : undefined}
      open={link.folds.scenario} ontoggle={(open) => link.setFold('scenario', open)}>
      <ScenarioBox bind:text={scenarioText} applied={sel.scenario} {fixtureJson} onapply={(text) => link.set({ scenario: text })} onclear={() => link.set({ scenario: null })} />
    </MenuSection>
    <MenuSection label={t('cplug.devwidgetlab.section.capture')} value={captureValue} tone={lastBatch && lastBatch.failed > 0 ? 'bad' : undefined} open={link.folds.capture} ontoggle={(open) => link.setFold('capture', open)}>
      <CaptureFooter count={frames.length} running={link.live.capturing} last={lastBatch} available={status.available && sel.draft === null} reason={sel.draft !== null ? 'draft' : status.reason} oncapture={() => void captureAll()} />
    </MenuSection>
    {#if draft}
      <MenuSection label={t('cplug.devwidgetlab.section.revision')} value={t(`cplug.devwidgetlab.drafts.state.${draft.state}`)} open={revisionOpen} ontoggle={(open) => (revisionOpen = open)}>
        <DraftPanel {draft} compare={sel.compare} busy={drafts.busy} error={drafts.error} onbuild={() => void drafts.build(draft.slug)} onhand={() => void drafts.handToClaude(draft.slug)}
          ondiscard={() => void discardDraft(draft.slug)} oncompare={(mode) => link.set({ compare: mode })} />
      </MenuSection>
    {/if}
    <MenuSection label={t('cplug.devwidgetlab.section.checks')} value={checksValue} tone={table && table.counts.fail > 0 ? 'bad' : undefined} open={link.folds.checks} ontoggle={(open) => link.setFold('checks', open)}>
      <ChecksSection {runner} bind:scope selected={checkTarget} {total} onshow={showFit} />
    </MenuSection>
  </div>

  <p class="dwl-links"><a class="dwl-link" href="/static/style-guide.html" target="_blank" rel="noopener">{t('cplug.devwidgetlab.links.style_guide')}</a></p>
</div>
