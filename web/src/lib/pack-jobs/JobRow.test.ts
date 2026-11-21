/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import type { JobView } from './jobs-api';
import JobRow from './JobRow.svelte';

const mounted: Array<Record<string, unknown>> = [];
afterEach(() => { mounted.splice(0).forEach((m) => void unmount(m)); document.body.innerHTML = ''; });

function job(extra: Partial<JobView> = {}): JobView {
  return {
    id: 'j1', side: 'caller', state: 'running', body: 'command', project_uid: 'p1', project_name: 'proj', folder: null, command: 'make test', kind: null,
    task_head: null, agent_type: null, computer: 'tower', reason: 'tower was idle', exit_code: null, output_tail: null, applied: [], deleted: [], clashes: [], ref: null,
    error_code: null, error_detail: null, question: null, question_kind: null, result_text: null, account_label: null, usage: null,
    created_at: 1000, started_at: 1000, ended_at: null, caller_session: 'u1', worker_session_uuid: null, peer_install_id: null, worker_listing_uuid: null, ...extra,
  };
}

function draw(props: { job: JobView; canOpenWorker?: boolean; onStop?: (j: JobView) => void }): HTMLElement {
  const host = document.createElement('div');
  document.body.append(host);
  mounted.push(mount(JobRow, { target: host, props }) as Record<string, unknown>);
  flushSync();
  return host;
}

describe('a jobs row', () => {
  it('shows the state tag, the head, where, the why line and a stop control that asks the parent', () => {
    const onStop = vi.fn();
    const host = draw({ job: job(), onStop });
    expect(host.querySelector('[data-jobs="state"]')?.textContent).toBe('running');
    expect(host.textContent).toContain('make test');
    expect(host.textContent).toContain('tower · proj');
    expect(host.querySelector('[data-jobs="why"]')?.textContent).toBe('tower was idle');
    (host.querySelector('[data-jobs="stop"]') as HTMLElement).click();
    expect(onStop).toHaveBeenCalledTimes(1);
  });

  it('a finished job has no stop; a host row has no stop and no open worker', () => {
    expect(draw({ job: job({ state: 'done', ended_at: 1100 }) }).querySelector('[data-jobs="stop"]')).toBeNull();
    const host = draw({ job: job({ side: 'host', body: 'agent', state: 'running', caller_session: null }) });
    expect(host.querySelector('[data-jobs="stop"]')).toBeNull();
    expect(host.querySelector('[data-jobs="open-worker"]')).toBeNull();
  });

  it('open worker is disabled when the listing has no worker row, and enabled when it has', () => {
    const missing = draw({ job: job({ body: 'agent', task_head: 'fix it' }), canOpenWorker: false });
    expect((missing.querySelector('[data-jobs="open-worker"]') as HTMLButtonElement).disabled).toBe(true);
    const found = draw({ job: job({ body: 'agent', task_head: 'fix it' }), canOpenWorker: true });
    expect((found.querySelector('[data-jobs="open-worker"]') as HTMLButtonElement).disabled).toBe(false);
  });

  it('draws text from a job as text, never as markup', () => {
    const host = draw({ job: job({ command: '<img src=x onerror=alert(1)>', output_tail: '<b>tail</b>', state: 'failed', exit_code: 1, ended_at: 1100 }) });
    expect(host.querySelector('img')).toBeNull();
    expect(host.querySelector('b')).toBeNull();
    expect(host.textContent).toContain('<img src=x onerror=alert(1)>');
  });
});
