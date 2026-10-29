
export interface PluginRow {
  id: string;
  name: string;
  description: string;
  version: string;
  author: string;
  tone?: 'link';
  demoColumns: readonly string[];
}

const DEMO = ['version', 'author'] as const;

export const plugins: PluginRow[] = [
  { id: 'chart-kit', name: 'Chart-Kit', description: 'Charts from tabular data', version: '2.2.0', author: 'example', demoColumns: DEMO },
  { id: 'pdf-notes', name: 'PDF-Notes', description: 'Annotate and export documents', version: '1.1.4', author: 'community', tone: 'link', demoColumns: DEMO },
  { id: 'ticket-bridge', name: 'Ticket-Bridge', description: 'Sync issues with a tracker', version: '0.8.0', author: 'community', demoColumns: DEMO },
  { id: 'lint-watch', name: 'Lint-Watch', description: 'Run linters on save', version: '3.4.1', author: 'core', demoColumns: DEMO },
  { id: 'snippet-box', name: 'Snippet-Box', description: 'Reusable prompt snippets', version: '1.0.0', author: 'example', demoColumns: DEMO },
  { id: 'calendar-sync', name: 'Calendar-Sync', description: 'Show events beside sessions', version: '0.5.2', author: 'community', demoColumns: DEMO },
  { id: 'theme-pack', name: 'Theme-Pack', description: 'Extra colour themes', version: '1.7.3', author: 'core', demoColumns: DEMO },
];
