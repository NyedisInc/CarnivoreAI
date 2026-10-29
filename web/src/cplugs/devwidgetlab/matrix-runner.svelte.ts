import { t } from '../sdk';
import { fitTableState, startMatrix } from './lab-api';
import type { MatrixState } from './lab-model';

export const MATRIX_POLL_MS = 5000;

export class MatrixRunner {
  state = $state<MatrixState | null>(null);
  refusal = $state('');

  #timer: ReturnType<typeof setTimeout> | null = null;
  #gone = false;
  readonly #onread: () => void;

  constructor(onread: () => void) {
    this.#onread = onread;
  }

  async refresh(): Promise<void> {
    try {
      this.state = await fitTableState();
    } catch (error) {
      console.warn('[widget lab] fit table', error);
      this.refusal = t('cplug.devwidgetlab.fit.unreadable');
      return;
    }
    if (this.#gone) return;
    this.#onread();
    if (this.#timer !== null) clearTimeout(this.#timer);
    this.#timer = this.state.running ? setTimeout(() => void this.refresh(), MATRIX_POLL_MS) : null;
  }

  async run(catalog: boolean, only: string | null = null): Promise<void> {
    this.refusal = '';
    const started = await startMatrix(catalog, only);
    if (started.state === null) {
      this.refusal = started.refusal;
      return;
    }
    this.state = started.state;
    this.#onread();
    await this.refresh();
  }

  destroy(): void {
    this.#gone = true;
    if (this.#timer !== null) clearTimeout(this.#timer);
  }
}
