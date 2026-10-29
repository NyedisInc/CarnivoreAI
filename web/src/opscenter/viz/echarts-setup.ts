import { init, use, type EChartsType } from 'echarts/core';
import { CustomChart, HeatmapChart, SankeyChart, ScatterChart, TreemapChart } from 'echarts/charts';
import { GridComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { toSrgb, type ColorContext } from '../cells/analytics/series-colors';

use([CustomChart, HeatmapChart, SankeyChart, ScatterChart, TreemapChart, GridComponent, TooltipComponent, CanvasRenderer]);

export interface OpenChart { chart: EChartsType; dispose: () => void }

export function openChart(node: HTMLElement, redraw: () => void): OpenChart {
  const chart = init(node, undefined, { renderer: 'canvas' });
  const resize = new ResizeObserver(() => { chart.resize(); redraw(); });
  resize.observe(node);
  const theme = new MutationObserver(redraw);
  theme.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'data-theme'] });
  return { chart, dispose: () => { resize.disconnect(); theme.disconnect(); chart.dispose(); } };
}

let flatten: ColorContext | null = null;

/**
 * Resolve theme colours at draw time, so a theme switch (and a per-session theme) is honoured.
 * Inputs: host - a node inside the themed subtree; probe - a hidden element in that same subtree.
 * Output: `color(css, fallback)` giving an `rgb()` string for any CSS colour expression, for example
 *   `var(--oc-series-2)` or `color-mix(in oklab, var(--oc-series-5) 40%, var(--oc-ground-panel))`.
 */
export function tokenColors(host: HTMLElement, probe: HTMLElement): (css: string, fallback: string) => string {
  return (css, fallback) => {
    flatten ??= document.createElement('canvas').getContext('2d', { willReadFrequently: true }) as ColorContext;
    probe.style.color = '';
    probe.style.color = css;
    if (!probe.style.color) return fallback;
    return toSrgb(getComputedStyle(probe).color, flatten, fallback);
  };
}
