
export interface FeatureChangeEntry {
  date: string;
  type: string;
  features: string[];
  summary: string;
  details?: string;
  issue?: number;
  pr?: number;
  breaking?: boolean;
  release?: string;
}

export interface FeatureCatalogEntry {
  id: string;
  name: string;
  [key: string]: unknown;
}

export interface FeaturesIndexResponse {
  available: boolean;
  areas: unknown[];
  catalog: FeatureCatalogEntry[];
  changes: FeatureChangeEntry[];
}

export interface FeatureLink {
  id: string;
  name: string;
}

export interface FeatureChangeLine {
  summary: string;
  details: string | null;
  type: string;
  date: string;
  featureNames: string[];
  featureLinks: FeatureLink[];
  pr: number | null;
  issue: number | null;
  breaking: boolean;
}

export interface FeatureTypeGroup {
  type: string;
  changes: FeatureChangeLine[];
}

export interface FeatureRelease {
  name: string;
  isUnreleased: boolean;
  date: string | null;
  types: FeatureTypeGroup[];
}

const TYPE_ORDER = ['added', 'changed', 'fixed', 'removed', 'deprecated', 'security'];

const UNRELEASED = 'Unreleased';

export function versionKey(name: string): number[] {
  const digits = name.match(/\d+/g);
  return digits ? digits.map(Number) : [0];
}

function compareVersionKeysDesc(a: number[], b: number[]): number {
  const len = Math.max(a.length, b.length);
  for (let i = 0; i < len; i++) {
    const diff = (b[i] ?? 0) - (a[i] ?? 0);
    if (diff !== 0) return diff;
  }
  return 0;
}

export function groupFeaturesByRelease(payload: FeaturesIndexResponse): FeatureRelease[] {
  const namesById = new Map(payload.catalog.map((entry) => [entry.id, entry.name]));
  const byRelease = new Map<string, FeatureChangeEntry[]>();
  for (const change of payload.changes) {
    if (change.type === 'internal') continue;
    const release = change.release ?? UNRELEASED;
    const bucket = byRelease.get(release);
    if (bucket) bucket.push(change);
    else byRelease.set(release, [change]);
  }

  const releaseNames = [...byRelease.keys()];
  const tagged = releaseNames
    .filter((name) => name !== UNRELEASED)
    .sort((a, b) => compareVersionKeysDesc(versionKey(a), versionKey(b)));
  const ordered = releaseNames.includes(UNRELEASED) ? [UNRELEASED, ...tagged] : tagged;

  return ordered.map((name) => {
    const entries = byRelease.get(name) ?? [];
    const types: FeatureTypeGroup[] = [];
    for (const type of TYPE_ORDER) {
      const matching = entries.filter((entry) => entry.type === type);
      if (matching.length === 0) continue;
      types.push({
        type,
        changes: matching
          .slice()
          .sort((a, b) => (a.date === b.date ? a.summary.localeCompare(b.summary) : a.date.localeCompare(b.date)))
          .map((entry) => {
            const links = entry.features
              .map((id) => {
                const name = namesById.get(id);
                return name ? { id, name } : null;
              })
              .filter((link): link is FeatureLink => link !== null);
            return {
              summary: entry.summary,
              details: typeof entry.details === 'string' && entry.details.length > 0 ? entry.details : null,
              type,
              date: entry.date,
              featureNames: links.map((link) => link.name),
              featureLinks: links,
              pr: typeof entry.pr === 'number' ? entry.pr : null,
              issue: typeof entry.issue === 'number' ? entry.issue : null,
              breaking: entry.breaking === true,
            };
          }),
      });
    }
    const dates = entries
      .filter((entry) => TYPE_ORDER.includes(entry.type) && entry.date)
      .map((entry) => entry.date)
      .sort();
    const date = dates.length > 0 ? (dates[dates.length - 1] ?? null) : null;
    return { name, isUnreleased: name === UNRELEASED, date, types };
  });
}
