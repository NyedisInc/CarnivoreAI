
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
  { id: 'rfp-agent', name: 'RFP-Agent', description: 'Automate RFP analysis', version: '1.4.0', author: 'nyedis', tone: 'link', demoColumns: DEMO },
  { id: 'shopify', name: 'Shopify', description: 'E-commerce integration', version: '2.1.3', author: 'nyedis', demoColumns: DEMO },
  { id: 'argent', name: 'Argent', description: 'Web3 wallet operations', version: '0.9.1', author: 'community', demoColumns: DEMO },
  { id: 'leaveit', name: 'LeaveIt', description: 'Task and notes manager', version: '1.0.2', author: 'community', demoColumns: DEMO },
  { id: 'github', name: 'GitHub', description: 'Repo, PR and issue automation', version: '3.0.0', author: 'core', demoColumns: DEMO },
];
