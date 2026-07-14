import { test } from 'node:test';
import assert from 'node:assert/strict';
import { generateSlots, zonedWallToUtc, tzOffsetMs } from './slots.mjs';
import { BOOKING_CONFIG as CFG } from './booking-config.mjs';

const TZ = 'Europe/London';
// Base rules: Mon–Fri 09:00–17:00, buffer/notice OFF, so each test isolates one behaviour.
const base = (o = {}) => ({
  timeZone: TZ,
  hours: {
    1: [['09:00', '17:00']], 2: [['09:00', '17:00']], 3: [['09:00', '17:00']],
    4: [['09:00', '17:00']], 5: [['09:00', '17:00']],
  },
  slotMinutes: 30, bufferMinutes: 0, minNoticeMinutes: 0, horizonDays: 1, blackoutDates: [], ...o,
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

// --- Per-day windows ---------------------------------------------------------
test('after-work window 16:30–21:00 (BST) yields 9 slots starting 16:30', () => {
  const s = starts(generateSlots(base({ hours: { 2: [['16:30', '21:00']] } }), [], new Date('2026-07-14T00:00:00Z')));
  assert.equal(s.length, 9);
  assert.equal(s[0], '2026-07-14T15:30:00.000Z'); // 16:30 BST
  assert.ok(s.includes('2026-07-14T19:30:00.000Z')); // 20:30 BST last slot
  assert.ok(!s.includes('2026-07-14T20:00:00.000Z')); // 21:00 BST would end 21:30
});

// --- Busy / buffer -----------------------------------------------------------
test('busy 10:00–10:30 BST removes only that slot when buffer is 0', () => {
  const busy = [{ start: '2026-07-14T09:00:00Z', end: '2026-07-14T09:30:00Z' }]; // 10:00–10:30 BST
  const s = starts(generateSlots(base({ bufferMinutes: 0 }), busy, new Date('2026-07-14T00:00:00Z')));
  assert.ok(!s.includes('2026-07-14T09:00:00.000Z'));
  assert.ok(s.includes('2026-07-14T08:30:00.000Z'));
  assert.ok(s.includes('2026-07-14T09:30:00.000Z'));
});

test('15-min buffer also clears the neighbouring slots', () => {
  const busy = [{ start: '2026-07-14T09:00:00Z', end: '2026-07-14T09:30:00Z' }];
  const s = starts(generateSlots(base({ bufferMinutes: 15 }), busy, new Date('2026-07-14T00:00:00Z')));
  assert.ok(s.includes('2026-07-14T08:00:00.000Z'));
  assert.ok(!s.includes('2026-07-14T08:30:00.000Z'));
  assert.ok(!s.includes('2026-07-14T09:00:00.000Z'));
  assert.ok(!s.includes('2026-07-14T09:30:00.000Z'));
  assert.ok(s.includes('2026-07-14T10:00:00.000Z'));
});

test('all-day busy block removes every slot that day', () => {
  const busy = [{ start: '2026-07-14T00:00:00Z', end: '2026-07-15T00:00:00Z' }];
  assert.equal(generateSlots(base(), busy, new Date('2026-07-14T00:00:00Z')).length, 0);
});

// --- Notice / horizon / closed days / blackout -------------------------------
test('12h minimum notice excludes too-soon slots', () => {
  const s = starts(generateSlots(base({ minNoticeMinutes: 720 }), [], new Date('2026-07-14T00:00:00Z')));
  assert.ok(!s.includes('2026-07-14T08:00:00.000Z')); // 09:00 BST, < 12h away
  assert.ok(s.includes('2026-07-14T12:00:00.000Z')); // 13:00 BST, exactly 12h away
});

test('a day with no window yields no slots', () => {
  // base() has no Sat(6)/Sun(7) windows
  assert.equal(generateSlots(base(), [], new Date('2026-07-18T00:00:00Z')).length, 0);
});

test('blackout date is fully blocked', () => {
  assert.equal(generateSlots(base({ blackoutDates: ['2026-07-14'] }), [], new Date('2026-07-14T00:00:00Z')).length, 0);
});

test('every slot is exactly slotMinutes long', () => {
  for (const slot of generateSlots(base(), [], new Date('2026-07-14T00:00:00Z'))) {
    assert.equal(Date.parse(slot.endIso) - Date.parse(slot.startIso), 30 * 60000);
  }
});

// --- Production config encodes the agreed rules ------------------------------
test('BOOKING_CONFIG encodes the per-day rules and 14-day horizon', () => {
  assert.equal(CFG.horizonDays, 14);
  assert.deepEqual(CFG.hours[1], [['09:00', '20:00']]); // Mon
  assert.deepEqual(CFG.hours[2], [['16:30', '21:00']]); // Tue
  assert.deepEqual(CFG.hours[3], [['16:30', '21:00']]); // Wed
  assert.deepEqual(CFG.hours[4], [['09:00', '20:00']]); // Thu
  assert.deepEqual(CFG.hours[5], [['09:00', '20:00']]); // Fri
  assert.deepEqual(CFG.hours[6], [['09:00', '20:00']]); // Sat
  assert.deepEqual(CFG.hours[7], [['09:00', '20:00']]); // Sun
});
