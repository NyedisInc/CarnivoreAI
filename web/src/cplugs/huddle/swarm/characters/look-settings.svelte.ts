import { HOME_SHAPES, type HomeShape, type HomeShapeName } from './shapes';
import { ALL_STATES, ANIMATIONS, type CharacterState } from './states';

export const COLOR_MODES = ['project', 'random'] as const;
export type ColorMode = (typeof COLOR_MODES)[number];

export const LOOK_RANKS = ['sysop', 'company', 'project', 'agent'] as const;
export type LookRank = (typeof LOOK_RANKS)[number];

export const SHAPE_NAMES = Object.keys(HOME_SHAPES) as HomeShapeName[];

export const NO_ANIMATION = 'none';

export interface SwarmLook {
  color_mode: ColorMode;
  shapes: Record<LookRank, HomeShapeName>;
  animations: Partial<Record<CharacterState, string>>;
}

export function defaultLook(): SwarmLook {
  return { color_mode: 'project', shapes: { sysop: 'square', company: 'square', project: 'square', agent: 'square' }, animations: {} };
}

export const swarmLook = $state<SwarmLook>(defaultLook());

export function adoptLook(answer: Partial<Record<keyof SwarmLook, unknown>> | null | undefined): void {
  const d = defaultLook();
  swarmLook.color_mode = (COLOR_MODES as readonly unknown[]).includes(answer?.color_mode) ? (answer!.color_mode as ColorMode) : d.color_mode;
  const shapes = (answer?.shapes ?? {}) as Record<string, unknown>;
  swarmLook.shapes = Object.fromEntries(
    LOOK_RANKS.map((r) => [r, (SHAPE_NAMES as readonly unknown[]).includes(shapes[r]) ? shapes[r] : d.shapes[r]]),
  ) as SwarmLook['shapes'];
  const picks = (answer?.animations ?? {}) as Record<string, unknown>;
  swarmLook.animations = Object.fromEntries(
    ALL_STATES.flatMap((s) => {
      const v = picks[s];
      return typeof v === 'string' && (v === NO_ANIMATION || ANIMATIONS.includes(v)) ? [[s, v]] : [];
    }),
  );
}

export function lookRank(rank: string | null | undefined): LookRank {
  return rank === 'alpha' ? 'sysop' : rank === 'company' || rank === 'project' ? rank : 'agent';
}

export function homeShapeOf(rank: string | null | undefined): HomeShape {
  return rank == null ? 'sq' : HOME_SHAPES[swarmLook.shapes[lookRank(rank)]];
}
