import { describe, expect, it } from 'vitest';
import { ScenarioStore } from './scenario-store';

const NOTE = '/sessions/cloude_billing-api/note';
const table = () => ({
  [`GET ${NOTE}`]: { status: 'ok', revision: 7, body: 'old', updated_at: '2026-10-18T00:00:00Z' },
  'GET /sessions/list': [],
  'GET /stats*': { n: 1 },
});
const put = (body: unknown): RequestInit => ({ method: 'PUT', body: JSON.stringify(body) });

describe('ScenarioStore', () => {
  it('answers a stored read from memory, as a copy', () => {
    const store = new ScenarioStore(table());
    const first = store.simulate('GET', NOTE)!;
    (first.body as { body: string }).body = 'mutated by the caller';
    expect((store.simulate('GET', NOTE)!.body as { body: string }).body).toBe('old');
  });

  it('plays a save: merges the fields the read has, bumps the revision and the time, and the next read returns it', () => {
    const store = new ScenarioStore(table());
    const saved = store.simulate('PUT', NOTE, put({ body: 'new text', expected_revision: 7 }))!;
    expect(saved.status).toBe(200);
    expect(saved.body).toMatchObject({ status: 'ok', revision: 8, body: 'new text' });
    expect((saved.body as { updated_at: string }).updated_at).not.toBe('2026-10-18T00:00:00Z');
    expect(store.simulate('GET', NOTE)!.body).toMatchObject({ revision: 8, body: 'new text' });
    expect(store.simulate('GET', NOTE)!.body).not.toHaveProperty('expected_revision');
  });

  it('refuses a stale save with 409 and the stored value, like the server', () => {
    const store = new ScenarioStore(table());
    const refused = store.simulate('PUT', NOTE, put({ body: 'x', expected_revision: 3 }))!;
    expect(refused.status).toBe(409);
    expect(refused.body).toMatchObject({ revision: 7, body: 'old' });
    expect(store.simulate('GET', NOTE)!.body).toMatchObject({ revision: 7, body: 'old' });
  });

  it('declines what is not its to play: no stored read, a prefix route, a delete, a body that is not json', () => {
    const store = new ScenarioStore(table());
    expect(store.simulate('PUT', '/nowhere', put({ a: 1 }))).toBeUndefined();
    expect(store.simulate('GET', '/stats/charts')).toBeUndefined();
    expect(store.simulate('DELETE', NOTE)).toBeUndefined();
    expect(store.simulate('PUT', NOTE, { method: 'PUT', body: 'not json' })).toBeUndefined();
  });

  it('leaves a route the fixture names for the write to the normal lookup', () => {
    const store = new ScenarioStore({ ...table(), [`PUT ${NOTE}`]: { custom: true } });
    expect(store.simulate('PUT', NOTE, put({ body: 'x' }))).toBeUndefined();
  });
});
