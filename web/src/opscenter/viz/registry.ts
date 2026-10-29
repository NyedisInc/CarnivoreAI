import type { Component } from 'svelte';
import TimelineView from '../cells/analytics/TimelineView.svelte';
import type { ChartConfig, QueryBody } from '../cells/analytics/types';
import type { Tier } from './density';
import AgentsRenderer from './AgentsRenderer.svelte';
import { agentsPlan } from './agents';
import EventsRenderer from './EventsRenderer.svelte';
import FlowRenderer from './FlowRenderer.svelte';
import FleetRenderer from './FleetRenderer.svelte';
import { flowLevelsPlan } from './flow';
import HealthRenderer from './HealthRenderer.svelte';
import HeatRenderer from './HeatRenderer.svelte';
import HotRenderer from './HotRenderer.svelte';
import ImpactRenderer from './ImpactRenderer.svelte';
import KpiRenderer from './KpiRenderer.svelte';
import PackRenderer from './PackRenderer.svelte';
import LeaderboardRenderer from './LeaderboardRenderer.svelte';
import { heatPlan, kpiPlan, leaderboardPlan, runwayPlan, swimlanePlan, timelinePlan, treemapModelsPlan, type PlanContext } from './plan';
import RunwayRenderer from './RunwayRenderer.svelte';
import ScatterRenderer from './ScatterRenderer.svelte';
import SwimlanesRenderer from './SwimlanesRenderer.svelte';
import TreemapRenderer from './TreemapRenderer.svelte';
import VitalsRenderer from './VitalsRenderer.svelte';
import { VIZ_SPECS, type Viz, type VizSpec } from './specs';

export interface RendererProps { config: ChartConfig; instance: string; tier: Tier }

export interface VizEntry {
  component: Component<RendererProps>;
  spec: VizSpec;
  queries: (config: ChartConfig, ctx: PlanContext) => QueryBody[];
}

export const VIZ_REGISTRY: Readonly<Record<Viz, VizEntry>> = {
  timeline: { component: TimelineView as unknown as Component<RendererProps>, spec: VIZ_SPECS.timeline, queries: (config, ctx) => timelinePlan(config, ctx).all },
  kpi: { component: KpiRenderer as unknown as Component<RendererProps>, spec: VIZ_SPECS.kpi, queries: kpiPlan },
  leaderboard: { component: LeaderboardRenderer as unknown as Component<RendererProps>, spec: VIZ_SPECS.leaderboard, queries: leaderboardPlan },
  treemap: { component: TreemapRenderer as unknown as Component<RendererProps>, spec: VIZ_SPECS.treemap, queries: treemapModelsPlan },
  heat: { component: HeatRenderer as unknown as Component<RendererProps>, spec: VIZ_SPECS.heat, queries: heatPlan },
  vitals: { component: VitalsRenderer as unknown as Component<RendererProps>, spec: VIZ_SPECS.vitals, queries: () => [] },
  hot: { component: HotRenderer as unknown as Component<RendererProps>, spec: VIZ_SPECS.hot, queries: () => [] },
  events: { component: EventsRenderer as unknown as Component<RendererProps>, spec: VIZ_SPECS.events, queries: () => [] },
  fleet: { component: FleetRenderer as unknown as Component<RendererProps>, spec: VIZ_SPECS.fleet, queries: () => [] },
  runway: { component: RunwayRenderer as unknown as Component<RendererProps>, spec: VIZ_SPECS.runway, queries: runwayPlan },
  swimlanes: { component: SwimlanesRenderer as unknown as Component<RendererProps>, spec: VIZ_SPECS.swimlanes, queries: swimlanePlan },
  flow: { component: FlowRenderer as unknown as Component<RendererProps>, spec: VIZ_SPECS.flow, queries: flowLevelsPlan },
  scatter: { component: ScatterRenderer as unknown as Component<RendererProps>, spec: VIZ_SPECS.scatter, queries: () => [] },
  impact: { component: ImpactRenderer as unknown as Component<RendererProps>, spec: VIZ_SPECS.impact, queries: () => [] },
  health: { component: HealthRenderer as unknown as Component<RendererProps>, spec: VIZ_SPECS.health, queries: () => [] },
  agents: { component: AgentsRenderer as unknown as Component<RendererProps>, spec: VIZ_SPECS.agents, queries: agentsPlan },
  pack: { component: PackRenderer as unknown as Component<RendererProps>, spec: VIZ_SPECS.pack, queries: () => [] },
};
