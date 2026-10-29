import { fetchLayoutSkills, type LayoutSkill } from './api';
import { accepted, filterSkills, typing, type Sigil } from './skill-complete';

export interface SkillCompleteDeps {
  layoutUuid(): string;
  put(text: string): void;
  load?(uuid: string, sigil: Sigil): Promise<LayoutSkill[]>;
}

export class SkillComplete {
  rows = $state<LayoutSkill[]>([]);
  active = $state(0);
  sigil = $state<Sigil>('/');
  #all: LayoutSkill[] = [];
  #loaded = '';
  #dismissed = false;
  #query = '';
  #token = 0;
  #deps: SkillCompleteDeps;

  constructor(deps: SkillCompleteDeps) {
    this.#deps = deps;
  }

  get open(): boolean {
    return this.rows.length > 0;
  }

  update(text: string, commandMode: boolean): void {
    const hit = commandMode ? typing(text) : null;
    if (!hit) {
      this.#close();
      this.#dismissed = false;
      this.#loaded = '';
      this.#token += 1;
      return;
    }
    if (this.#dismissed && hit.query === this.#query) return;
    this.#dismissed = false;
    this.#query = hit.query;
    this.sigil = hit.sigil;
    const key = `${this.#deps.layoutUuid()}${hit.sigil}`;
    if (this.#loaded === key) {
      this.#show(hit.query);
      return;
    }
    this.#loaded = key;
    this.#all = [];
    const token = ++this.#token;
    void (this.#deps.load ?? fetchLayoutSkills)(this.#deps.layoutUuid(), hit.sigil).then((skills) => {
      if (token !== this.#token) return;
      this.#all = skills;
      if (!this.#dismissed) this.#show(this.#query);
    }).catch(() => {
      if (token === this.#token) this.#loaded = '';
    });
  }

  key(key: string): boolean {
    if (!this.open) return false;
    if (key === 'ArrowDown' || key === 'ArrowUp') {
      const step = key === 'ArrowDown' ? 1 : -1;
      this.active = (this.active + step + this.rows.length) % this.rows.length;
      return true;
    }
    if (key === 'Tab' || key === 'Enter') {
      this.accept(this.active);
      return true;
    }
    if (key === 'Escape') {
      this.#dismissed = true;
      this.#close();
      return true;
    }
    return false;
  }

  accept(index: number): void {
    const skill = this.rows[index];
    if (!skill) return;
    this.#deps.put(accepted(this.sigil, skill));
    this.#close();
  }

  #show(query: string): void {
    this.rows = filterSkills(this.#all, query);
    this.active = 0;
  }

  #close(): void {
    this.rows = [];
    this.active = 0;
  }
}
