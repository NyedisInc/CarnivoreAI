<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';

  export const STAT_TILE_WIDGET = defineWidget({ id: 'core.stat-running', scope: 'global', actions: [], state: {} });
</script>

<script lang="ts">
  /* could not be determined */
  import type { CellProps } from '../../lib/cell';
  import Icon from '../../ui/Icon.svelte';
  import Sparkline from '../../ui/Sparkline.svelte';
  import StatTile from '../../../lib/base/StatTile.svelte';
  import { sessions, recent, projects, catalog, ledger } from '../../api';
  import { cardReading, delta, secondary, sparkBars } from './series';
  import { cardOfTile } from './tiles';
  import { deriveFigures, sampleFigures } from '../../data/stats';
  import { t } from '../../../lib/i18n/index.svelte';
  import { layoutEditor } from '../../layout-editor/editor.svelte';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import { useWidget } from '../../widgets/shell/define-widget.svelte';

  let props: CellProps = $props();
  const widget = useWidget(STAT_TILE_WIDGET, () => props);
  const height = $derived(props.height);

  const wide = $derived(widget.widthState === 'wide');
  const heightState = $derived(widget.heightState);
  const tall = $derived(heightState === 'graph');
  const line = $derived(heightState === 'line');
  const figurePx = $derived(Math.round(Math.max(20, Math.min(44, height * 0.3))));

  const sources = { sessions, recent, projects, catalog, ledger };
  const card = $derived(cardOfTile(props.meta.id));
  const drawn = $derived.by(() => {
    const figures = deriveFigures(sources);
    sampleFigures(figures, sources);
    if (!card) return null;
    const read = cardReading(card, figures);
    return {
      read,
      change: read.chart ? delta(card) : null,
      second: read.kind === 'value' ? secondary(card, figures) : null,
      bars: read.chart && tall ? sparkBars(card, wide ? 12 : 6) : [],
    };
  });
</script>

<WidgetShell {widget}>
{#if card && drawn}
  <StatTile
    id={card.id}
    label={t(!wide && card.shortLabelKey ? card.shortLabelKey : card.labelKey)}
    figure={drawn.read.text}
    kind={drawn.read.kind}
    size={wide ? 'regular' : 'compact'}
    mode={tall ? 'graph' : line ? 'line' : 'flat'}
    tone={card.tone}
    {figurePx}
    editing={layoutEditor.active}
    delta={drawn.change ?? ''}
    meter={drawn.second?.meter ?? null}
    sub={drawn.second?.text ?? ''}
    subLive={card.id === 'ledger'}
    icon={glyph}
    spark={drawn.bars.length ? spark : undefined}
  />
{/if}
</WidgetShell>

{#snippet glyph()}<Icon name={card?.icon ?? ''} size={12} strokeWidth={2} />{/snippet}

{#snippet spark()}
  {#if drawn && card}<Sparkline bars={drawn.bars} height={28} gap={card.sparkGap} barWidth={card.sparkBarWidth} />{/if}
{/snippet}
