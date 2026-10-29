<script lang="ts">
  import ChartFrame from '../../lib/base/ChartFrame.svelte';
  import StatTile from '../../lib/base/StatTile.svelte';
  import SparkLine from '../../opscenter/viz/SparkLine.svelte';
  import Sparkline, { type SparkBar } from '../../opscenter/ui/Sparkline.svelte';

  const POINTS = [3, 5, 4, 8, 6, 9, 7, 12, 10, 14, 11, 15];
  const BARS: SparkBar[] = POINTS.map((value) => ({ h: value, tone: '--oc-green' }));
  const TILES = [
    { name: '92 x 56, line', w: 92, h: 56, size: 'compact', mode: 'line' },
    { name: '92 x 56, flat', w: 92, h: 56, size: 'compact', mode: 'flat' },
    { name: '192 x 56, line', w: 192, h: 56, size: 'regular', mode: 'line' },
    { name: '192 x 64, flat', w: 192, h: 64, size: 'regular', mode: 'flat' },
    { name: '192 x 136, graph', w: 192, h: 136, size: 'regular', mode: 'graph' },
  ] as const;
  const CHARTS = [
    { name: '260 x 120', w: 260, h: 120 },
    { name: '420 x 200', w: 420, h: 200 },
    { name: '640 x 260', w: 640, h: 260 },
  ] as const;
</script>

<div class="sg-sw">
  <div class="sg-sw__row">
    {#each TILES as tile (tile.name)}
      <div class="sg-sw__cell">
        <span class="sg-bc__label">stat tile {tile.name}</span>
        <div class="sg-sw__box" style:width="{tile.w}px" style:height="{tile.h}px">
          <StatTile label={tile.size === 'compact' ? 'running' : 'working now'} figure="7" size={tile.size} mode={tile.mode} tone="--oc-green"
            delta="up 2" meter={60} sub="of 12 alive">
            {#snippet icon()}&#9656;{/snippet}
            {#snippet spark()}<Sparkline bars={BARS} height={28} gap={2} barWidth={6} />{/snippet}
          </StatTile>
        </div>
      </div>
    {/each}
  </div>

  <div class="sg-sw__row">
    <div class="sg-sw__cell">
      <span class="sg-bc__label">a sentence, 192 x 64</span>
      <div class="sg-sw__box" style:width="192px" style:height="64px">
        <StatTile label="ledger" figure="no accounts yet" kind="note" size="regular" mode="flat" tone="--oc-orange" />
      </div>
    </div>
    <div class="sg-sw__cell">
      <span class="sg-bc__label">not measured, 92 x 56</span>
      <div class="sg-sw__box" style:width="92px" style:height="56px">
        <StatTile label="projects" figure="--" kind="dim" size="compact" mode="flat" tone="--oc-green" />
      </div>
    </div>
    <div class="sg-sw__cell">
      <span class="sg-bc__label">kpi card, no frame, display figure</span>
      <div class="sg-sw__box sg-sw__chart" style:width="260px" style:height="160px">
        <StatTile label="tokens" meta="24 hours" figure="12.4" unit="m" size="regular" mode="graph" display framed={false} delta="up 4.2%"
          deltaNote="vs prior" deltaTone="up">
          {#snippet spark()}<SparkLine points={POINTS} />{/snippet}
        </StatTile>
      </div>
    </div>
  </div>

  <div class="sg-sw__row">
    {#each CHARTS as chart (chart.name)}
      <div class="sg-sw__cell">
        <span class="sg-bc__label">chart body {chart.name}</span>
        <div class="sg-sw__chart" style:width="{chart.w}px" style:height="{chart.h}px">
          <div class="sg-sw__title">tokens</div>
          <div class="sg-sw__body">
            <ChartFrame size={chart.h < 150 ? 'tile' : 'panel'} label="tokens">
              <div class="oc-chart-frame__headline"><strong>12.4m</strong><span>tokens, 24 hours</span></div>
              <p class="oc-chart-frame__note">up 4.2% vs prior</p>
              {#if chart.h >= 200}
                <ul class="oc-chart-frame__list">
                  <li><span>claude</span><strong>9.1m</strong></li>
                  <li><span>codex</span><strong>3.3m</strong></li>
                </ul>
              {/if}
              <div class="oc-chart-frame__plot"><SparkLine points={POINTS} /></div>
            </ChartFrame>
          </div>
        </div>
      </div>
    {/each}
  </div>
</div>
