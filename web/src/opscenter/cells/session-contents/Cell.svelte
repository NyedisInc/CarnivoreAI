<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';

  export const SESSION_CONTENTS_WIDGET = defineWidget({ id: 'core.session-contents', scope: 'session', actions: [], state: {} });
</script>

<script lang="ts">
  import type { CellProps } from '../../lib/cell';
  import { sessions } from '../../api';
  import { t } from '../../../lib/i18n/index.svelte';
  import { Button, Field, Fold, IconButton, List, ListRow, Segmented, State } from '../../../lib/base';
  import { readChoice, writeChoice } from '../../../lib/ui/prefs.svelte';
  import { truncatedTip } from '../../../lib/tooltip/truncated-tip';
  import Icon from '../../ui/Icon.svelte';
  import { useHeaderGroup } from '../../shell/frame-header.svelte';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import { useWidget } from '../../widgets/shell/define-widget.svelte';
  import { declareWidgetActions, type DeclaredAction } from '../../widgets/menu/declared-actions.svelte';
  import {
    DEFAULT_SCOPE, DEFAULT_SHOW_EMPTY, EMPTY_OPTION, SCOPES, SCOPE_ICONS, SCOPE_OPTION, accountOf, detailBeyondLines, itemKey, itemScopeIcon, kindKey, kindOneKey,
    refusalKey, scopeFilterOf, scopeKey, shownSections, showEmptyOf, statusKey, type ScopeFilter,
  } from './model';
  import { CONTROLS_HEAD_MIN_WIDTH } from './model';
  import { canOpen, openInFiles } from './opener';
  import { canPreview, loadHead } from './preview';
  import { contents } from './state.svelte';
  import type { ContentsItem } from './types';

  let props: CellProps = $props();
  const { scope = null, options, onOption, instance, width } = $derived(props);

  const widget = useWidget(SESSION_CONTENTS_WIDGET, () => props);

  const scopeStoreKey = (): string => `cloude_session_resources_scope_${instance}`;

  const sessionId = $derived(widget.sessionId);
  const row = $derived((sessions.data ?? []).find((info) => info.session.id === sessionId) ?? null);
  const rowId = $derived(scope?.rowId ?? (typeof row?.session_row_id === 'number' ? row.session_row_id : null));

  $effect(() => {
    contents.follow(rowId);
  });

  let localScope = $state<ScopeFilter>(readChoice(scopeStoreKey(), SCOPES, DEFAULT_SCOPE));
  const filter = $derived<ScopeFilter>(onOption ? scopeFilterOf(options?.[SCOPE_OPTION]) : localScope);

  function setScope(next: ScopeFilter): void {
    if (onOption) {
      onOption(SCOPE_OPTION, next);
      return;
    }
    localScope = next;
    writeChoice(scopeStoreKey(), next);
  }

  const emptyStoreKey = (): string => `cloude_session_resources_empty_${instance}`;
  const EMPTY_CHOICES = ['show', 'hide'] as const;

  let localShowEmpty = $state<boolean>(readChoice(emptyStoreKey(), EMPTY_CHOICES, DEFAULT_SHOW_EMPTY ? 'show' : 'hide') === 'show');
  const showEmpty = $derived<boolean>(onOption ? showEmptyOf(options?.[EMPTY_OPTION]) : localShowEmpty);

  function toggleEmpty(): void {
    const next = !showEmpty;
    if (onOption) {
      onOption(EMPTY_OPTION, next);
      return;
    }
    localShowEmpty = next;
    writeChoice(emptyStoreKey(), next ? 'show' : 'hide');
  }

  let expanded = $state<ReadonlySet<string>>(new Set(['instructions']));
  let text = $state('');
  let showPath = $state(false);
  let selectedKey = $state<string | null>(null);
  let openNote = $state(false);
  let head = $state<{ key: string; lines: string[] | null } | null>(null);

  function toggle(kind: string): void {
    const next = new Set(expanded);
    if (!next.delete(kind)) next.add(kind);
    expanded = next;
  }

  const shown = $derived(shownSections(contents.data?.sections ?? [], filter, text, showEmpty));
  const selected = $derived.by((): { kind: string; item: ContentsItem } | null => {
    for (const { section, items } of shown) {
      const hit = items.find((one) => itemKey(section.kind, one) === selectedKey);
      if (hit) return { kind: section.kind, item: hit };
    }
    return null;
  });

  function select(kind: string, one: ContentsItem): void {
    const key = itemKey(kind, one);
    if (key === selectedKey) return;
    selectedKey = key;
    openNote = false;
    head = null;
    if (!canPreview(kind, one)) return;
    void loadHead(kind, one, contents.data?.working_dir ?? null).then((lines) => {
      if (selectedKey === key) head = { key, lines };
    });
  }

  async function openFile(one: ContentsItem): Promise<void> {
    openNote = false;
    const result = await openInFiles(one, { sessionId: scope?.sessionId ?? (sessionId || null), rowId });
    openNote = result === 'unavailable';
  }

  const label = (one: ContentsItem): string => (showPath && one.path ? one.path : one.name);

  const scopeWord = (one: ScopeFilter): string => t(`opscenter.cell.session_contents.scope_filter.menu_${one}`);
  const frameHeader = $derived(widget.frame);

  const choices = $derived<DeclaredAction[]>([
    ...SCOPES.map((one) => ({
      id: `scope:${one}`, label: t(`opscenter.cell.session_contents.scope_filter.menu_${one}`), checked: filter === one, group: 'scope', run: () => setScope(one),
    })),
    { id: 'show-empty', label: t('opscenter.cell.session_contents.show_empty'), checked: showEmpty, toggle: true, group: 'view', run: toggleEmpty },
    { id: 'show-path', label: t('opscenter.cell.session_contents.show_path'), checked: showPath, toggle: true, group: 'view', run: () => (showPath = !showPath) },
    { id: 'refresh', label: t('opscenter.cell.session_contents.refresh'), group: 'view', blocked: rowId === null ? t('opscenter.cell.session_contents.no_session') : undefined, run: () => contents.refresh() },
  ]);

  $effect(() => {
    if (!frameHeader) return;
    return declareWidgetActions(frameHeader.hostId, 'resources', choices);
  });

  const place = useHeaderGroup(() => (width >= CONTROLS_HEAD_MIN_WIDTH ? controls : null));
</script>

{#snippet controls()}
  <Segmented label={t('opscenter.cell.session_contents.scope_filter.label')} iconOnly data-sc-scopes value={filter}
    options={SCOPES.map((one) => ({ value: one, label: scopeWord(one), icon: SCOPE_ICONS[one], attrs: { 'data-sc-scope': one } }))}
    onchange={(one) => setScope(one as ScopeFilter)} />
  <IconButton label={t('opscenter.cell.session_contents.show_empty')} variant="quiet" icon={showEmpty ? 'folder-eye' : 'folder-eye-off'} iconSize={15}
    pressed={showEmpty} data-sc-empty-toggle onclick={toggleEmpty} />
  <IconButton label={t('opscenter.cell.session_contents.show_path')} variant="quiet" icon="path" iconSize={15} pressed={showPath}
    data-sc-path-toggle onclick={() => (showPath = !showPath)} />
  <IconButton label={t('opscenter.cell.session_contents.refresh')} variant="quiet" icon="refresh" iconSize={15} data-sc-refresh
    disabled={rowId === null || contents.status === 'loading'} onclick={() => contents.refresh()} />
{/snippet}

<WidgetShell {widget}>
<div class="sc-cell" data-session-contents>
  <div class="sc-sub">
    <span class="sc-sub__who" use:truncatedTip={contents.data ? contents.data.config_dir : ''}>{contents.data ? `${contents.data.family} ${accountOf(contents.data.config_dir)}` : ''}</span>
    {#if !place.up}<span class="sc-sub__controls">{@render controls()}</span>{/if}
  </div>
  {#if rowId === null}
    <State inline title={t('opscenter.cell.session_contents.no_session')} />
  {:else if contents.status === 'error'}
    <State kind="error" inline title={t(refusalKey(contents.errorCode))} />
  {:else if !contents.data}
    <State kind="loading" inline title={t('opscenter.cell.session_contents.loading')} />
  {:else}
    <div class="sc-filter">
      <Field block bind:value={text} placeholder={t('opscenter.cell.session_contents.filter_placeholder')} data-sc-filter
        aria-label={t('opscenter.cell.session_contents.filter_label')} spellcheck="false" autocomplete="off" />
    </div>
    <div class="sc-body">
      {#each shown as { section, items } (section.kind)}
        <section class="sc-section" data-kind={section.kind}>
          <Fold label={t(kindKey(section.kind))} count={`${items.length}${section.truncated && filter === 'all' && !text ? '+' : ''}`}
            open={expanded.has(section.kind)} onOpenChange={() => toggle(section.kind)}>
            {#if expanded.has(section.kind) && items.length}
              <List density="dense" label={t(kindKey(section.kind))}>
                {#snippet children()}
                  {#each items as one (itemKey(section.kind, one))}
                    {@const key = itemKey(section.kind, one)}
                    <ListRow density="dense" selected={key === selectedKey} data-sc-row>
                      {#snippet children()}
                        <Button variant="row" data-sc-main aria-pressed={key === selectedKey} onclick={() => select(section.kind, one)}>
                          <span class="sc-row__body">
                            <span class="sc-row__scope sc-row__scope--{one.scope}" data-sc-scope-icon role="img" aria-label={t(scopeKey(one.scope))} title={t(scopeKey(one.scope))}>
                              <Icon name={itemScopeIcon(one.scope)} size={13} />
                            </span>
                            <span class="sc-row__name" data-sc-name use:truncatedTip={one.path ?? one.name}>{label(one)}</span>
                            {#if one.lines !== null}
                              <span class="sc-row__lines" data-sc-lines>
                                <span class="sc-row__lines-long" data-sc-lines-long>{t('opscenter.cell.session_contents.lines_long', { lines: one.lines })}</span>
                                <span class="sc-row__lines-short" data-sc-lines-short aria-hidden="true">{t('opscenter.cell.session_contents.lines_short', { lines: one.lines })}</span>
                              </span>
                            {/if}
                          </span>
                        </Button>
                      {/snippet}
                      {#snippet actions()}
                        {#if canOpen(one)}
                          <IconButton label={t('opscenter.cell.session_contents.open_file', { name: one.name })} variant="quiet" icon="files" iconSize={14}
                            data-sc-open onclick={() => void openFile(one)} />
                        {/if}
                      {/snippet}
                    </ListRow>
                  {/each}
                {/snippet}
              </List>
            {/if}
          </Fold>
        </section>
      {/each}
    </div>
    <div class="sc-details" data-sc-details aria-live="polite">
      {#if selected}
        <div class="sc-details__top">
          <span class="sc-details__name" use:truncatedTip={selected.item.name}>{selected.item.name}</span>
          <span class="sc-details__scope sc-details__scope--{selected.item.scope}"><Icon name={itemScopeIcon(selected.item.scope)} size={12} /> {t(scopeKey(selected.item.scope))}</span>
        </div>
        <p class="sc-details__line">
          {selected.item.lines === null ? t(kindOneKey(selected.kind)) : t('opscenter.cell.session_contents.details_lines', { lines: selected.item.lines, kind: t(kindOneKey(selected.kind)) })}
        </p>
        {#if detailBeyondLines(selected.item)}
          <p class="sc-details__line sc-details__line--dim">{detailBeyondLines(selected.item)}</p>
        {/if}
        <p class="sc-details__path" use:truncatedTip={selected.item.path ?? ''}>{selected.item.path ?? ''}</p>
        <p class="sc-details__line sc-details__line--dim">{t('opscenter.cell.session_contents.details_status', { status: t(statusKey(selected.item.status)) })}</p>
        <p class="sc-details__line sc-details__line--dim">{canOpen(selected.item) ? t('opscenter.cell.session_contents.details_open') : t('opscenter.cell.session_contents.details_no_file')}</p>
        {#if head && head.key === selectedKey && head.lines}
          <pre class="sc-details__head" data-sc-head>{head.lines.join('\n')}</pre>
        {/if}
        {#if openNote}<p class="sc-details__line sc-details__line--bad" role="status">{t('opscenter.cell.session_contents.open_failed', { name: selected.item.name })}</p>{/if}
      {:else}
        <p class="sc-details__line sc-details__line--dim">{t('opscenter.cell.session_contents.details_empty')}</p>
      {/if}
    </div>
    <div class="sc-strip">
      <span>{t('opscenter.cell.session_contents.strip_left')}</span>
      <span>{t('opscenter.cell.session_contents.strip_right')}</span>
    </div>
  {/if}
</div>
</WidgetShell>

<style>
  @layer components {
    .sc-cell {
      display: flex;
      flex-direction: column;
      flex: 1 1 auto;
      height: 100%;
      min-height: 0;
      font-family: var(--font-mono);
      container: oc-sc / inline-size;
      font-size: var(--oc-fs-label);
    }

    .sc-section :global(.oc-fold__toggle) { --_btn-h: var(--oc-control-h-sm); padding-inline: var(--oc-space-2); }
    .sc-section :global(.oc-fold__head) { background: var(--oc-ground-titlerow); box-shadow: inset 0 calc(-1 * var(--oc-border)) 0 var(--oc-line-rule); }
    .sc-section :global(.oc-fold__panel) { gap: 0; padding-bottom: 0; }

    .sc-sub {
      flex: none;
      display: flex;
      align-items: center;
      gap: var(--oc-space-1);
      height: 26px;
      padding: 0 var(--oc-space-2);
      box-shadow: inset 0 -1px 0 var(--oc-line-rule);
      font-size: var(--oc-fs-micro);
    }

    .sc-sub__who { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--oc-text-dim); }
    .sc-sub__controls { flex: none; display: flex; align-items: center; gap: var(--oc-space-1); }

    .sc-filter { flex: none; padding: var(--oc-space-2); box-shadow: inset 0 -1px 0 var(--oc-line-rule); }

    .sc-body { flex: 1 1 auto; min-height: 0; overflow-y: auto; }

    .sc-row__body { flex: 1 1 auto; min-width: 0; container: oc-sc-row / inline-size; display: flex; align-items: center; gap: var(--oc-space-2); }
    :global(.oc-list__row[data-sc-row] > [data-sc-main]) { flex: 1 1 auto; min-width: 0; }

    .sc-row__scope { flex: none; display: inline-flex; color: var(--oc-text-muted); }
    .sc-row__scope--project { color: var(--oc-cyan); }
    .sc-row__scope--plugin { color: var(--oc-orange); }
    .sc-row__name { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .sc-row__lines { flex: none; color: var(--oc-text-muted); font-size: var(--oc-fs-micro); }
    .sc-row__lines-short { display: none; }

    @container oc-sc-row (max-width: 310px) {
      .sc-row__lines-long { display: none; }
      .sc-row__lines-short { display: inline; }
    }

    .sc-details {
      flex: none;
      max-height: 40%;
      overflow-y: auto;
      padding: var(--oc-space-2);
      box-shadow: inset 0 1px 0 var(--oc-line-rule);
      font-size: var(--oc-fs-micro);
    }

    .sc-details__top { display: flex; align-items: baseline; gap: var(--oc-space-2); }
    .sc-details__name { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--oc-text-primary); font-size: var(--oc-fs-label); }
    .sc-details__scope { flex: none; display: inline-flex; align-items: center; gap: var(--oc-space-1); color: var(--oc-text-dim); text-transform: capitalize; font-size: var(--oc-fs-label); }
    .sc-details__scope--project { color: var(--oc-cyan); }
    .sc-details__scope--plugin { color: var(--oc-orange); }
    .sc-details__line { margin: var(--oc-space-1) 0 0; color: var(--oc-text-muted); }
    .sc-details__line--dim { color: var(--oc-text-dim); }
    .sc-details__line--bad { color: var(--oc-coral); }
    .sc-details__head {
      margin: var(--oc-space-1) 0 0;
      padding: var(--oc-space-1) 0 0;
      box-shadow: inset 0 1px 0 var(--oc-line-rule);
      overflow: hidden;
      color: var(--oc-text-muted);
      font: inherit;
      white-space: pre;
      text-overflow: ellipsis;
    }

    .sc-details__path { margin: var(--oc-space-1) 0 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--oc-text-dim); }

    .sc-strip {
      flex: none;
      display: flex;
      justify-content: space-between;
      gap: var(--oc-space-2);
      height: 22px;
      align-items: center;
      padding: 0 var(--oc-space-2);
      background: var(--oc-ground-titlerow);
      box-shadow: inset 0 1px 0 var(--oc-line-rule);
      color: var(--oc-text-dim);
      font-size: var(--oc-fs-micro);
    }
  }
</style>
