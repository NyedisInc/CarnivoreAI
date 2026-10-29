<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';

  export const THEMES_WIDGET = defineWidget({ id: 'core.themes', scope: 'global', actions: [], state: {} });
</script>

<script lang="ts">
  import { onMount } from 'svelte';
  import type { CellProps } from '../../lib/cell';
  import { atLeast } from '../../lib/states';
  import { themes, openThemes } from '../../api';
  import { tile, tileRows, CHIP_LEFT, CHIP_WIDTH, LINE_LEFT, LINE_HEIGHT, TILES_PER_ROW, buildTiles, visibleTiles, type RenderTile } from './meta';
  import { themesCellView } from './view.svelte';
  import { themeFavorites } from '../../../lib/themes-page/favorites.svelte';
  import { t } from '../../../lib/i18n/index.svelte';
  import Button from '../../../lib/base/Button.svelte';
  import State from '../../../lib/base/State.svelte';
  import { stateKindOf } from '../../../lib/base/state-kind';
  import Icon from '../../ui/Icon.svelte';
  import { IconButton } from '../../../lib/base';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import { useWidget } from '../../widgets/shell/define-widget.svelte';
  import { declareWidgetActions } from '../../widgets/menu/declared-actions.svelte';

  let props: CellProps = $props();
  const { meta } = $derived(props);
  const phone = $derived(props.phone ?? false);

  const widget = useWidget(THEMES_WIDGET, () => props);

  function selectTheme(id: string): void {
    const registry = (globalThis as { Themes?: { applyTheme(id: string, options: { persist: boolean }): boolean } }).Themes;
    registry?.applyTheme(id, { persist: true });
  }

  let pageTheme = $state<string | null>(null);
  onMount(() => {
    const read = (): void => { pageTheme = document.documentElement.dataset.theme ?? null; };
    read();
    const observer = new MutationObserver(read);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    return () => observer.disconnect();
  });

  const widthState = $derived(widget.widthState);
  const heightState = $derived(widget.heightState);

  const PHONE_GAP = 10;

  const perRow = $derived(phone ? 3 : (TILES_PER_ROW[widthState] ?? 2));
  const showsGrid = $derived(phone ? true : atLeast(meta.heightStates, heightState, 'tiles-1row'));
  const showsNames = $derived(phone ? true : atLeast(meta.heightStates, heightState, 'names'));
  const isBig = $derived(phone ? false : atLeast(meta.heightStates, heightState, 'tiles-big'));

  const view = $derived(themesCellView.value);
  const builtTiles = $derived(visibleTiles(themes.data, pageTheme, view, themeFavorites.ids));
  const tiles = $derived(phone ? [...builtTiles].sort((a, b) => Number(b.current) - Number(a.current)) : builtTiles);
  const current = $derived(tiles.find((t) => t.current));

  /* there is nothing */
  const notice = $derived.by((): string | null => {
    if (themes.status === 'loading') return t('opscenter.themes.loading');
    if (themes.status === 'signed-out') return t('opscenter.themes.signed_out');
    if (themes.status === 'unavailable') return t('opscenter.themes.unavailable');
    if (themes.status === 'error') return themes.error ?? t('opscenter.themes.error');
    if (!tiles.length) {
      return view === 'favorites' && buildTiles(themes.data, pageTheme).length
        ? t('themes.cell.no_favorites')
        : t('opscenter.themes.none');
    }
    return null;
  });

  function preview(theme: RenderTile) {
    return tileRows.map((row, index) => ({ ...row, ...(theme.rows[index] ?? theme.rows[0]) }));
  }

  function toggleView(): void {
    themesCellView.set(view === 'favorites' ? 'all' : 'favorites');
  }

  const frameHeader = $derived(widget.frame);
  $effect(() => {
    if (!frameHeader) return;
    const action = { id: 'favorites', label: t('themes.cell.favorites_only'), checked: view === 'favorites', toggle: true, run: toggleView };
    return declareWidgetActions(frameHeader.hostId, 'view', [action]);
  });
</script>

{#snippet viewToggle()}
  <span class="oc-themes-toggle">
    <IconButton label={t('themes.cell.favorites_only')} variant="quiet" pressed={view === 'favorites'} onclick={toggleView}>
      <Icon name="star" size={15} fill={view === 'favorites' ? 'solid' : 'outline'} />
    </IconButton>
  </span>
{/snippet}

<WidgetShell {widget} controls={viewToggle}>
<div class="oc-themes">
  {#if notice}
    {#if heightState !== 'title'}
      {#if view === 'favorites' && themes.status === 'ok' && !tiles.length}
        <State inline data-themes-notice title={notice}>
          {#snippet actions()}<Button size="sm" onclick={() => void openThemes()}>{t('themes.cell.open_page')}</Button>{/snippet}
        </State>
      {:else}
        <State inline data-themes-notice kind={stateKindOf(themes.status)} title={notice} />
      {/if}
    {/if}
  {:else}
  {#if showsNames}
    <ul
      class="oc-tile-grid"
      class:oc-tile-grid-big={isBig}
      style={`--oc-tiles-per-row: ${perRow}; --oc-tile-w: ${phone ? '1fr' : `${tile.width}px`}; --oc-tile-gap: ${phone ? PHONE_GAP : tile.gap}px`}
    >
      {#each tiles as theme (theme.id)}
        <li class="oc-tile" data-tile={theme.id} class:oc-tile-current={theme.current}>
          <button type="button" class="oc-theme-choice" onclick={() => selectTheme(theme.id)} aria-pressed={theme.current} aria-label={`use ${theme.name} as page theme`}>
          {#if showsGrid}
            <span
              class="oc-tile-swatch"
              style={`background: ${theme.interior};${theme.border ? ` --oc-tile-border: ${theme.border};` : ''}`}
            >
              {#if theme.artwork}<img class="oc-tile-art" src={theme.artwork} alt="" loading="lazy" decoding="async" />{/if}
              {#if theme.ascii}<span class="oc-tile-ascii" aria-hidden="true">░▒▓╞═══╪───</span>{/if}
              {#each preview(theme) as row, index (index)}
                <span
                  class="oc-tile-chip"
                  style={`left:${CHIP_LEFT}px; top:${row.chipTop}px; width:${CHIP_WIDTH}px; height:${row.chipHeight}px; background: ${row.chip}`}
                ></span>
                {#if row.lineWidth > 0 && row.line}
                  <span
                    class="oc-tile-line"
                    style={`left:${LINE_LEFT}px; top:${row.lineTop}px; width:${row.lineWidth}px; height:${LINE_HEIGHT}px; background: ${row.line}`}
                  ></span>
                {/if}
              {/each}
            </span>
          {/if}
          <span class="oc-tile-name">{theme.name}</span>
          {#if theme.current}<span class="oc-tile-state">{t('opscenter.themes.current')}</span>{/if}
          </button>
        </li>
      {/each}
    </ul>
  {/if}

  {#if isBig && current}
    <div class="oc-preview" style={`background: ${current.interior}`}>
      {#each preview(current).slice(0, 3) as row, index (index)}
        {@const lineTone = row.line ?? row.chip}
        <span
          class="oc-preview-chip"
          style={`left:16px; top:${row.chipTop}px; width:${CHIP_WIDTH}px; height:${row.chipHeight}px; background: ${row.chip}`}
        ></span>
        <span
          class="oc-preview-line"
          style={`left:${16 + LINE_LEFT - CHIP_LEFT}px; top:${row.lineTop}px; width:${row.lineWidth}px; height:${LINE_HEIGHT}px; background: ${lineTone}`}
        ></span>
      {/each}
      <span class="oc-preview-label">{t('opscenter.themes.preview', { name: current.name })}</span>
    </div>
  {/if}
  {/if}
</div>
</WidgetShell>

<style>
  @layer components {
    .oc-theme-choice { display:block; width:100%; border:0; padding:0; background:transparent; font:inherit; color:inherit; cursor:pointer; text-align:inherit; }

    .oc-tile-art { position:absolute; left:0; top:0; width:100%; height:100%; object-fit:cover; opacity:.65; }

    .oc-tile-ascii { position:absolute; inset:0 auto auto 0; font:7px/8px var(--oc-font); color:var(--oc-text-bright); }

    .oc-themes {
      display: flex;
      flex-direction: column;
      gap: calc(var(--oc-space-3) + var(--oc-space-0-5));
      min-width: 0;
      min-height: 0;
      height: 100%;
      overflow-y: auto;
      overflow-x: hidden;
      padding: calc(var(--oc-space-3) + var(--oc-space-0-5)) var(--oc-cell-pad) var(--oc-space-3) calc(var(--oc-cell-pad) - var(--oc-space-0-5));
    }

    .oc-themes-toggle {
      display: inline-flex;
      margin-left: var(--oc-space-1);
    }



    .oc-tile-grid {
      display: grid;
      grid-template-columns: repeat(var(--oc-tiles-per-row), var(--oc-tile-w));
      justify-content: start;
      gap: var(--oc-tile-gap);
      margin: 0;
      padding: 0;
      list-style: none;
      min-width: 0;
    }

    .oc-themes .oc-tile {
      display: block;
      width: auto;
      min-width: 0;
      padding: 0;
      border: 0;
      background: transparent;
      text-align: left;
    }

    .oc-tile-swatch {
      position: relative;
      display: block;
      aspect-ratio: 16 / 10;
      border: var(--oc-border) solid var(--oc-tile-border, var(--oc-line-panel));
      border-radius: var(--oc-radius-sm);
      overflow: hidden;
    }

    .oc-tile-current .oc-tile-swatch {
      border-color: var(--oc-orange);
    }

    .oc-tile-chip,
    .oc-tile-line,
    .oc-preview-chip,
    .oc-preview-line {
      position: absolute;
      border-radius: 1px;
    }

    .oc-tile-name,
    .oc-tile-state {
      display: block;
      margin-top: var(--oc-space-1-5);
      text-align: center;
      font-size: var(--oc-fs-label);
      color: var(--oc-text-secondary);
    }

    .oc-tile-current .oc-tile-name {
      color: var(--oc-text-bright);
      font-weight: 700;
    }

    .oc-tile-state {
      margin-top: var(--oc-border);
      color: var(--oc-text-dim);
    }

    .oc-preview {
      position: relative;
      flex: 0 0 auto;
      min-width: 0;
      height: 44px;
      border: var(--oc-border) solid var(--oc-orange);
      border-radius: var(--oc-radius-sm);
      overflow: hidden;
    }

    .oc-preview-label {
      position: absolute;
      right: 14px;
      top: 50%;
      transform: translateY(-50%);
      font-size: var(--oc-fs-label);
      color: var(--oc-text-secondary);
    }
  }
</style>
