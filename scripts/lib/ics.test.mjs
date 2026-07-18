import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildIcs, icsUtc, icsEscape } from './ics.mjs';

const baseEvent = {
  uid: 'evt-123@settlepay.uk',
  start: '2026-07-15T08:30:00Z',
  end: '2026-07-15T09:00:00Z',
  dtstamp: '2026-07-14T09:00:00Z',
  summary: 'SettlePay consultation',
  description: 'Join: https://meet.google.com/abc-defg-hij',
  organizerName: 'Finlay Salisbury',
  organizerEmail: 'finlay@settlepay.uk',
  attendeeName: 'Jane Doe',
  attendeeEmail: 'jane@acme.co',
};

test('icsUtc formats an instant as UTC basic time', () => {
  assert.equal(icsUtc('2026-07-15T08:30:00Z'), '20260715T083000Z');
  assert.equal(icsUtc(new Date('2026-01-01T00:00:00Z')), '20260101T000000Z');
});

test('icsEscape escapes comma, semicolon, backslash and newlines', () => {
  assert.equal(icsEscape('a, b; c\\d\ne'), 'a\\, b\\; c\\\\d\\ne');
});

test('a confirmed booking produces a well-formed VEVENT', () => {
  const ics = buildIcs(baseEvent);
  assert.match(ics, /^BEGIN:VCALENDAR\r\n/);
  assert.ok(ics.includes('METHOD:REQUEST'));
  assert.ok(ics.includes('BEGIN:VEVENT'));
  assert.ok(ics.includes('UID:evt-123@settlepay.uk'));
  assert.ok(ics.includes('DTSTART:20260715T083000Z'));
  assert.ok(ics.includes('DTEND:20260715T090000Z'));
  assert.ok(ics.includes('STATUS:CONFIRMED'));
  assert.ok(ics.includes('SEQUENCE:0'));
  assert.ok(ics.includes('ORGANIZER;CN="Finlay Salisbury":mailto:finlay@settlepay.uk'));
  assert.ok(ics.includes('ATTENDEE;CN="Jane Doe";RSVP=TRUE:mailto:jane@acme.co'));
  assert.ok(ics.endsWith('END:VCALENDAR\r\n'));
});

test('every line uses CRLF and is <= 75 octets (folding)', () => {
  const ics = buildIcs({
    ...baseEvent,
    description:
      'A very long description that comfortably exceeds the seventy-five octet iCalendar line limit and therefore must be folded across multiple continuation lines with a leading space.',
  });
  assert.ok(ics.includes('\r\n'));
  for (const line of ics.split('\r\n')) {
    assert.ok(line.length <= 75, `line too long (${line.length}): ${line}`);
  }
});

test('cancellation variant sets METHOD:CANCEL, STATUS:CANCELLED and bumps SEQUENCE', () => {
  const ics = buildIcs({ ...baseEvent, method: 'CANCEL', status: 'CANCELLED', sequence: 2 });
  assert.ok(ics.includes('METHOD:CANCEL'));
  assert.ok(ics.includes('STATUS:CANCELLED'));
  assert.ok(ics.includes('SEQUENCE:2'));
  assert.ok(ics.includes('UID:evt-123@settlepay.uk')); // same UID so the invite updates
});
