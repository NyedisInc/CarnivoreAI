import { readAnimations } from './animations-pref';

export const animationsState = $state({ on: readAnimations() });

export function refreshAnimations(): void {
    animationsState.on = readAnimations();
}
