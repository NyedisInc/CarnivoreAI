
export const INDEX_OK = {
  serial: 42,
  generated_at: '2026-09-30T06:00:00.000Z',
  as_of: '2026-09-30T06:00:00.000Z',
  degraded: false,
  stale: false,
  fetched_at: 1790751600,
  refusal: null,
};

function item(id: string, kind: string, name: string, publisher: string, latest: string, brief: string, installed: boolean): unknown {
  return {
    id,
    kind,
    name,
    publisher,
    latest,
    card: { brief },
    installed: installed
      ? { install_id: `inst-${id}`, scope: 'user', project_path: '', version: latest, update_available: false }
      : null,
    untrusted: false,
  };
}

export function catalogItems(): unknown[] {
  return [
    item('skill-code-review', 'skill', 'code-review', 'northwind labs', '1.4.0', 'reviews a diff for correctness bugs', true),
    item('skill-release-notes', 'skill', 'release-notes', 'northwind labs', '0.9.2', 'drafts release notes from merged work', true),
    item('skill-db-migrations', 'skill', 'db-migrations', 'harbor tools', '2.1.0', 'plans and checks schema migrations', false),
    item('skill-api-docs', 'skill', 'api-docs', 'harbor tools', '1.0.3', 'keeps api reference pages in step with routes', false),
    item('skill-incident-notes', 'skill', 'incident-notes', 'meridian ops', '0.3.1', 'writes up an incident timeline', false),
    item('plugin-session-export', 'plugin', 'session-export', 'northwind labs', '1.2.0', 'exports a session as markdown', true),
    item('plugin-cost-badge', 'plugin', 'cost-badge', 'meridian ops', '0.5.0', 'shows a running cost on each session card', false),
  ];
}

export function emptyCatalog(): unknown {
  return { index: INDEX_OK, items: [], untrusted: [] };
}

export function fullCatalog(): unknown {
  return { index: INDEX_OK, items: catalogItems(), untrusted: [] };
}
