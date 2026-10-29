
export interface ShellKnownEntry {
  folder: string;
  why: string;
}

export const KNOWN: readonly ShellKnownEntry[] = [
  { folder: 'task-manager-all', why: '#2006' },
  { folder: 'task-manager', why: '#2006' },
];

export const KNOWN_CEILING = 2;
