import { untrack } from 'svelte';
import { activeProject, followActiveProject } from '../sdk';
import { huddle } from './huddle.svelte';

export function addTargetFor(project: number | null, lists: readonly string[]): string | null {
  if (project === null) return null;
  const key = String(project);
  return lists.includes(key) ? key : null;
}

let started = false;
let pendingAdd: number | null = null;

function applyAdd(): void {
  const key = addTargetFor(pendingAdd, huddle.lists.map((row) => row.key));
  if (key === null) return;
  huddle.addTarget = key;
  pendingAdd = null;
}

export function startFollow(): void {
  if (started) return;
  started = true;
  followActiveProject();
  $effect.root(() => {
    $effect(() => {
      const project = activeProject.project;
      if (project === null) return;
      pendingAdd = project;
      untrack(applyAdd);
    });
    $effect(() => {
      if (huddle.lists.length && pendingAdd !== null) untrack(applyAdd);
    });
  });
}
