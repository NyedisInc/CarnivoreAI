import { loadECharts, type EChartsType } from './echarts-loader';
import { toSrgb, type ColorContext } from '../cells/analytics/series-colors';

export interface OpenChart { chart: EChartsType; dispose: () => void }

export function openChart(node: HTMLElement, redraw: () => void): OpenChart {
  let real: EChartsType | null = null;
  let disposed = false;
  let lastOption: unknown[] | null = null;
  const queuedListeners: Array<unknown[]> = [];

  const proxy = {
    setOption(...args: unknown[]) {
      if (real) return (real.setOption as (...a: unknown[]) => unknown)(...args);
      lastOption = args;
    },
    clear() {
      if (real) return real.clear();
      lastOption = null;
    },
    resize(...args: unknown[]) {
      if (real) return (real.resize as (...a: unknown[]) => unknown)(...args);
    },
    on(...args: unknown[]) {
      if (real) return (real.on as (...a: unknown[]) => unknown)(...args);
      queuedListeners.push(args);
    },
    off(...args: unknown[]) {
      if (real) return (real.off as (...a: unknown[]) => unknown)(...args);
    },
    dispatchAction(...args: unknown[]) {
      if (real) return (real.dispatchAction as (...a: unknown[]) => unknown)(...args);
    },
    dispose() {
      disposed = true;
      real?.dispose();
      real = null;
    },
  } as unknown as EChartsType;

  const resize = new ResizeObserver(() => {
    if (!real) return;
    real.resize();
    redraw();
  });
  resize.observe(node);
  const theme = new MutationObserver(() => { if (real) redraw(); });
  theme.observe(document.documentElement, { attributes: true, attributeFilter: ['class', 'data-theme'] });

  void loadECharts().then(({ init }) => {
    if (disposed || !node.isConnected) return;
    real = init(node, undefined, { renderer: 'canvas' });
    for (const args of queuedListeners) (real.on as (...a: unknown[]) => unknown)(...args);
    queuedListeners.length = 0;
    if (lastOption) {
      (real.setOption as (...a: unknown[]) => unknown)(...lastOption);
      lastOption = null;
    } else {
      redraw();
    }
    real.resize();
  });

  return {
    chart: proxy,
    dispose: () => {
      disposed = true;
      resize.disconnect();
      theme.disconnect();
      real?.dispose();
      real = null;
    },
  };
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
