<script lang="ts">
  import { tick } from 'svelte';
  import { t } from '../sdk';
  import { FoldChevron, Icon, watchCascadeHint } from '../sdk/ui';
  import { distinctWidgets, DRAFT_KEY_PREFIX, widgetStatus, widgetVerdict, type FitTable, type TreeGroup } from './lab-model';
  import WidgetTreeMenu from './WidgetTreeMenu.svelte';
  import { foldAll, groupOpen, readTreeFolds, ROOT_FOLD, rootOpen, writeTreeFolds, type TreeFolds } from './tree-folds';

  interface Props {
    groups: TreeGroup[];
    trailing?: TreeGroup[];
    total?: number;
    picked: string;
    table: FitTable | null;
    filtering?: boolean;
    fitOnShow?: boolean;
    onpick: (key: string) => void;
    onfit: () => void;
  }

  const { groups, trailing = [], total = 0, picked, table, filtering = false, fitOnShow = false, onpick, onfit }: Props = $props();

  let folds = $state<TreeFolds>(readTreeFolds());

  const shown = $derived([...groups, ...trailing]);

  const isOpen = (group: TreeGroup): boolean => groupOpen(group, folds, picked, filtering);

  const failsIn = (group: TreeGroup): number => distinctWidgets(group.leaves.filter((leaf) => widgetVerdict(table, leaf.key) === 'fail'));

  const allOpen = $derived(rootOpen(folds, filtering));

  function keep(next: TreeFolds): void {
    folds = next;
    writeTreeFolds(folds);
  }

  function toggle(id: string, open: boolean, event: MouseEvent): void {
    keep(event.shiftKey ? foldAll(shown, !open) : { ...folds, [id]: !open });
  }

  function keepShiftOffSelection(event: MouseEvent): void {
    if (event.shiftKey) event.preventDefault();
  }

  let nav = $state<HTMLElement | null>(null);
  let menu = $state<{ at: { x: number; y: number }; key: string; label: string } | null>(null);

  function rowMenu(event: MouseEvent, key: string, label: string): void {
    event.preventDefault();
    menu = { at: { x: event.clientX, y: event.clientY }, key, label };
  }

  async function copyKey(key: string): Promise<void> {
    try {
      await navigator.clipboard.writeText(key);
    } catch (error) {
      console.warn('[widget lab] copy key', error);
    }
  }

  $effect(() => {
    void picked;
    void tick().then(() => nav?.querySelector<HTMLElement>('[aria-current="true"]')?.scrollIntoView?.({ block: 'nearest' }));
  });
</script>

{#snippet verdict(key: string)}
  {@const status = widgetStatus(table, key)}
  <span class="dwl-verdict" data-verdict={status.verdict}>{status.verdict === 'fail' && status.failures > 0 ? t('cplug.devwidgetlab.verdict.fails', { count: status.failures }) : t(`cplug.devwidgetlab.verdict.${status.verdict}`)}</span>
{/snippet}

<nav class="dwl-tree" bind:this={nav} aria-label={t('cplug.devwidgetlab.tree.title')}>
  <button type="button" class="dwl-all" data-all-fit aria-current={fitOnShow ? 'true' : undefined} onclick={onfit}>
    <Icon name="grid" size={14} />
    <span class="dwl-all-text"><span class="dwl-all-name">{t('cplug.devwidgetlab.tree.all_fit')}</span><span class="dwl-all-sub">{t('cplug.devwidgetlab.tree.all_sub')}</span></span>
    {#if total > 0}<span class="dwl-group-count">{total}</span>{/if}
  </button>
  <button type="button" class="dwl-group dwl-group--root" data-group-root aria-expanded={allOpen} {@attach watchCascadeHint} onmousedown={keepShiftOffSelection}
    onclick={(event) => toggle(ROOT_FOLD, allOpen, event)}>
    <FoldChevron /><span class="dwl-leaf-name">{t('cplug.devwidgetlab.tree.title')}</span><span class="dwl-group-count">{total}</span>
  </button>
  {#if allOpen}{#each shown as group (group.id)}
    <button type="button" class="dwl-group dwl-group--nested" data-group={group.id} aria-expanded={isOpen(group)} {@attach watchCascadeHint} onmousedown={keepShiftOffSelection}
      onclick={(event) => toggle(group.id, isOpen(group), event)}>
      <FoldChevron /><span class="dwl-leaf-name">{group.label}</span><span class="dwl-group-count">{distinctWidgets(group.leaves)}{#if failsIn(group) > 0}<span class="dwl-group-fail"> {t('cplug.devwidgetlab.tree.group_failing', { count: failsIn(group) })}</span>{/if}</span>
    </button>
    {#if isOpen(group)}
      {#each group.leaves as leaf, at (leaf.key)}
        {#if leaf.category !== undefined && leaf.category !== group.leaves[at - 1]?.category}
          <span class="dwl-draft-cat" data-draft-cat={leaf.category}>{leaf.categoryLabel}</span>
        {/if}
        <button type="button" class="dwl-leaf dwl-leaf--nested" class:dwl-leaf--draft={leaf.tag !== undefined} aria-current={!fitOnShow && picked === leaf.key ? 'true' : undefined}
          oncontextmenu={(event) => rowMenu(event, leaf.key, leaf.label)} data-key={leaf.key} data-draft-row={leaf.tag !== undefined ? leaf.key.slice(DRAFT_KEY_PREFIX.length) : undefined} onclick={() => onpick(leaf.key)}>
          {#if leaf.tag !== undefined}<span class="dwl-draft-tag">{leaf.tag}</span>{:else}<span class="dwl-dot" data-verdict={widgetVerdict(table, leaf.key)} aria-hidden="true"></span>{/if}
          <span class="dwl-leaf-name">{leaf.label}</span>
          {#if leaf.status !== undefined}<span class="dwl-draft-state" data-state={leaf.statusKey}>{leaf.status}</span>{:else}{@render verdict(leaf.key)}{/if}
        </button>
      {/each}
    {/if}
  {/each}{/if}
  {#if groups.length === 0}
    <p class="dwl-note dwl-tree-empty">{filtering ? t('cplug.devwidgetlab.tree.no_match') : t('cplug.devwidgetlab.widget.none')}</p>
  {/if}
</nav>
{#if menu}
  {@const row = menu}
  {#key `${row.at.x},${row.at.y}`}
    <WidgetTreeMenu at={row.at} label={row.label} onshow={() => onpick(row.key)} oncopy={() => void copyKey(row.key)} onclose={() => (menu = null)} />
  {/key}
{/if}
