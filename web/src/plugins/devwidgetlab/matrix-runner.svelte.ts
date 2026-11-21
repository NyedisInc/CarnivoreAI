import { t } from '../sdk';
import { fitTableState, startMatrix } from './lab-api';
import type { MatrixState } from './lab-model';

export const MATRIX_POLL_MS = 5000;
export const MATRIX_BACKOFF_MAX_MS = 60_000;

export class MatrixRunner {
  state = $state<MatrixState | null>(null);
  refusal = $state('');

  #timer: ReturnType<typeof setTimeout> | null = null;
  #gone = false;
  #failures = 0;
  readonly #onread: () => void;

  constructor(onread: () => void) {
    this.#onread = onread;
  }

  async refresh(): Promise<void> {
    try {
      this.state = await fitTableState();
      this.#failures = 0;
    } catch (error) {
      console.warn('[widget lab] fit table', error);
      this.refusal = t('cplug.devwidgetlab.fit.unreadable');
      if (this.state?.running && !this.#gone) {
        this.#failures += 1;
        this.#arm(Math.min(MATRIX_POLL_MS * 2 ** this.#failures, MATRIX_BACKOFF_MAX_MS));
      }
      return;
    }
    if (this.#gone) return;
    this.#onread();
    this.#arm(this.state.running ? MATRIX_POLL_MS : null);
  }

  #arm(delay: number | null): void {
    if (this.#timer !== null) clearTimeout(this.#timer);
    this.#timer = delay === null ? null : setTimeout(() => void this.refresh(), delay);
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
