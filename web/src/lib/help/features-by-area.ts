
import type { FeatureChangeEntry } from './features-grouping';

export interface FeatureMediaItem {
  kind: 'screenshot' | 'gif' | 'icon';
  file: string;
  alt: string;
  caption?: string;
  theme?: string;
  state?: string;
}

export interface FeatureCatalogItem {
  id: string;
  name: string;
  summary: string;
  area: string;
  status: string;
  where?: string[];
  how_to?: string[];
  examples?: string[];
  media?: FeatureMediaItem[];
  media_exempt?: string;
}

export interface FeatureAreaMeta {
  id: string;
  name: string;
  blurb?: string;
}

export interface FeatureCatalogPayload {
  available: boolean;
  areas: FeatureAreaMeta[];
  catalog: FeatureCatalogItem[];
  changes: FeatureChangeEntry[];
}

export interface FeatureAreaGroup {
  id: string;
  name: string;
  features: FeatureCatalogItem[];
}

const HIDDEN_STATUSES = new Set(['removed']);

export function groupFeaturesByArea(payload: FeatureCatalogPayload): FeatureAreaGroup[] {
  const visible = payload.catalog.filter((entry) => !HIDDEN_STATUSES.has(entry.status));
  const byArea = new Map<string, FeatureCatalogItem[]>();
  for (const entry of visible) {
    const bucket = byArea.get(entry.area);
    if (bucket) bucket.push(entry);
    else byArea.set(entry.area, [entry]);
  }

  const known = payload.areas.filter((area) => byArea.has(area.id));
  const knownIds = new Set(known.map((area) => area.id));
  const unknown = [...byArea.keys()].filter((id) => !knownIds.has(id)).sort();

  const ordered: FeatureAreaGroup[] = known.map((area) => ({
    id: area.id,
    name: area.name,
    features: (byArea.get(area.id) ?? []).slice().sort((a, b) => a.name.localeCompare(b.name)),
  }));
  for (const id of unknown) {
    ordered.push({
      id,
      name: id,
      features: (byArea.get(id) ?? []).slice().sort((a, b) => a.name.localeCompare(b.name)),
    });
  }
  return ordered;
}

export function findFeature(groups: FeatureAreaGroup[], id: string): FeatureCatalogItem | null {
  for (const group of groups) {
    const found = group.features.find((f) => f.id === id);
    if (found) return found;
  }
  return null;
}
