import type { Component } from 'svelte';
import type { AutomationTarget, Targets } from './api';
import { agentReady, blankAgent } from './agent-defaults';
import AgentBuilder from './AgentBuilder.svelte';
import TargetBlueprint from './TargetBlueprint.svelte';
import TargetCard from './TargetCard.svelte';
import TargetCommand from './TargetCommand.svelte';
import TargetRecipe from './TargetRecipe.svelte';
import TargetSequence from './TargetSequence.svelte';
import TargetSession from './TargetSession.svelte';

export interface TargetForm {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  component: Component<any>;
  blank(targets: Targets): AutomationTarget | null;
  ready?(target: AutomationTarget): boolean;
}

function blankRecipe(targets: Targets): AutomationTarget | null {
  const first = targets.recipes[0];
  if (!first) return null;
  const params: Record<string, unknown> = {};
  for (const [key, spec] of Object.entries(first.params_schema.properties ?? {})) if (spec.default !== undefined) params[key] = spec.default;
  return { kind: 'recipe', recipe: first.recipe, params };
}

function blankBlueprint(): AutomationTarget {
  return { kind: 'blueprint_launch', blueprint_uuid: '', members: null };
}

function blankCard(): AutomationTarget {
  return { kind: 'swarm_card', project_id: null, title: '', summary: '', text: '', how_to_validate: '', queued: false };
}

function cardReady(target: AutomationTarget): boolean {
  return target.project_id != null && String(target.title ?? '').trim() !== '';
}

function blankCommand(): AutomationTarget {
  return { kind: 'command', command: '', project_id: null };
}

function blankSession(): AutomationTarget {
  return { kind: 'session_message', session_uuid: '', text: '', if_asleep: 'wake', if_gone: 'start', project_id: null, session_name: '' };
}

function blankSequence(targets: Targets): AutomationTarget | null {
  const first = blankCommand();
  const last = blankRecipe(targets);
  return last ? { kind: 'sequence', steps: [first, last] } : null;
}

export const SEQUENCE_MIN_STEPS = 2;
export const SEQUENCE_MAX_STEPS = 4;
export const SEQUENCE_STEP_KINDS: readonly string[] = ['command', 'recipe'];
export const SEQUENCE_LAST_KINDS: readonly string[] = [...SEQUENCE_STEP_KINDS, 'session_message', 'blueprint_launch'];
export const SEQUENCE_OMITTED_BY_DESIGN: readonly string[] = ['agent'];
const SEQUENCE_ACTION_KINDS = SEQUENCE_STEP_KINDS;

export const TARGET_FORMS: Record<string, TargetForm> = {
  blueprint_launch: { component: TargetBlueprint, blank: blankBlueprint },
  recipe: { component: TargetRecipe, blank: blankRecipe },
  session_message: { component: TargetSession, blank: blankSession },
  command: { component: TargetCommand, blank: blankCommand },
  sequence: { component: TargetSequence, blank: blankSequence },
  swarm_card: { component: TargetCard, blank: blankCard, ready: cardReady },
  agent: { component: AgentBuilder, blank: blankAgent, ready: agentReady },
};

export function sequenceKinds(targets: Targets, last: boolean): string[] {
  const allowed = last ? SEQUENCE_LAST_KINDS : SEQUENCE_ACTION_KINDS;
  return allowed.filter((kind) => targets.kinds.includes(kind) && TARGET_FORMS[kind]?.blank(targets) != null);
}

export function offeredKinds(targets: Targets): string[] {
  return targets.kinds.filter((kind) => TARGET_FORMS[kind]?.blank(targets) != null);
}
