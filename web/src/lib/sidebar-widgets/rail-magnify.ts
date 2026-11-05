import { preferenceField } from '../preferences/field';

export const RAIL_MAGNIFY_FIELD = 'rail_magnify';
export const RAIL_MAGNIFY_PERCENTS = [100, 125, 150, 175, 200] as const;
export const RAIL_MAGNIFY_DEFAULT = 150;
export const RAIL_MAGNIFY_OFF = 100;

export function asMagnify(value: unknown): number {
  return typeof value === 'number' && (RAIL_MAGNIFY_PERCENTS as readonly number[]).includes(value) ? value : RAIL_MAGNIFY_DEFAULT;
}

export const railMagnify = preferenceField<number>(RAIL_MAGNIFY_FIELD, asMagnify, RAIL_MAGNIFY_DEFAULT);

export function railPeakScale(): number {
  return railMagnify.read() / 100;
}
