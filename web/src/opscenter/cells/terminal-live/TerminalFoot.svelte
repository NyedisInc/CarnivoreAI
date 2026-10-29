<script lang="ts">
  import {
    sessionUsage,
    releaseSessionUsage,
    sessionUsageLabels,
    type UsageRow,
    type Resource,
    type SessionTokenUsage,
  } from '../../api';
  import { sessions } from '../../api';
  import { ledger } from '../../api/ledger.svelte';
  import { accountSwitch } from '../../../lib/account-switch/switch-store.svelte';
  import { footAccount } from './foot-account';
  import { rowFor } from '../terminal-viewer/meta';
  import ShellFoot from './ShellFoot.svelte';
  import FootWork from '../../../lib/background-work/FootWork.svelte';
  import FootGrown from './FootGrown.svelte';
  import type { ControlSection } from '../../../lib/session-control/control-center';
  import { splitFoot } from './foot-toolbar';
  import {
    FOOT_PRIORITY, admitted, coreVisible, footSpacing, maskAdmitByItems, planFoot, readMeasure,
    resolveFootBarCollapsedOption, DEFAULT_FOOT_BAR_COLLAPSED_OPTION,
    type CoreVisible, type FootBarCollapsedOption, type FootFeature, type FootMeasure, type WorkForm,
  } from './foot-plan';
  import { FOOT_PRIORITY_B, admittedB, planFootB, readMeasureB, type FootFeatureB, type FootMeasureB } from './foot-plan-b';
  import { FOOT_PRIORITY_C, admittedC, leadingScopeC, planFootC, readMeasureC, type FootFeatureC, type FootMeasureC, type LeadScope } from './foot-plan-c';
  import { footKindFor, footMarkPreset } from './foot-family';
  import { readFootBarItems, followFootBarItems } from './foot-bar-items';
  import { readFootBarOrder, followFootBarOrder } from './foot-bar-order';
  import { readFootBarLayout, followFootBarLayout } from './foot-bar-layout';
  import { growRoom, readFootExpanded, SPLIT_MIN_WIDTH, writeFootExpanded } from './foot-expand';
  import { resolveSessionControlOption, DEFAULT_SESSION_CONTROL_OPTION, type SessionControlOption }
    from '../../../lib/session-control/control-center';
  import { t } from '../../../lib/i18n/index.svelte';
  import FootMeters from './FootMeters.svelte';
  import { fillPct, type Admit } from './foot-meter-math';

  let {
    sessionId,
    width = 0,
    usage = undefined,
    collapsedOption = undefined,
    openOption = undefined,
  }: {
    sessionId: string;
    width?: number;
    usage?: SessionTokenUsage;
    collapsedOption?: FootBarCollapsedOption;
    openOption?: SessionControlOption;
  } = $props();
  let footBarLayout = $state(readFootBarLayout());
  $effect(() => followFootBarLayout((next) => { footBarLayout = next; }));
  const resolvedCollapsedOption = $derived(resolveFootBarCollapsedOption(collapsedOption ?? footBarLayout.collapsed));
  const resolvedOpenOption = $derived(resolveSessionControlOption(openOption ?? footBarLayout.open));

  const footKind = $derived(footKindFor(rowFor(sessions.data, sessionId)?.agent_family));
  const isShell = $derived(footKind === 'shell');
  const markPreset = $derived(footMarkPreset(rowFor(sessions.data, sessionId)?.agent_family));
  const noStats = $derived(footKind === 'none');

  /* the bottom bar */
  let expanded = $state(readFootExpanded());
  let focus = $state<ControlSection | null>(null);
  let room = $state(0);

  function openSection(section: ControlSection): void {
    if (expanded && focus === section) {
      setExpanded(false);
      return;
    }
    focus = section;
    setExpanded(true);
  }
  const regionId = $props.id();
  let slot = $state<HTMLDivElement | null>(null);

  function setExpanded(next: boolean): void {
    expanded = next;
    writeFootExpanded(next);
  }

  /* Escape inside the bar collapses it */
  function onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape' && expanded) {
      event.preventDefault();
      setExpanded(false);
    }
  }

  function keepTerminalFocus(event: MouseEvent): void {
    event.preventDefault();
  }

  $effect(() => {
    if (!expanded || !slot) return;
    const area = slot.closest<HTMLElement>('[data-foot-area]') ?? slot.parentElement;
    if (!area) return;
    const read = (): void => { room = growRoom(area.clientHeight); };
    read();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(read);
    observer.observe(area);
    return () => observer.disconnect();
  });

  $effect(() => {
    if (!expanded) return;
    const onPointerDown = (event: Event): void => {
      const target = event.target;
      if (slot && target instanceof Node && slot.contains(target)) return;
      setExpanded(false);
    };
    document.addEventListener('pointerdown', onPointerDown, true);
    return () => document.removeEventListener('pointerdown', onPointerDown, true);
  });

  let usageResource = $state<Resource<SessionTokenUsage> | null>(null);

  $effect(() => {
    const id = sessionId;
    if (!id || usage || isShell || noStats) {
      usageResource = null;
      return;
    }
    usageResource = sessionUsage(id);
    return () => releaseSessionUsage(id);
  });

  const payload = $derived(usage ?? (usageResource ? usageResource.data : null));
  const model = $derived(sessionUsageLabels(payload, null));

  const rowsByKey = $derived<Record<string, UsageRow>>(
    model.state === 'ok' ? Object.fromEntries(model.rows.map((r) => [r.key, r])) : {},
  );
  const context = $derived(model.state === 'ok' ? model.context : null);
  const windows = $derived(model.state === 'ok' ? model.windows : []);

  const hasEffort = $derived(typeof payload?.effort === 'string' && payload.effort.trim() !== '');

  let step = $state('');
  let workWidths = $state<Record<WorkForm, number>>({ full: 0, short: 0 });
  const ALL: Admit = Object.fromEntries(FOOT_PRIORITY.map((k) => [k, true])) as Admit;
  let measureEl = $state<HTMLDivElement | null>(null);
  let measured = $state<FootMeasure | null>(null);
  const footRow = $derived(rowFor(sessions.data, sessionId));
  const account = $derived(
    footAccount(footRow?.agent_family, footRow?.account_id, ledger.data?.accounts, accountSwitch.data?.active),
  );
  let accountW = $state(0);
  const planWidth = $derived(Math.max(1, width - (account ? accountW : 0)));
  const plan = $derived(planFoot(planWidth, measured));
  let labelsShortEl = $state<HTMLElement | null>(null);
  let labelsFullEl = $state<HTMLElement | null>(null);
  let labelWidths = $state<Record<'full' | 'short', number>>({ full: 0, short: 0 });
  let measureElB = $state<HTMLDivElement | null>(null);
  let measuredB = $state<FootMeasureB | null>(null);
  const planB = $derived(planFootB(planWidth, measuredB));
  let measureElC = $state<HTMLDivElement | null>(null);
  let measuredC = $state<FootMeasureC | null>(null);
  const planC = $derived(planFootC(planWidth, measuredC));
  const leadPct = $derived<Record<LeadScope, number | null>>({
    context: context ? fillPct(context) : null,
    fiveHour: windows.find((w) => w.key === 'window:five_hour') ? fillPct(windows.find((w) => w.key === 'window:five_hour')!) : null,
    sevenDay: windows.find((w) => w.key !== 'window:five_hour') ? fillPct(windows.find((w) => w.key !== 'window:five_hour')!) : null,
  });
  const leadScope = $derived(leadingScopeC(leadPct));
  const leadWindow = $derived(
    leadScope === 'fiveHour' ? windows.find((w) => w.key === 'window:five_hour')
      : leadScope === 'sevenDay' ? windows.find((w) => w.key !== 'window:five_hour')
      : undefined,
  );
  const activeWorkForm = $derived(
    resolvedCollapsedOption === 'b' ? (planB?.work ?? 'full')
      : resolvedCollapsedOption === 'c' ? (planC?.work ?? 'full')
      : (plan?.work ?? 'full'),
  );
  const workWidth = $derived(workWidths[activeWorkForm]);
  const stacked = $derived(width > 0 && width < SPLIT_MIN_WIDTH);
  const grownStyle = $derived(
    (stacked ? 'right:0;bottom:100%;' : 'right:0;')
      + `max-height:${room > 0 ? `${room}px` : 'min(50vh, 460px)'}`,
  );
  const split = $derived(splitFoot(Math.max(0, width - workWidth), step));
  $effect(() => { step = split.state; });

  /* and the three */
  let footBarItems = $state(readFootBarItems());
  $effect(() => followFootBarItems((next) => { footBarItems = next; }));
  let footBarOrder = $state(readFootBarOrder());
  $effect(() => followFootBarOrder((next) => { footBarOrder = next; }));
  const core = $derived(coreVisible(footBarItems));
  const adm = $derived(maskAdmitByItems(admitted(plan, split), footBarItems));
  const allMasked = $derived(maskAdmitByItems(ALL, footBarItems));

  /* there is nothing */
  function maskByItems<T extends Record<string, boolean>>(admit: T, modelKey: keyof T, effortKey: keyof T): T {
    const model = admit[modelKey] && footBarItems.model;
    return { ...admit, [modelKey]: model, [effortKey]: admit[effortKey] && footBarItems.effort && model };
  }
  const admB = $derived(maskByItems(admittedB(planB), 'model', 'effort'));
  const admC = $derived(maskByItems(admittedC(planC), 'model', 'effort'));
  const ALL_B: Record<FootFeatureB, boolean> = Object.fromEntries(FOOT_PRIORITY_B.map((k) => [k, true])) as Record<FootFeatureB, boolean>;
  const ALL_C: Record<FootFeatureC, boolean> = Object.fromEntries(FOOT_PRIORITY_C.map((k) => [k, true])) as Record<FootFeatureC, boolean>;
  const allMaskedB = $derived(maskByItems(ALL_B, 'model', 'effort'));
  const allMaskedC = $derived(maskByItems(ALL_C, 'model', 'effort'));

  const canMeasure = typeof ResizeObserver !== 'undefined';
  const measureContent = $derived(JSON.stringify(model));
  $effect(() => {
    void measureContent;
    const el = measureEl;
    const work = workWidths;
    const labels = labelWidths;
    if (!el) return;
    measured = readMeasure(el, work, labels);
    const observer = new ResizeObserver(() => { measured = readMeasure(el, work, labels); });
    observer.observe(el);
    return () => observer.disconnect();
  });
  $effect(() => {
    const full = labelsFullEl;
    const short = labelsShortEl;
    const report = (): void => { labelWidths = { full: full?.offsetWidth ?? 0, short: short?.offsetWidth ?? 0 }; };
    report();
    if (!full || !short || !canMeasure) return;
    const observer = new ResizeObserver(report);
    observer.observe(full);
    observer.observe(short);
    return () => observer.disconnect();
  });
  $effect(() => {
    const el = measureElB;
    const work = workWidths;
    if (!el) return;
    measuredB = readMeasureB(el, work);
    const observer = new ResizeObserver(() => { measuredB = readMeasureB(el, work); });
    observer.observe(el);
    return () => observer.disconnect();
  });
  $effect(() => {
    const el = measureElC;
    const work = workWidths;
    if (!el) return;
    measuredC = readMeasureC(el, work);
    const observer = new ResizeObserver(() => { measuredC = readMeasureC(el, work); });
    observer.observe(el);
    return () => observer.disconnect();
  });

  const spacing = $derived(footSpacing(width));
  const spacingStyle = $derived(`--oc-tf-lead:${spacing.leadPx}px;--oc-tf-bar-w:${spacing.barPx}px;--oc-tf-grp:${spacing.groupPx}px;--oc-tf-edge:${spacing.edgePx}px`);
  const edgeLiveStyle = $derived(
    resolvedCollapsedOption === 'a' && plan ? `${spacingStyle};--oc-tf-edge:${plan.edgePx}px` : spacingStyle,
  );
  const edgeMeasureStyle = $derived(`${spacingStyle};--oc-tf-edge:0px`);
</script>


{#if isShell}
<ShellFoot {sessionId} {width} />
{:else if !noStats}
<div class="oc-tf-slot" bind:this={slot} onkeydown={onKeydown} role="presentation">
  <div class="oc-tf-line" data-foot-bar>
  <button
    type="button"
    class="oc-tf"
    style={edgeLiveStyle}
    data-usage-state={model.state}
    aria-label={t('usage.foot.toggle')}
    aria-expanded={expanded ? 'true' : 'false'}
    aria-controls={regionId}
    onmousedown={keepTerminalFocus}
    onclick={() => setExpanded(!expanded)}
  >
    <FootMeters option={resolvedCollapsedOption} admit={resolvedCollapsedOption === 'b' ? admB : resolvedCollapsedOption === 'c' ? admC : adm} {core} {model} {payload} {context} {windows} {rowsByKey} {hasEffort}
      {markPreset} {footBarOrder} {leadScope} {leadWindow} /></button>
  <FootWork {sessionId} form={activeWorkForm} active={expanded ? focus : null}
    hideAgents={!footBarItems.agents} hideShells={!footBarItems.shells} hideTimers={!footBarItems.timers}
    onwidths={(w) => { workWidths = w; }} onopen={openSection} />
  {#if account}
    <span class="oc-tf-acct" bind:offsetWidth={accountW}>
      {#if account.mismatch}<span class="oc-tf-acct-warn" role="img" title={t('usage.foot.account.mismatch')}
        aria-label={t('usage.foot.account.mismatch')}><svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M12 3 2 20h20Z"/><path d="M12 10v5M12 18v.01"/></svg></span>{/if}
      <span class="oc-tf-acct-name">{account.name}</span>
    </span>
  {/if}
  </div>
  
  {#if canMeasure && resolvedCollapsedOption === 'b'}<div class="oc-tf oc-tf-measure" aria-hidden="true" style={spacingStyle}
    data-usage-state={model.state} bind:this={measureElB}><FootMeters option={'b'} admit={allMaskedB} {core} {model} {payload} {context} {windows} {rowsByKey} {hasEffort}
      {markPreset} {footBarOrder} {leadScope} {leadWindow} /></div>
  {:else if canMeasure && resolvedCollapsedOption === 'c'}<div class="oc-tf oc-tf-measure" aria-hidden="true" style={spacingStyle}
    data-usage-state={model.state} bind:this={measureElC}><FootMeters option={'c'} admit={allMaskedC} {core} {model} {payload} {context} {windows} {rowsByKey} {hasEffort}
      {markPreset} {footBarOrder} {leadScope} {leadWindow} /></div>
  {:else if canMeasure}<div class="oc-tf oc-tf-measure" aria-hidden="true" style={edgeMeasureStyle}
    data-usage-state={model.state} bind:this={measureEl}><FootMeters option={'a'} admit={allMasked} {core} {model} {payload} {context} {windows} {rowsByKey} {hasEffort}
      {markPreset} {footBarOrder} {leadScope} {leadWindow} /></div>
    
    <span class="oc-tf-label oc-tf-labels-measure" aria-hidden="true" bind:this={labelsShortEl}
      >{t('usage.context.short')}{#each windows as w (w.key)}{w.label}{/each}</span>
    <span class="oc-tf-label oc-tf-labels-measure" aria-hidden="true" bind:this={labelsFullEl}
      >{t('usage.context.title')}{#each windows as w (w.key)}{w.label}{/each}</span>
  {/if}
  <FootGrown {regionId} style={grownStyle} {stacked} {expanded} {model} {payload} {sessionId} {focus}
    openOption={resolvedOpenOption} onclose={() => setExpanded(false)} />
</div>
{/if}

<style>
  @layer components {
    .oc-tf {
      box-sizing: border-box;
      min-height: var(--oc-foot-h);
      display: flex;
      align-items: center;
      flex-wrap: nowrap;
      justify-content: flex-start;
      gap: 10px;
      padding: 3px var(--oc-space-3);
      background: var(--oc-ground-titlerow);
      border-top: 1px solid var(--oc-line-rule);
      font-size: var(--oc-fs-label);
      color: var(--oc-text-secondary);
      overflow: hidden;
      flex: 0 0 auto;
    }

    .oc-tf-slot {
      position: relative;
      flex: 0 0 auto;
      z-index: 5;
    }

    button.oc-tf {
      box-sizing: border-box;
      width: 100%;
      margin: 0;
      border: 0;
      border-top: 1px solid var(--oc-line-rule);
      border-radius: 0;
      font: inherit;
      font-size: var(--oc-fs-label);
      text-align: left;
      cursor: pointer;
      appearance: none;
    }

    .oc-tf-measure {
      position: absolute;
      left: 0;
      bottom: 0;
      width: max-content;
      visibility: hidden;
      pointer-events: none;
      border-top: 0;
    }

    .oc-tf-labels-measure {
      position: absolute;
      left: 0;
      bottom: 0;
      width: max-content;
      visibility: hidden;
      pointer-events: none;
      white-space: nowrap;
    }


    /* nothing at all */
    .oc-tf-line {
      display: flex;
      align-items: stretch;
      background: var(--oc-ground-titlerow);
      border-top: 1px solid var(--oc-line-rule);
    }

    .oc-tf-acct {
      display: flex;
      align-items: center;
      flex: 0 0 auto;
      gap: 5px;
      padding: 0 10px 0 0;
      font-size: var(--oc-fs-label);
      color: var(--oc-text-secondary);
      white-space: nowrap;
    }

    .oc-tf-acct-warn {
      display: inline-flex;
      color: var(--oc-yellow-bright);
    }

    .oc-tf-acct-warn svg {
      width: 1.1em;
      height: 1.1em;
      fill: none;
      stroke: currentColor;
      stroke-width: 1.6;
      stroke-linecap: round;
      stroke-linejoin: round;
    }

    .oc-tf-line > button.oc-tf {
      flex: 1 1 auto;
      min-width: 0;
      width: auto;
      background: transparent;
      border-top: 0;
    }

    .oc-tf-line > .oc-tf-acct {
      align-self: center;
    }

  }

  @layer components {
    .oc-tf-slot :global(.oc-tf-model),
    .oc-tf-slot :global(.oc-tf-lead) {
      gap: 5px;
    }

    .oc-tf-slot :global(.oc-tf-reset) {
      gap: 3px;
    }

    .oc-tf-slot :global(.oc-tf-caption) {
      font-size: 0.85em;
    }

    .oc-tf-slot :global(.oc-tf-grown) {
      box-shadow: 0 -6px 14px color-mix(in oklab, black 35%, transparent);
    }
  }
</style>
