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

export function tokenColors(host: HTMLElement, probe: HTMLElement): (css: string, fallback: string) => string {
  return (css, fallback) => {
    flatten ??= document.createElement('canvas').getContext('2d', { willReadFrequently: true }) as ColorContext;
    probe.style.color = '';
    probe.style.color = css;
    if (!probe.style.color) return fallback;
    return toSrgb(getComputedStyle(probe).color, flatten, fallback);
  };
}
