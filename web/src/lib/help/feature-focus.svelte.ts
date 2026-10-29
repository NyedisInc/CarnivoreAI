
export const featureFocusState = $state<{ id: string | null }>({ id: null });

export function requestFocusFeature(id: string): void {
  featureFocusState.id = id;
}

export function clearFocusFeature(): void {
  featureFocusState.id = null;
}
