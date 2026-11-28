const state = $state<{ selfId: string | null }>({ selfId: null });

export function setSelfHostInstallId(id: string | null | undefined): void {
  const cleaned = typeof id === 'string' && id.trim().length > 0 ? id.trim() : null;
  if (state.selfId !== cleaned) state.selfId = cleaned;
}

export function selfHostInstallId(): string | null {
  return state.selfId;
}
