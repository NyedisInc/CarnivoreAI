import type { EChartsType } from 'echarts/core';

export interface EChartsRuntime {
  init: typeof import('echarts/core').init;
}

let cached: Promise<EChartsRuntime> | null = null;

export function loadECharts(): Promise<EChartsRuntime> {
  cached ??= Promise.all([
    import('echarts/core'),
    import('echarts/charts'),
    import('echarts/components'),
    import('echarts/renderers'),
  ]).then(([core, charts, components, renderers]) => {
    core.use([
      charts.LineChart,
      charts.BarChart,
      charts.CustomChart,
      charts.HeatmapChart,
      charts.SankeyChart,
      charts.ScatterChart,
      charts.TreemapChart,
      components.GridComponent,
      components.LegendComponent,
      components.LegendScrollComponent,
      components.TooltipComponent,
      components.DataZoomComponent,
      components.MarkLineComponent,
      components.MarkAreaComponent,
      renderers.CanvasRenderer,
    ]);
    return { init: core.init };
  });
  return cached;
}

export type { EChartsType };
