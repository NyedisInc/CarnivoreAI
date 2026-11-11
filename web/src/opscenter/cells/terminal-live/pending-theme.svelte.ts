const pending = $state<Record<string, string>>({});

export function pendingTheme(tmux: string | null | undefined): string | null {
  return (tmux && pending[tmux]) || null;
}

export function setPendingTheme(tmux: string, id: string | null): void {
  if (id) pending[tmux] = id;
  else delete pending[tmux];
}
