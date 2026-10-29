
export interface ProjectRow {
  id: string;
  name: string;
  underline?: boolean;
  type: string;
  updatedMinutes: number;
  sessions: number;
  path: string;
  demoColumns: readonly string[];
}

const DEMO = ['sessions', 'path'] as const;

export const projects: ProjectRow[] = [
  { id: 'cloudecode', name: 'cloudecode', type: 'Project', updatedMinutes: 2, sessions: 4, path: '~/Dev/cloudecode', demoColumns: DEMO },
  { id: 'insiders', name: 'Lantern App', type: 'Project', updatedMinutes: 60, sessions: 2, path: '~/Dev/lantern-app', demoColumns: DEMO },
  { id: 'newui', name: 'cloudecode-newui', type: 'Project', updatedMinutes: 180, sessions: 3, path: '~/Dev/cloudecode-newui', demoColumns: DEMO },
  { id: 'riverbed', name: 'Riverbed', type: 'Project', updatedMinutes: 300, sessions: 1, path: '~/Dev/riverbed', demoColumns: DEMO },
  { id: 'codex', name: 'cloudecode-codex', type: 'Project', updatedMinutes: 1440, sessions: 1, path: '~/Dev/cloudecode-codex', demoColumns: DEMO },
  { id: 'mailsorter', name: 'mailSorter', underline: true, type: 'Project', updatedMinutes: 2880, sessions: 0, path: '~/Dev/mail-sorter', demoColumns: DEMO },
];
