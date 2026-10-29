<script lang="ts">
  /*  hidden
 */
  import type { UsageRow, UsageWindowView, SessionTokenUsage, sessionUsageLabels } from '../../api';
  import ProviderMark from '../../../lib/byoai/ProviderMark.svelte';
  import { t } from '../../../lib/i18n/index.svelte';
  import Icon from '../../ui/Icon.svelte';
  import LimitGauge from '../../ui/LimitGauge.svelte';
  import { effortClass } from '../../../lib/effort/effort-level';
  import type { CoreVisible } from './foot-plan';
  import type { FootFeatureB } from './foot-plan-b';
  import type { FootFeatureC, LeadScope } from './foot-plan-c';
  import type { FootBarOrderId } from './foot-bar-order';
  import type { footMarkPreset } from './foot-family';
  import { fillPct, resetFeature, type Admit } from './foot-meter-math';

  type OkModel = Extract<ReturnType<typeof sessionUsageLabels>, { state: 'ok' }>;

  let {
    option,
    admit,
    core,
    model,
    payload,
    context,
    windows,
    rowsByKey,
    hasEffort,
    markPreset,
    footBarOrder,
    leadScope,
    leadWindow,
  }: {
    option: 'a' | 'b' | 'c';
    admit: Record<string, boolean>;
    core: CoreVisible;
    model: ReturnType<typeof sessionUsageLabels>;
    payload: SessionTokenUsage | null;
    context: OkModel['context'] | null;
    windows: OkModel['windows'];
    rowsByKey: Record<string, UsageRow>;
    hasEffort: boolean;
    markPreset: ReturnType<typeof footMarkPreset>;
    footBarOrder: readonly FootBarOrderId[];
    leadScope: LeadScope;
    leadWindow: UsageWindowView | undefined;
  } = $props();
</script>




{#snippet contextGroup(a: Admit)}
  {@const barShown = a.bars}
  <span class="oc-tf-meter" data-bar-hidden={barShown ? 'false' : 'true'}>
    <span class="oc-tf-label" data-scale={context?.scale ?? ''}
      >{t(a.fullLabels ? 'usage.context.title' : 'usage.context.short')}</span>
    {#if barShown}
      <span class="oc-tf-bar" data-fw="bars" data-scale={context?.scale ?? ''} role="img" aria-label={context?.meterText}>
        <span class="oc-tf-bar-fill" style={`width:${context ? fillPct(context) : 0}%`}></span>
      </span>
    {/if}
    {#if context?.percentText}<span class="oc-tf-num oc-tf-pct" data-scale={context.scale ?? ''}>{context.percentText}</span>{/if}
    {#if a.contextDetail && context?.compactDetail}<span class="oc-tf-num" data-fw="contextDetail">{context.compactDetail}</span>{/if}
  </span>
{/snippet}


{#snippet modelGroup(a: Admit)}
  {#if a.model && rowsByKey.model?.spans}
    <span class="oc-tf-model" data-fw="model">
      {#if markPreset}
        <span class="oc-tf-mark" data-fw="model-mark" data-mark={markPreset}><ProviderMark preset={markPreset} size={12} /></span>
      {/if}
      <span class="oc-tf-model-name" data-tier={rowsByKey.model.spans[0]?.tier ?? ''}
        >{rowsByKey.model.spans[0]?.text}</span>
      {#if a.effort && hasEffort && rowsByKey.model.spans.length > 2}
        <span class="oc-tf-effort {effortClass(payload?.effort)}" data-fw="effort" data-word={rowsByKey.model.spans[2]?.text}
          >{rowsByKey.model.spans[2]?.text}</span>
      {/if}
    </span>
  {/if}
{/snippet}


{#snippet windowGroup(w: UsageWindowView, a: Admit)}
  {@const barShown = a.bars}
  {@const reset = resetFeature(w)}
  <span class="oc-tf-meter" data-bar-hidden={barShown ? 'false' : 'true'}>
    <span class="oc-tf-label" data-scale={w.scale ?? ''}>{w.label}</span>
    {#if barShown}
      <span class="oc-tf-gauge" data-fw="bars">
        <LimitGauge variant="fill" pct={fillPct(w)} scale={w.scale} paceElapsedPct={w.paceElapsedPct} paceState={w.paceState} meterText={w.meterText} height={7} />
      </span>
    {/if}
    {#if w.percentText}<span class="oc-tf-num oc-tf-pct" data-scale={w.scale ?? ''}>{w.percentText}</span>{/if}
    {#if a[reset] && w.resetDuration}
      <span class="oc-tf-reset" data-fw={reset} title={w.resetAria} aria-label={w.resetAria}>
        <Icon name="recycle" size={11} />
        <span class="oc-tf-reset-text" aria-hidden="true">{w.resetDuration}</span>
      </span>
    {/if}
  </span>
{/snippet}

{#snippet groups(a: Admit, core: CoreVisible)}
  {#if model.state === 'ok'}
    {@render modelGroup(a)}
    <span class="oc-tf-meters">
      {#each footBarOrder as id (id)}
        {#if id === 'context'}
          {#if core.context}{@render contextGroup(a)}{/if}
        {:else}
          {#each windows as w (w.key)}
            {#if (w.key === 'window:five_hour') === (id === 'window_5h') && (id === 'window_5h' ? core.window5h : core.window7d)}
              {@render windowGroup(w, a)}
            {/if}
          {/each}
        {/if}
      {/each}
    </span>
  {:else}
    
    <span class="oc-tf-bar oc-tf-bar-placeholder" data-usage-state={model.state} role="img" aria-label={t('terminal.context.unmeasured')}></span>
    <span class="oc-tf-bar oc-tf-bar-placeholder" data-usage-state={model.state} role="img" aria-label="5h window, unmeasured"></span>
    <span class="oc-tf-bar oc-tf-bar-placeholder" data-usage-state={model.state} role="img" aria-label="7d window, unmeasured"></span>
    <span class="oc-tf-state" data-usage-state={model.state}>{model.message}</span>
  {/if}
{/snippet}


{#snippet groupsB(a: Record<FootFeatureB, boolean>, core: CoreVisible)}
  {#if model.state === 'ok'}
    {@render modelGroup(a as unknown as Admit)}
    {#if core.context}
      <span class="oc-tf-scope">
        {#if a.captions}<span class="oc-tf-caption" data-fw="captions">{t('usage.footb.scope.session')}</span>{/if}
        <span class="oc-tf-label" data-scale={context?.scale ?? ''}>{t('usage.context.short')}</span>
        {#if context?.percentText}<span class="oc-tf-num oc-tf-pct" data-scale={context.scale ?? ''}>{context.percentText}</span>{/if}
        {#if a.ctxFraction && context?.compactDetail}<span class="oc-tf-num" data-fw="ctxFraction">{context.compactDetail}</span>{/if}
      </span>
    {/if}
    {#if core.window5h || core.window7d}
      <span class="oc-tf-scope">
        {#if a.captions}<span class="oc-tf-caption" data-fw="captions">{t('usage.footb.scope.account')}</span>{/if}
        {#each windows as w (w.key)}
          {@const isFiveH = w.key === 'window:five_hour'}
          {#if isFiveH ? core.window5h : core.window7d}
            <span class="oc-tf-label" data-scale={w.scale ?? ''}>{w.label}</span>
            {#if w.percentText}<span class="oc-tf-num oc-tf-pct" data-scale={w.scale ?? ''}>{w.percentText}</span>{/if}
            {#if a[isFiveH ? 'fiveHReset' : 'sevenDReset'] && w.resetDuration}
              <span class="oc-tf-reset" data-fw={isFiveH ? 'fiveHReset' : 'sevenDReset'} title={w.resetAria} aria-label={w.resetAria}>
                <Icon name="recycle" size={11} />
                <span class="oc-tf-reset-text" aria-hidden="true">{w.resetDuration}</span>
              </span>
            {/if}
          {/if}
        {/each}
      </span>
    {/if}
  {:else}
    <span class="oc-tf-state" data-usage-state={model.state}>{model.message}</span>
  {/if}
{/snippet}


{#snippet groupsC(a: Record<FootFeatureC, boolean>)}
  {#if model.state === 'ok'}
    {@const leadPercentText = leadScope === 'context' ? context?.percentText : leadWindow?.percentText}
    {@const leadScaleValue = leadScope === 'context' ? context?.scale : leadWindow?.scale}
    {@const leadMeterText = leadScope === 'context' ? context?.meterText : leadWindow?.meterText}
    <span class="oc-tf-lead" data-scale={leadScaleValue ?? ''}>
      <span class="oc-tf-dot" data-scale={leadScaleValue ?? ''} aria-hidden="true"></span>
      {#if a.leadBar}
        {#if leadScope === 'context'}
          <span class="oc-tf-bar" data-fw="leadBar" data-scale={leadScaleValue ?? ''} role="img" aria-label={leadMeterText}>
            <span class="oc-tf-bar-fill" style={`width:${context ? fillPct(context) : 0}%`}></span>
          </span>
        {:else}
          <span class="oc-tf-gauge" data-fw="leadBar">
            <LimitGauge variant="fill" pct={leadWindow ? fillPct(leadWindow) : 0} scale={leadWindow?.scale ?? null} paceElapsedPct={leadWindow?.paceElapsedPct ?? null} paceState={leadWindow?.paceState ?? null} meterText={leadMeterText ?? ''} height={7} />
          </span>
        {/if}
      {/if}
      {#if leadPercentText}<span class="oc-tf-num oc-tf-pct" data-scale={leadScaleValue ?? ''}>{leadPercentText}</span>{/if}
      {#if a.leadReset && leadScope !== 'context' && leadWindow?.resetDuration}
        <span class="oc-tf-reset" data-fw="leadReset" title={leadWindow.resetAria} aria-label={leadWindow.resetAria}>
          <Icon name="recycle" size={11} />
          <span class="oc-tf-reset-text" aria-hidden="true">{leadWindow.resetDuration}</span>
        </span>
      {/if}
    </span>
    <span class="oc-tf-dim-nums">
      {#if leadScope !== 'context' && context?.percentText}<span class="oc-tf-num oc-tf-dim">{t('usage.context.short')} {context.percentText}</span>{/if}
      {#each windows as w (w.key)}
        {#if w !== leadWindow && w.percentText}<span class="oc-tf-num oc-tf-dim">{w.label} {w.percentText}</span>{/if}
      {/each}
    </span>
    {@render modelGroup(a as unknown as Admit)}
  {:else}
    <span class="oc-tf-state" data-usage-state={model.state}>{model.message}</span>
  {/if}
{/snippet}

{#if option === 'b'}{@render groupsB(admit as Record<FootFeatureB, boolean>, core)}
{:else if option === 'c'}{@render groupsC(admit as Record<FootFeatureC, boolean>)}
{:else}{@render groups(admit as Admit, core)}{/if}

<style>
  @layer components {
    /* min-width: 0 */
    .oc-tf-meter {
      display: flex;
      align-items: center;
      gap: var(--oc-space-1);
      flex: 0 0 auto;
    }

    .oc-tf-label {
      color: var(--oc-text-bright);
      white-space: nowrap;
      flex: 0 0 auto;
    }

    /* min-width: 14px */
    .oc-tf-bar {
      position: relative;
      display: inline-block;
      flex: 1 1 14px;
      min-width: 14px;
      max-width: 160px;
      height: 6px;
      border-radius: 3px;
      background: var(--oc-ground-hover);
      box-shadow: inset 0 0 0 1px var(--oc-line-frame);
      overflow: hidden;
    }

    .oc-tf-gauge {
      display: flex;
      flex: 1 1 14px;
      min-width: 14px;
      max-width: 160px;
    }

    .oc-tf-bar-fill {
      position: absolute;
      inset: 0 auto 0 0;
      height: 100%;
      border-radius: inherit;
      background: var(--oc-text-dim);
    }

    .oc-tf-bar[data-scale='1'] .oc-tf-bar-fill { background: var(--oc-green-bright); }

    .oc-tf-bar[data-scale='2'] .oc-tf-bar-fill { background: var(--oc-cyan); }

    .oc-tf-bar[data-scale='3'] .oc-tf-bar-fill { background: var(--oc-yellow-bright); }

    .oc-tf-bar[data-scale='4'] .oc-tf-bar-fill { background: color-mix(in oklab, var(--oc-yellow-bright) 55%, var(--oc-coral)); }

    .oc-tf-bar[data-scale='5'] .oc-tf-bar-fill { background: var(--oc-coral); }

    .oc-tf-bar-placeholder[data-usage-state='absent'] {
      background: transparent;
      box-shadow: inset 0 0 0 1px var(--oc-line-rule);
    }

    .oc-tf-bar-placeholder[data-usage-state='unchecked'] {
      background-image: repeating-linear-gradient(
        135deg,
        var(--oc-yellow) 0 2px,
        transparent 2px 5px
      );
      background-color: transparent;
      box-shadow: inset 0 0 0 1px var(--oc-line-rule);
      opacity: 0.7;
    }

    .oc-tf-state {
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      min-width: 0;
    }

    .oc-tf-state[data-usage-state='absent'] { color: var(--oc-text-dim); }

    .oc-tf-state[data-usage-state='unchecked'] { color: var(--oc-yellow); }

    /* flex: 0 0 auto flex: 1 1 auto margin-left: auto */
    .oc-tf-model {
      display: flex;
      align-items: baseline;
      flex: 0 0 auto;
    }

    .oc-tf-mark { display: inline-flex; align-self: center; }

    .oc-tf-model-name {
      white-space: nowrap;
      color: var(--oc-text-primary);
    }

    .oc-tf-model-name[data-tier='1'] { color: var(--oc-green-bright); }

    .oc-tf-model-name[data-tier='2'] { color: var(--oc-cyan); }

    .oc-tf-model-name[data-tier='3'] { color: var(--oc-yellow-bright); }

    .oc-tf-model-name[data-tier='4'] { color: color-mix(in oklab, var(--oc-yellow-bright) 55%, var(--oc-coral)); }

    .oc-tf-model-name[data-tier='5'] { color: var(--oc-coral); }

    .oc-tf-effort::before {
      content: '\00b7\0020';
      color: var(--oc-text-dim);
    }

    .oc-tf-effort {
      white-space: nowrap;
    }

    .oc-tf-effort:not(:global(.effort-level)) {
      color: var(--oc-text-dim);
    }

    .oc-tf-num {
      color: var(--oc-text-secondary);
      white-space: nowrap;
      flex: 0 0 auto;
    }

    .oc-tf-reset {
      display: inline-flex;
      align-items: center;
      color: var(--oc-text-dim);
      white-space: nowrap;
      flex: 0 0 auto;
    }

    .oc-tf-reset :global(svg) {
      flex: 0 0 auto;
      opacity: 0.85;
    }

    /* OPTION A: THE THREE LIMITS ARE ONE CENTERED GROUP AGAIN (the team
       (acme), an earlier date, restoring the layout of 92622de3, an earlier date
       15:24: "center the three and put enough space between them with a
       little divider", "Make all of them even progress bar size"; reverses
       the left-packing of c0925ead, `docs/DECISIONS.md`, an earlier date). The
       model stays leftmost and the work segments on the right (the owner's
       ordering); the auto margins put the meters in the middle of the free
       width between them. Each pair of PRESENT meters is a 28px gap plus 28px
       of padding with a hairline 9px into the padding, the same weight as the
       work segments' own hairline; `+` takes a missing window's divider with
       it for free. Every bar is one fixed 112px (was 64pxlonger bars, more space
       between the groups), so what the measuring copy
       reads is what is drawn. */
    .oc-tf-meters {
      display: flex;
      align-items: center;
      justify-content: center;
      flex: 0 0 auto;
      gap: var(--oc-tf-grp, 28px);
      margin-inline: auto;
      padding-inline: var(--oc-tf-edge, 0px);
    }

    .oc-tf-meters > .oc-tf-meter + .oc-tf-meter {
      position: relative;
      padding-left: var(--oc-tf-grp, 28px);
    }

    .oc-tf-meters > .oc-tf-meter + .oc-tf-meter::before {
      content: '';
      position: absolute;
      left: calc(var(--oc-tf-grp, 28px) * 9 / 28);
      top: 50%;
      transform: translateY(-50%);
      width: 1px;
      height: 11px;
      background: var(--oc-line-rule);
    }

    .oc-tf-meters .oc-tf-bar {
      flex: 0 0 112px;
      min-width: 112px;
      max-width: 112px;
      height: 7px;
    }

    .oc-tf-meters .oc-tf-gauge {
      flex: 0 0 112px;
      min-width: 112px;
      max-width: 112px;
    }

    .oc-tf-gauge .oc-gauge__pace {
      top: 0;
      bottom: 0;
    }

    .oc-tf-pct[data-scale='1'] { color: var(--oc-green-bright); }

    .oc-tf-pct[data-scale='2'] { color: var(--oc-cyan); }

    .oc-tf-pct[data-scale='3'] { color: var(--oc-yellow-bright); }

    .oc-tf-pct[data-scale='4'] { color: color-mix(in oklab, var(--oc-yellow-bright) 55%, var(--oc-coral)); }

    .oc-tf-pct[data-scale='5'] { color: var(--oc-coral); }


    .oc-tf-scope {
      display: flex;
      align-items: center;
      gap: var(--oc-space-1-5);
      flex: 0 0 auto;
    }

    .oc-tf-scope + .oc-tf-scope {
      position: relative;
      padding-left: var(--oc-tf-lead, var(--oc-space-5));
    }

    .oc-tf-scope + .oc-tf-scope::before {
      content: '';
      position: absolute;
      left: calc(var(--oc-tf-lead, 24px) / 2);
      top: 50%;
      transform: translateY(-50%);
      width: 1px;
      height: 11px;
      background: var(--oc-line-rule);
    }

    .oc-tf-caption {
      color: var(--oc-text-dim);
      text-transform: uppercase;
      letter-spacing: 0.06em;
      white-space: nowrap;
      flex: 0 0 auto;
    }

    .oc-tf-lead {
      display: flex;
      align-items: center;
      flex: 0 0 auto;
    }

    .oc-tf-dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      flex: 0 0 auto;
      background: var(--oc-text-dim);
    }

    .oc-tf-dot[data-scale='1'] { background: var(--oc-green-bright); }

    .oc-tf-dot[data-scale='2'] { background: var(--oc-cyan); }

    .oc-tf-dot[data-scale='3'] { background: var(--oc-yellow-bright); }

    .oc-tf-dot[data-scale='4'] { background: color-mix(in oklab, var(--oc-yellow-bright) 55%, var(--oc-coral)); }

    .oc-tf-dot[data-scale='5'] { background: var(--oc-coral); }

    .oc-tf-lead .oc-tf-bar {
      flex: 0 0 var(--oc-tf-bar-w, 64px);
      min-width: var(--oc-tf-bar-w, 64px);
      max-width: var(--oc-tf-bar-w, 64px);
      height: 7px;
    }

    .oc-tf-lead .oc-tf-gauge {
      flex: 0 0 var(--oc-tf-bar-w, 64px);
      min-width: var(--oc-tf-bar-w, 64px);
      max-width: var(--oc-tf-bar-w, 64px);
    }

    .oc-tf-dim-nums {
      display: flex;
      align-items: center;
      gap: var(--oc-tf-lead, var(--oc-space-5));
      flex: 0 0 auto;
      padding-left: var(--oc-tf-lead, var(--oc-space-5));
    }

    .oc-tf-num.oc-tf-dim {
      color: var(--oc-text-dim);
    }
  }
</style>
