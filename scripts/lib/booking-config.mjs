/**
 * SettlePay consultation booking rules — single source of truth for the slot engine.
 * Pure data, no runtime deps, so it is imported by both the Deno Edge Functions and
 * the Node unit tests. Change these values to change availability.
 */
export const BOOKING_CONFIG = {
  timeZone: 'Europe/London',
  workingDays: [1, 2, 3, 4, 5], // Mon–Fri (Intl weekday: 1=Mon … 7=Sun)
  dayStart: '09:00', // first slot starts at/after this London wall-clock time
  dayEnd: '17:00', // last slot must END by this time
  slotMinutes: 30,
  bufferMinutes: 15, // gap kept clear around existing busy blocks
  minNoticeMinutes: 720, // 12h — no last-minute bookings
  horizonDays: 30, // bookable up to this many days ahead
  blackoutDates: [], // London 'YYYY-MM-DD' dates to block entirely (holidays)
  calendarId: 'finlay@settlepay.uk', // calendar booked against + checked for conflicts
};
