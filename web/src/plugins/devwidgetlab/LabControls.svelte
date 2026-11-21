<script lang="ts">
  import { t } from '../sdk';
  import { Button, Checkbox, ChoiceDropdown, FoldChevron, IconButton, Select, type ChoiceItem } from '../sdk/ui';
  import { FIXTURE_CHOICES, type FixtureChoice } from './frame-url';
  import { flipIn, flipPlacement, isDockPlacement, PLACEMENT_ORDER, placementsOn, PREVIEW_WIDTHS_SHOWN, type LabSelection, type Placement, type SizeOption } from './lab-selection';
  import { placementLabel, placementSummary } from './placement-label';

  interface Props {
    sel: LabSelection;
    themes: readonly { id: string; name: string }[];
    hosts: readonly string[];
    sizes: readonly SizeOption[];
    onset: (patch: Partial<LabSelection>) => void;
    onfixture: () => void;
    draftSlug?: string | null;
    added?: readonly string[];
    onadd?: (host: string) => Promise<boolean>;
  }

  const { sel, themes, hosts, sizes, onset, onfixture, draftSlug = null, added = [], onadd = async () => false }: Props = $props();

  const hostOf = (one: Placement): string => (isDockPlacement(one) ? 'drawer' : one);

  const declared = (one: Placement): boolean => hosts.includes(hostOf(one));
  const on = $derived(placementsOn(sel));
  const placementItems = $derived<ChoiceItem[]>(PLACEMENT_ORDER.map((one) => ({ id: one, label: placementLabel(one), disabled: !declared(one) && !draftSlug })));
  const noteOf = (one: Placement): string => (added.includes(hostOf(one)) ? t('cplug.devwidgetlab.show_in.added') : declared(one) ? '' : t('cplug.devwidgetlab.show_in.unused'));
  const titleOf = (one: Placement): string | undefined => (declared(one) ? undefined : t(draftSlug ? 'cplug.devwidgetlab.show_in.unused_draft_title' : 'cplug.devwidgetlab.show_in.unused_title'));

  async function toggle(id: string): Promise<void> {
    const one = id as Placement;
    if (!declared(one) && !(draftSlug && (await onadd(hostOf(one))))) return;
    onset({ ...flipPlacement(sel, one), focus: null });
  }
  const fixtureItems = $derived<ChoiceItem[]>(FIXTURE_CHOICES.map((one) => ({ id: one, label: t(`cplug.devwidgetlab.fixture.${one}`) })));
  const main = $derived(sizes.filter((one) => one.main));
  const more = $derived(sizes.filter((one) => !one.main));
  let moreOpen = $state(false);
  const moreShown = $derived(moreOpen || more.some((one) => sel.sizes.includes(one.name)));

  function step(by: number): void {
    if (themes.length === 0) return;
    const at = themes.findIndex((one) => one.id === sel.theme);
    onset({ theme: themes[(at + by + themes.length) % themes.length]!.id });
  }

  function sizeLabel(one: SizeOption): string {
    const first = one.widths[0];
    const last = one.widths[one.widths.length - 1];
    const px = first === last ? `${first}px` : `${first}-${last}px`;
    return `${one.name.toUpperCase()} / ${px}`;
  }
</script>

{#snippet width(one: SizeOption)}
  <Checkbox label={sizeLabel(one)} data-width-choice={one.name} checked={sel.sizes.includes(one.name)} onchange={() => onset({ sizes: flipIn(sel.sizes, one.name), focus: null })} />
{/snippet}

<div class="dwl-rows">
  <div class="dwl-row" data-show-in>
    <span class="dwl-label">{t('cplug.devwidgetlab.show_in')}</span>
    <ChoiceDropdown multiple compact dataKey="show-in" label={t('cplug.devwidgetlab.show_in')} items={placementItems} values={on} summary={placementSummary(on)}
      onToggle={(id) => void toggle(id)}>
      {#snippet row(item, state)}
        <span class="oc-check oc-check--bare dwl-pick" class:dwl-pick--off={!declared(item.id as Placement)} aria-checked={state.selected} title={titleOf(item.id as Placement)}>
          <span class="oc-check__box" aria-hidden="true"></span><span class="oc-check__label">{item.label}</span>
          {#if noteOf(item.id as Placement)}<span class="dwl-pick-note">{noteOf(item.id as Placement)}</span>{/if}</span>
      {/snippet}
    </ChoiceDropdown>
  </div>

  {#if PREVIEW_WIDTHS_SHOWN}
  <div class="dwl-field" role="group" aria-label={t('cplug.devwidgetlab.size')}>
    <p class="dwl-legend"><span class="dwl-label">{t('cplug.devwidgetlab.sizes.pick')}</span><span class="dwl-legend-note">{t('cplug.devwidgetlab.select_many')}</span></p>
    <div class="dwl-choices">
      {#each main as one (one.name)}{@render width(one)}{/each}
    </div>
    {#if more.length > 0}
      <Button variant="quiet" size="sm" data-more-key aria-expanded={moreShown} onclick={() => (moreOpen = !moreShown)}>
        <FoldChevron />{t('cplug.devwidgetlab.sizes.more', { count: more.length })}</Button>
      {#if moreShown}<div class="dwl-choices">{#each more as one (one.name)}{@render width(one)}{/each}</div>{/if}
    {/if}
  </div>
  {/if}

  <div class="dwl-row" data-fixture>
    <span class="dwl-label">{t('cplug.devwidgetlab.fixture')}</span>
    <ChoiceDropdown compact dataKey="fixture" label={t('cplug.devwidgetlab.fixture')} items={fixtureItems} value={sel.fixture} onChange={(id) => { onset({ fixture: id as FixtureChoice }); onfixture(); }}>
      {#snippet row(item)}<span class="dwl-pick-text">{item.label}</span>{/snippet}
    </ChoiceDropdown>
  </div>

  <div class="dwl-row">
    <label class="dwl-label" for="dwl-theme">{t('cplug.devwidgetlab.theme')}</label>
    <div class="dwl-seg dwl-seg--theme">
      <IconButton label={t('cplug.devwidgetlab.theme.prev')} icon="chevron-left" data-theme-step="prev" onclick={() => step(-1)} />
      <Select id="dwl-theme" size="sm" value={sel.theme} onchange={(event) => onset({ theme: event.currentTarget.value })}
        options={themes.length > 0 ? themes.map((one) => ({ value: one.id, label: one.name })) : [{ value: sel.theme, label: sel.theme }]} />
      <IconButton label={t('cplug.devwidgetlab.theme.next')} icon="chevron-right" data-theme-step="next" onclick={() => step(1)} />
    </div>
  </div>
</div>
