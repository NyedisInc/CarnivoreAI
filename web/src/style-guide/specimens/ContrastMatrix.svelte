<script lang="ts">
  /*  hidden  */
  import {
    EXTRA_PAIRS,
    GROUND_ROLES,
    TEXT_ROLES,
    contrastRatio,
    summarize,
    verdict,
    type Measured,
    type ThemeSummary,
  } from '../contrast';
  import { colorReader, guideThemes, onGuideTheme, paintScope, type GuideTheme } from '../theme-scope';

  interface ThemeReport {
    theme: GuideTheme;
    rows: Measured[];
    summary: ThemeSummary;
  }

  const UNDER = '--oc-surface-base';

  let reports = $state<ThemeReport[]>([]);
  let picked = $state<string | null>(null);
  let probe = $state<HTMLDivElement | null>(null);
  let detailScope = $state<HTMLDivElement | null>(null);

  const detail = $derived(reports.find((r) => r.theme.id === picked) ?? reports[0] ?? null);

  function measure(scope: HTMLElement): Measured[] {
    const reader = colorReader();
    const out: Measured[] = [];
    const push = (fg: string, bg: string, kind: Measured['kind'], resting: boolean, min: number): void => {
      const ground = reader.composite(scope, bg === UNDER ? [UNDER] : [UNDER, bg]);
      const ink = reader.composite(scope, bg === UNDER ? [UNDER, fg] : [UNDER, bg, fg]);
      if (!ground || !ink) return;
      const ratio = contrastRatio(ink, ground);
      out.push({ fg, bg, kind, resting, min, ratio, verdict: verdict(ratio, kind, min) });
    };
    for (const fg of TEXT_ROLES) for (const bg of GROUND_ROLES) push(fg.token, bg.token, 'text', bg.resting, 4.5);
    for (const p of EXTRA_PAIRS) push(p.fg.token, p.bg.token, p.kind, p.bg.resting, p.min);
    return out;
  }

  function measureAll(): void {
    if (!probe) return;
    const themes = guideThemes();
    reports = themes.map((theme) => {
      paintScope(probe!, theme, themes);
      const rows = measure(probe!);
      return { theme, rows, summary: summarize(rows) };
    });
  }

  $effect(() => {
    if (!probe) return;
    return onGuideTheme((id) => {
      measureAll();
      picked = id;
    });
  });

  $effect(() => {
    if (detailScope && detail) paintScope(detailScope, detail.theme, reports.map((r) => r.theme));
  });

  function labelOf(token: string): string {
    const all = [...TEXT_ROLES, ...GROUND_ROLES, ...EXTRA_PAIRS.flatMap((p) => [p.fg, p.bg])];
    return all.find((r) => r.token === token)?.label ?? token;
  }

  function cell(fg: string, bg: string): Measured | undefined {
    return detail?.rows.find((r) => r.fg === fg && r.bg === bg && r.kind === 'text');
  }
</script>

<div class="sg-cm-probe" bind:this={probe} aria-hidden="true"></div>

{#if reports.length === 0}
  <p class="sg-caption">waiting for the theme list</p>
{:else}
  <div class="sg-table-wrap">
    <table class="sg-table sg-cm-summary">
      <thead>
        <tr><th>theme</th><th>fails on resting grounds</th><th>fails anywhere</th><th>worst pair (ratio / floor)</th></tr>
      </thead>
      <tbody>
        {#each reports as r (r.theme.id)}
          <tr data-verdict={r.summary.failsResting > 0 ? 'fail' : r.summary.failsAll > 0 ? 'large' : 'pass'} aria-current={r.theme.id === detail?.theme.id ? 'true' : undefined}>
            <td>
              <button type="button" class="oc-btn oc-btn--ghost oc-btn--sm" onclick={() => (picked = r.theme.id)}>{r.theme.name}</button>
            </td>
            <td class="sg-cm-count sg-cm-count--resting">{r.summary.failsResting}</td>
            <td class="sg-cm-count">{r.summary.failsAll} of {r.summary.measured}</td>
            <td>
              {#if r.summary.worst}
                {labelOf(r.summary.worst.fg)} on {labelOf(r.summary.worst.bg)}: {r.summary.worst.ratio} / {r.summary.worst.min}
              {/if}
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>

  {#if detail}
    <h4 class="sg-cm-title">{detail.theme.name}: every text role on every ground</h4>
    <div class="sg-cm-scope" bind:this={detailScope}>
      <div class="sg-table-wrap">
        <table class="sg-cm-matrix">
          <thead>
            <tr>
              <th scope="col">text role</th>
              {#each GROUND_ROLES as g (g.token)}<th scope="col">{g.label}{g.resting ? '' : ' *'}</th>{/each}
            </tr>
          </thead>
          <tbody>
            {#each TEXT_ROLES as fg (fg.token)}
              <tr>
                <th scope="row">{fg.label}</th>
                {#each GROUND_ROLES as g (g.token)}
                  {@const m = cell(fg.token, g.token)}
                  <td data-verdict={m?.verdict}>
                    <span class="sg-cm-sample" style:background={`var(${g.token})`} style:color={`var(${fg.token})`}>Aa {m?.ratio ?? ''}</span>
                    {#if m && m.verdict !== 'pass'}<span class="sg-cm-flag">{m.verdict === 'large' ? 'large only' : 'fail'}</span>{/if}
                  </td>
                {/each}
              </tr>
            {/each}
          </tbody>
        </table>
      </div>

      <div class="sg-table-wrap">
        <table class="sg-cm-matrix">
          <thead><tr><th scope="col">pair</th><th scope="col">on</th><th scope="col">kind</th><th scope="col">ratio</th><th scope="col">floor</th></tr></thead>
          <tbody>
            {#each EXTRA_PAIRS as p (p.fg.token + p.bg.token)}
              {@const m = detail.rows.find((r) => r.fg === p.fg.token && r.bg === p.bg.token)}
              <tr>
                <th scope="row">{p.fg.label}</th>
                <td>{p.bg.label}</td>
                <td>{p.kind}</td>
                <td data-verdict={m?.verdict}>
                  <span class="sg-cm-sample" style:background={`var(${p.bg.token})`} style:color={`var(${p.fg.token})`}
                    >{#if p.kind === 'boundary' || p.kind === 'decorative' || p.kind === 'step'}<span class="sg-cm-bar" style:background={`var(${p.fg.token})`}></span>{:else}Aa{/if} {m?.ratio ?? ''}</span>
                  {#if m && m.verdict !== 'pass' && m.verdict !== 'info'}<span class="sg-cm-flag">{m.verdict === 'large' ? 'large only' : 'fail'}</span>{/if}
                </td>
                <td>{p.min > 0 ? p.min + ':1' : 'none'}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>
  {/if}
{/if}
