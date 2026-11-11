import { SvelteMap } from 'svelte/reactivity';

export interface VisitorPromptAnswer { prompt: string; options?: string[]; checked?: boolean; text?: string; note?: string }
export interface VisitorAnswerBody { answers?: VisitorPromptAnswer[]; payload?: Record<string, unknown> }

export interface VisitorRevision {
  label: string;
  number: number;
  revision: string;
  updated_at: number;
  print?: string;
  present?: boolean;
}

export type VisitorRevisionAnswers = VisitorRevision & { body: VisitorAnswerBody };

export interface VisitorRevisionFollow {
  rows: () => VisitorRevision[];
  answers: (revision: string, number: number) => Promise<VisitorAnswerBody | null>;
  stop: () => void;
}

export interface VisitorRevisionSource {
  id: string;
  enabled: () => boolean;
  follow: (slug: string) => VisitorRevisionFollow;
}

export type VisitorRevisionOpener = (slug: string, revision: string, number: number) => void;

const sources = new SvelteMap<string, VisitorRevisionSource>();
let openers = $state.raw<VisitorRevisionOpener[]>([]);

export function registerVisitorRevisionSource(source: VisitorRevisionSource): void {
  sources.set(source.id, source);
}

export function visitorRevisionSources(): VisitorRevisionSource[] {
  return [...sources.values()].filter((source) => source.enabled());
}

export function registerVisitorRevisionOpener(open: VisitorRevisionOpener): () => void {
  openers = [...openers, open];
  return () => { openers = openers.filter((one) => one !== open); };
}

export function openVisitorRevision(slug: string, revision: string, number: number): boolean {
  const open = openers.at(-1);
  if (!open) return false;
  open(slug, revision, number);
  return true;
}

export function canOpenVisitorRevision(): boolean {
  return openers.length > 0;
}

export function resetVisitorRevisions(): void {
  sources.clear();
  openers = [];
}
