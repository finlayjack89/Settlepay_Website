/**
 * Pure, DST-correct slot engine for a single host. Uses only Intl + Date, so the
 * exact same file runs inside the Deno Edge Functions AND under `node --test`.
 *
 * @typedef {{ start: string, end: string }} Interval  ISO instants (busy block)
 * @typedef {{ startIso: string, endIso: string }} Slot
 */

/**
 * Offset (ms) of `tz` from UTC at instant `t` (ms since epoch): local = utc + offset.
 */
export function tzOffsetMs(t, tz) {
  const p = Object.fromEntries(
    new Intl.DateTimeFormat('en-US', {
      timeZone: tz,
      hourCycle: 'h23',
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    })
      .formatToParts(t)
      .map((x) => [x.type, x.value]),
  );
  return Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute, +p.second) - t;
}

/**
 * UTC ms for a `tz` wall-clock time on a given calendar day — correct across DST
 * transitions (re-checks the offset once the initial guess has been applied).
 */
export function zonedWallToUtc(y, m, d, hh, mm, tz) {
  const guess = Date.UTC(y, m - 1, d, hh, mm, 0);
  const off = tzOffsetMs(guess, tz);
  let utc = guess - off;
  const off2 = tzOffsetMs(utc, tz);
  if (off2 !== off) utc = guess - off2;
  return utc;
}

/** { year, month, day, weekday(1=Mon…7=Sun) } for instant `ms` in `tz`. */
export function zonedYmd(ms, tz) {
  const p = Object.fromEntries(
    new Intl.DateTimeFormat('en-GB', {
      timeZone: tz, weekday: 'short', year: 'numeric', month: '2-digit', day: '2-digit',
    })
      .formatToParts(ms)
      .map((x) => [x.type, x.value]),
  );
  const wk = { Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6, Sun: 7 }[p.weekday];
  return { year: +p.year, month: +p.month, day: +p.day, weekday: wk };
}

/**
 * Available booking slots between `now` and `now + horizonDays`.
 * A slot [s, s+slot] is available iff it is a working-day slot inside the daily
 * window, is at least `minNoticeMinutes` in the future, and does not fall within
 * `bufferMinutes` of any busy interval.
 *
 * @param {typeof import('./booking-config.mjs').BOOKING_CONFIG} cfg
 * @param {Interval[]} busy
 * @param {Date} now
 * @returns {Slot[]}
 */
export function generateSlots(cfg, busy, now) {
  const tz = cfg.timeZone;
  const step = cfg.slotMinutes * 60000;
  const nowMs = now.getTime();
  const earliest = nowMs + cfg.minNoticeMinutes * 60000;
  const horizon = nowMs + cfg.horizonDays * 86400000;
  const p2 = (n) => String(n).padStart(2, '0');
  const padded = (busy || []).map((b) => ({
    start: Date.parse(b.start) - cfg.bufferMinutes * 60000,
    end: Date.parse(b.end) + cfg.bufferMinutes * 60000,
  }));

  const out = [];
  const seen = new Set(); // dedupe days (a fall-back 25h day can repeat via +24h stepping)
  for (let dOff = 0; dOff <= cfg.horizonDays + 1; dOff++) {
    const { year, month, day, weekday } = zonedYmd(nowMs + dOff * 86400000, tz);
    const iso = `${year}-${p2(month)}-${p2(day)}`;
    if (seen.has(iso)) continue;
    seen.add(iso);
    if (cfg.blackoutDates && cfg.blackoutDates.includes(iso)) continue;

    const windows = (cfg.hours && cfg.hours[weekday]) || []; // per-weekday availability
    for (const [ws, we] of windows) {
      const [sh, sm] = ws.split(':').map(Number);
      const [eh, em] = we.split(':').map(Number);
      const winStart = zonedWallToUtc(year, month, day, sh, sm, tz);
      const winEnd = zonedWallToUtc(year, month, day, eh, em, tz);
      for (let t = winStart; t + step <= winEnd; t += step) {
        if (t < earliest || t > horizon) continue;
        if (padded.some((pp) => t < pp.end && t + step > pp.start)) continue; // half-open overlap
        out.push({ startIso: new Date(t).toISOString(), endIso: new Date(t + step).toISOString() });
      }
    }
  }
  return out;
}
