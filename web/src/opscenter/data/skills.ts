
export interface SkillRow {
  id: string;
  name: string;
  description: string;
  author: string;
  added: string;
  installed: boolean;
  demoColumns: readonly string[];
}

const DEMO = ['author', 'added'] as const;

export const skills: SkillRow[] = [
  { id: 'file-ops', name: 'file-ops', description: 'Read, write, edit files', author: 'core', added: '2d ago', installed: true, demoColumns: DEMO },
  { id: 'web-search', name: 'web-search', description: 'Search the web in real-time', author: 'core', added: '4d ago', installed: true, demoColumns: DEMO },
  { id: 'codebase', name: 'codebase', description: 'Semantic codebase search', author: 'core', added: '6d ago', installed: true, demoColumns: DEMO },
  { id: 'terminal', name: 'terminal', description: 'Run shell commands safely', author: 'core', added: '1w ago', installed: false, demoColumns: DEMO },
  { id: 'git', name: 'git', description: 'Git operations & workflows', author: 'core', added: '2w ago', installed: false, demoColumns: DEMO },
];
