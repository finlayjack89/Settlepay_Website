/**
 * Minimal, valid iCalendar (.ics) builder for one consultation VEVENT.
 * Pure — runs in the Deno Edge Functions and under `node --test`.
 * The .ics is what carries the calendar invite to the attendee, since we create
 * the Google event with sendUpdates:'none' (Google emails nobody).
 */

const pad = (n) => String(n).padStart(2, '0');

/** Date/instant → iCal UTC basic format, e.g. 20260715T083000Z. */
export function icsUtc(d) {
  const t = d instanceof Date ? d : new Date(d);
  return (
    t.getUTCFullYear() +
    pad(t.getUTCMonth() + 1) +
    pad(t.getUTCDate()) +
    'T' +
    pad(t.getUTCHours()) +
    pad(t.getUTCMinutes()) +
    pad(t.getUTCSeconds()) +
    'Z'
  );
}

/** Escape a TEXT value per RFC 5545 (backslash, semicolon, comma, newline). */
export function icsEscape(s) {
  return String(s)
    .replace(/\\/g, '\\\\')
    .replace(/;/g, '\\;')
    .replace(/,/g, '\\,')
    .replace(/\r?\n/g, '\\n');
}

/** Fold a content line to <=75 octets with CRLF + leading-space continuation. */
function fold(line) {
  if (line.length <= 75) return line;
  const parts = [];
  let i = 0;
  while (i < line.length) {
    const take = i === 0 ? 75 : 74; // 74 leaves room for the continuation space
    parts.push((i === 0 ? '' : ' ') + line.slice(i, i + take));
    i += take;
  }
  return parts.join('\r\n');
}

/**
 * Build an .ics document for a consultation.
 * @param {object} o
 * @param {string} o.uid stable UID (same across reschedule; bump sequence)
 * @param {Date|string} o.start
 * @param {Date|string} o.end
 * @param {Date|string} [o.dtstamp]
 * @param {string} o.summary
 * @param {string} o.description
 * @param {string} o.organizerName
 * @param {string} o.organizerEmail
 * @param {string} o.attendeeName
 * @param {string} o.attendeeEmail
 * @param {'REQUEST'|'CANCEL'} [o.method='REQUEST']
 * @param {'CONFIRMED'|'CANCELLED'} [o.status='CONFIRMED']
 * @param {number} [o.sequence=0]
 * @returns {string} .ics text with CRLF line endings
 */
export function buildIcs(o) {
  const method = o.method || 'REQUEST';
  const status = o.status || 'CONFIRMED';
  const seq = o.sequence ?? 0;
  const lines = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//SettlePay//Booking//EN',
    'CALSCALE:GREGORIAN',
    `METHOD:${method}`,
    'BEGIN:VEVENT',
    `UID:${o.uid}`,
    `DTSTAMP:${icsUtc(o.dtstamp ?? new Date())}`,
    `DTSTART:${icsUtc(o.start)}`,
    `DTEND:${icsUtc(o.end)}`,
    `SEQUENCE:${seq}`,
    `STATUS:${status}`,
    `SUMMARY:${icsEscape(o.summary)}`,
    `DESCRIPTION:${icsEscape(o.description)}`,
    `ORGANIZER;CN="${o.organizerName}":mailto:${o.organizerEmail}`,
    `ATTENDEE;CN="${o.attendeeName}";RSVP=TRUE:mailto:${o.attendeeEmail}`,
    'END:VEVENT',
    'END:VCALENDAR',
  ];
  return lines.map(fold).join('\r\n') + '\r\n';
}
