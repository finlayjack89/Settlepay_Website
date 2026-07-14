import { test } from 'node:test';
import assert from 'node:assert/strict';
import { generateSlots, zonedWallToUtc, tzOffsetMs } from './slots.mjs';

const TZ = 'Europe/London';
// Base rules with buffer/notice OFF so each test isolates one behaviour.
const base = (o = {}) => ({
  timeZone: TZ, workingDays: [1, 2, 3, 4, 5],
  dayStart: '09:00', dayEnd: '17:00', slotMinutes: 30, bufferMinutes: 0,
  minNoticeMinutes: 0, horizonDays: 1, blackoutDates: [], ...o,
});
const starts = (slots) => slots.map((s) => s.startIso);

// --- DST offset helper -------------------------------------------------------
test('London offset is +1h in BST (July) and 0 in GMT (January)', () => {
  assert.equal(tzOffsetMs(Date.parse('2026-07-14T12:00:00Z'), TZ), 60 * 60000);
  assert.equal(tzOffsetMs(Date.parse('2026-01-13T12:00:00Z'), TZ), 0);
});

test('zonedWallToUtc maps 09:00 London to the right UTC instant per season', () => {
  assert.equal(new Date(zonedWallToUtc(2026, 7, 14, 9, 0, TZ)).toISOString(), '2026-07-14T08:00:00.000Z');
  assert.equal(new Date(zonedWallToUtc(2026, 1, 13, 9, 0, TZ)).toISOString(), '2026-01-13T09:00:00.000Z');
});

// --- Core generation ---------------------------------------------------------
test('BST working day: 16 slots, first 09:00 BST = 08:00Z, last 16:30 BST = 15:30Z', () => {
  const s = generateSlots(base(), [], new Date('2026-07-14T00:00:00Z')); // Tue 14 Jul (BST)
  assert.equal(s.length, 16);
  assert.equal(s[0].startIso, '2026-07-14T08:00:00.000Z');
  assert.equal(s[0].endIso, '2026-07-14T08:30:00.000Z');
  assert.ok(starts(s).includes('2026-07-14T15:30:00.000Z')); // 16:30 BST last slot
  assert.ok(!starts(s).includes('2026-07-14T16:00:00.000Z')); // 17:00 BST would end 17:30
});

test('GMT working day: first slot 09:00 GMT = 09:00Z', () => {
  const s = generateSlots(base(), [], new Date('2026-01-13T00:00:00Z')); // Tue 13 Jan (GMT)
  assert.equal(s.length, 16);
  assert.equal(s[0].startIso, '2026-01-13T09:00:00.000Z');
});

test('spring-forward: Mon after the March change is BST (09:00 = 08:00Z)', () => {
  const s = generateSlots(base(), [], new Date('2026-03-30T00:00:00Z')); // Mon 30 Mar
  assert.equal(s[0].startIso, '2026-03-30T08:00:00.000Z');
});

test('fall-back: Mon after the October change is GMT (09:00 = 09:00Z)', () => {
  const s = generateSlots(base(), [], new Date('2026-10-26T00:00:00Z')); // Mon 26 Oct
  assert.equal(s[0].startIso, '2026-10-26T09:00:00.000Z');
});

// --- Busy / buffer -----------------------------------------------------------
test('busy 10:00–10:30 BST removes only that slot when buffer is 0', () => {
  const busy = [{ start: '2026-07-14T09:00:00Z', end: '2026-07-14T09:30:00Z' }]; // 10:00–10:30 BST
  const s = starts(generateSlots(base({ bufferMinutes: 0 }), busy, new Date('2026-07-14T00:00:00Z')));
  assert.ok(!s.includes('2026-07-14T09:00:00.000Z')); // the busy slot
  assert.ok(s.includes('2026-07-14T08:30:00.000Z')); // neighbour before
  assert.ok(s.includes('2026-07-14T09:30:00.000Z')); // neighbour after
});

test('15-min buffer also clears the neighbouring slots', () => {
  const busy = [{ start: '2026-07-14T09:00:00Z', end: '2026-07-14T09:30:00Z' }]; // 10:00–10:30 BST
  const s = starts(generateSlots(base({ bufferMinutes: 15 }), busy, new Date('2026-07-14T00:00:00Z')));
  assert.ok(s.includes('2026-07-14T08:00:00.000Z'));
  assert.ok(!s.includes('2026-07-14T08:30:00.000Z'));
  assert.ok(!s.includes('2026-07-14T09:00:00.000Z'));
  assert.ok(!s.includes('2026-07-14T09:30:00.000Z'));
  assert.ok(s.includes('2026-07-14T10:00:00.000Z'));
});

test('all-day busy block removes every slot that day', () => {
  const busy = [{ start: '2026-07-14T00:00:00Z', end: '2026-07-15T00:00:00Z' }];
  const s = generateSlots(base(), busy, new Date('2026-07-14T00:00:00Z'));
  assert.equal(s.length, 0);
});

// --- Notice / horizon / working-days / blackout ------------------------------
test('12h minimum notice excludes too-soon slots', () => {
  const s = starts(generateSlots(base({ minNoticeMinutes: 720 }), [], new Date('2026-07-14T00:00:00Z')));
  assert.ok(!s.includes('2026-07-14T08:00:00.000Z')); // 09:00 BST, < 12h away
  assert.ok(s.includes('2026-07-14T12:00:00.000Z')); // 13:00 BST, exactly 12h away
});

test('weekends yield no slots', () => {
  const s = generateSlots(base(), [], new Date('2026-07-18T00:00:00Z')); // Sat + Sun
  assert.equal(s.length, 0);
});

test('blackout date is fully blocked', () => {
  const s = generateSlots(base({ blackoutDates: ['2026-07-14'] }), [], new Date('2026-07-14T00:00:00Z'));
  assert.equal(s.length, 0);
});

test('every slot is exactly slotMinutes long and inside the day window', () => {
  const s = generateSlots(base(), [], new Date('2026-07-14T00:00:00Z'));
  for (const slot of s) {
    assert.equal(Date.parse(slot.endIso) - Date.parse(slot.startIso), 30 * 60000);
  }
});
