
import { isLayoutKey } from './session-layouts';

let listener: ((key: string) => void) | null = null;

let layoutListener: ((key: string) => void) | null = null;

export function onArrangementChange(fn: (key: string) => void): () => void {
  listener = fn;
  return () => {
    if (listener === fn) listener = null;
  };
}

export function arrangementChanged(key: string): void {
  if (isLayoutKey(key)) {
    layoutListener?.(key);
    return;
  }
  listener?.(key);
}

export function onLayoutArrangementChange(fn: (key: string) => void): () => void {
  layoutListener = fn;
  return () => {
    if (layoutListener === fn) layoutListener = null;
  };
}

let homeListener: (() => void) | null = null;

export function onHomeChange(fn: () => void): () => void {
  homeListener = fn;
  return () => {
    if (homeListener === fn) homeListener = null;
  };
}

export function homeChanged(): void {
  homeListener?.();
}

let warroomListener: (() => void) | null = null;

export function onWarroomChange(fn: () => void): () => void {
  warroomListener = fn;
  return () => {
    if (warroomListener === fn) warroomListener = null;
  };
}

export function warroomChanged(): void {
  warroomListener?.();
}
