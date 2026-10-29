
export type DensityMode = 'compact' | 'cozy' | 'detailed';

export const DENSITY_MODES: readonly DensityMode[] = ['compact', 'cozy', 'detailed'];

interface DensityGlobal {
  currentMode?: () => DensityMode;
  setMode?: (mode: DensityMode) => boolean;
}

function densityApi(): DensityGlobal | null {
  return (globalThis as { SessionSidebarDensity?: DensityGlobal }).SessionSidebarDensity ?? null;
}

export function currentDensity(): DensityMode | null {
  const mode = densityApi()?.currentMode?.();
  return mode && DENSITY_MODES.includes(mode) ? mode : null;
}

export function setDensity(mode: DensityMode): void {
  densityApi()?.setMode?.(mode);
}
