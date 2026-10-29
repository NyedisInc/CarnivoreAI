
import { getContext, setContext } from 'svelte';
import type { ResizeGuide } from './resize-hint';

const FRAME_GUIDE = Symbol('frame-resize-guide');

export class FrameGuide {
  guide = $state.raw<ResizeGuide | null>(null);
  bodyFloorPx = $state.raw<{ width: number; height: number } | null>(null);
  plates = $state(0);
}

export function provideFrameGuide(): FrameGuide {
  return setContext(FRAME_GUIDE, new FrameGuide());
}

export function useFrameGuide(): FrameGuide | null {
  return getContext<FrameGuide | undefined>(FRAME_GUIDE) ?? null;
}

export const FRAME_GUIDE_KEY = FRAME_GUIDE;
