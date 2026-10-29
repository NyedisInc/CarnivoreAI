
import type { ComponentProps } from 'svelte';
import type CellFrame from '../shell/CellFrame.svelte';

type CellFrameProps = ComponentProps<typeof CellFrame>;

export type FrameTitleProps = Pick<CellFrameProps, 'meta' | 'count' | 'suffix' | 'onRightControl'>;

export type FrameControlProps = Pick<
  CellFrameProps,
  'collapsed' | 'onToggleCollapse' | 'summary' | 'total' | 'expanded' | 'onToggleExpanded'
>;

export type FrameDensityProps = Pick<CellFrameProps, 'widthState' | 'heightState'>;

export type FrameHostProps = Pick<CellFrameProps, 'instance' | 'body' | 'store'>;

export type WidgetFrameProps = FrameTitleProps & FrameControlProps & FrameDensityProps & FrameHostProps;

export type UngroupedFrameProps = Exclude<keyof CellFrameProps, keyof WidgetFrameProps>;

export const FRAME_CONTRACT_COMPLETE: [UngroupedFrameProps] extends [never] ? true : never = true;
