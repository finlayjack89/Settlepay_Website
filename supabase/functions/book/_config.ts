// AUTO-GENERATED from scripts/lib — DO NOT EDIT. Regenerate: node scripts/build-booking-functions.mjs
/**
 * SettlePay consultation booking rules — single source of truth for the slot engine.
 * Pure data, no runtime deps, so it is imported by both the Deno Edge Functions and
 * the Node unit tests. Change these values to change availability.
 */
export const BOOKING_CONFIG = {
  timeZone: 'Europe/London',
  // Per-weekday availability windows (1=Mon … 7=Sun). Each day is an array of
  // [start, end] London wall-clock windows; a day absent/empty means "no slots".
  // (Actual availability is these windows MINUS Google Calendar busy time.)
  hours: {
    1: [['09:00', '20:00']], // Mon — works from home, free most of the day
    2: [['16:30', '21:00']], // Tue — evenings only (in the office by day)
    3: [['16:30', '21:00']], // Wed — evenings only
    4: [['09:00', '20:00']], // Thu — usually works from home (may vary week to week)
    5: [['09:00', '20:00']], // Fri — works from home
    6: [['09:00', '20:00']], // Sat
    7: [['09:00', '20:00']], // Sun
  },
  slotMinutes: 30,
  bufferMinutes: 15, // gap kept clear around existing busy blocks
  minNoticeMinutes: 720, // 12h — no last-minute bookings
  horizonDays: 14, // bookable up to this many days ahead
  blackoutDates: [], // London 'YYYY-MM-DD' dates to block entirely (e.g. an in-office Thursday)
  calendarId: 'finlay@settlepay.uk', // calendar booked against + checked for conflicts
};
