import type { Component, Snippet } from 'svelte';
import { SvelteMap } from 'svelte/reactivity';

export type PanelReadState = 'ready' | 'loading' | 'failed';

export interface ProjectPanelProps {
  projectId: number;
  projectKey: string;
  header: Snippet<[number, PanelReadState]>;
  isFolded: (empty: boolean) => boolean;
  age: (iso: string | null) => string;
  previewOf: (total: number, expanded: boolean) => number;
}

export interface ProjectPanel {
  id: string;
  labelKey: string;
  hintKey?: string;
  component: Component<ProjectPanelProps>;
  enabled: () => boolean;
}

const panels = new SvelteMap<string, ProjectPanel>();

export function registerProjectPanel(panel: ProjectPanel): void {
  panels.set(panel.id, panel);
}

export function projectPanels(): ProjectPanel[] {
  return [...panels.values()].filter((panel) => panel.enabled());
}

export function resetProjectPanels(): void {
  panels.clear();
}
