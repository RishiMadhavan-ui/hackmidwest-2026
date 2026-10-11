import test from 'node:test';
import assert from 'node:assert/strict';
import { activityView, newestPaymentSignal, newestRunId } from '../src/lib/activity-view.ts';

const event = (sequence, type, data, at = '2026-10-11T12:00:00Z') => ({ sequence, type, data, at });
test('a new run cannot inherit another run or mandate approval', () => {
  const old = event(1, 'authorization.decided', { run_id: 'run_old', mandate_id: 'mnd_old', result: 'APPROVED' });
  const mismatched = event(2, 'authorization.decided', { run_id: 'run_new', mandate_id: 'mnd_other', result: 'APPROVED' });
  assert.equal(newestPaymentSignal([old, mismatched], 'mnd_new', 'run_new'), null);
  assert.equal(newestPaymentSignal([old], null, 'run_old'), null);
  const blocked = event(3, 'checkout.blocked', { run_id: 'run_new', mandate_id: 'mnd_new' });
  assert.equal(newestPaymentSignal([old, blocked], 'mnd_new', 'run_new'), blocked);
});
test('latest run selection stays within the selected mandate', () => {
  const events = [event(1, 'agent.run_started', { mandate_id: 'mnd_1', run_id: 'run_1' }),
    event(2, 'execution.launched', { mandate_id: 'mnd_2', run_id: 'run_2' })];
  assert.equal(newestRunId(events, 'mnd_1'), 'run_1');
  assert.equal(newestRunId(events, 'mnd_3'), null);
});
test('clear view preserves the source audit and admits later events', () => {
  const events = [event(1, 'agent.step', { run_id: 'run_1' }), event(2, 'agent.step', { run_id: 'run_1' })];
  const original = structuredClone(events);
  assert.deepEqual(activityView(events, { scope: 'run', runId: 'run_1', afterSequence: 1 }), [events[1]]);
  assert.deepEqual(events, original);
  assert.deepEqual(activityView(events, { scope: 'run', runId: 'run_1' }), events);
  assert.deepEqual(activityView(events, { scope: 'run' }), []);
});
test('today hides old activity while all history remains available', () => {
  const now = new Date(2026, 9, 11, 12);
  const old = event(1, 'account.login', {}, new Date(2026, 9, 10, 12).toISOString());
  const fresh = event(2, 'account.login', {}, now.toISOString());
  assert.deepEqual(activityView([old, fresh], { scope: 'today', now }), [fresh]);
  assert.deepEqual(activityView([old, fresh], { scope: 'all' }), [old, fresh]);
});
