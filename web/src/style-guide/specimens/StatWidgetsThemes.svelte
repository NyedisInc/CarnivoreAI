<script lang="ts">
  import ChartFrame from '../../lib/base/ChartFrame.svelte';
  import StatTile from '../../lib/base/StatTile.svelte';
  import SparkLine from '../../opscenter/viz/SparkLine.svelte';
  import { guideThemes, onGuideTheme, paintScope, type GuideTheme } from '../theme-scope';

  const POINTS = [3, 5, 4, 8, 6, 9, 7, 12, 10, 14, 11, 15];
  let themes = $state<GuideTheme[]>([]);

  $effect(() => onGuideTheme(() => (themes = guideThemes())));

  function scoped(theme: GuideTheme) {
    return (el: HTMLElement): void => paintScope(el, theme, themes);
  }
</script>

{#if themes.length === 0}
  <p class="sg-caption">waiting for the theme list</p>
{:else}
  <div class="sg-sw__themes">
    {#each themes as theme (theme.id)}
      <div class="sg-bct__tile" {@attach scoped(theme)}>
        <span class="sg-bc__label">{theme.name}</span>
        <div class="sg-sw__box" style:height="120px">
          <StatTile label="working now" figure="7" size="regular" mode="graph" tone="--oc-green" delta="up 2" meter={60} sub="of 12 alive">
            {#snippet spark()}<SparkLine points={POINTS} />{/snippet}
          </StatTile>
        </div>
        <div class="sg-sw__chart" style:height="140px">
          <div class="sg-sw__title">tokens</div>
          <div class="sg-sw__body">
            <ChartFrame size="panel" label="tokens">
              <div class="oc-chart-frame__headline"><strong>12.4m</strong><span>24 hours</span></div>
              <div class="oc-chart-frame__plot"><SparkLine points={POINTS} /></div>
            </ChartFrame>
          </div>
        </div>
      </div>
    {/each}
  </div>
{/if}
