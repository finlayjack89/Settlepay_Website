// Calendar client abstraction for the Deno Edge Functions.
// Real implementation talks to the Google Calendar API (FreeBusy + events with a
// Google Meet link, sendUpdates:'none' so Google emails nobody). Mock returns
// deterministic fixtures so availability/book/manage run end-to-end BEFORE the
// GOOGLE_SA_KEY credential exists. Selected automatically by the key's presence.

import { getAccessToken } from './google-auth.ts';
import { BOOKING_CONFIG } from './booking-config.mjs';

const CAL = BOOKING_CONFIG.calendarId;
const API = 'https://www.googleapis.com/calendar/v3';

export interface BusyInterval {
  start: string;
  end: string;
}
export interface CreateEventInput {
  startIso: string;
  endIso: string;
  summary: string;
  description: string;
  attendeeName: string;
  attendeeEmail: string;
  timeZone: string;
  requestId: string;
}
export interface CalendarClient {
  freeBusy(timeMinIso: string, timeMaxIso: string): Promise<BusyInterval[]>;
  createEvent(i: CreateEventInput): Promise<{ eventId: string; meetUrl: string }>;
  updateEvent(eventId: string, patch: { startIso: string; endIso: string; timeZone: string }): Promise<void>;
  deleteEvent(eventId: string): Promise<void>;
}

class GoogleCalendarClient implements CalendarClient {
  private async headers() {
    return { authorization: `Bearer ${await getAccessToken()}`, 'content-type': 'application/json' };
  }

  async freeBusy(timeMin: string, timeMax: string): Promise<BusyInterval[]> {
    const res = await fetch(`${API}/freeBusy`, {
      method: 'POST',
      headers: await this.headers(),
      body: JSON.stringify({ timeMin, timeMax, timeZone: 'UTC', items: [{ id: CAL }] }),
    });
    if (!res.ok) throw new Error(`freeBusy ${res.status}: ${await res.text()}`);
    const j = await res.json();
    return (j.calendars?.[CAL]?.busy ?? []) as BusyInterval[];
  }

  async createEvent(i: CreateEventInput): Promise<{ eventId: string; meetUrl: string }> {
    const res = await fetch(`${API}/calendars/${encodeURIComponent(CAL)}/events?conferenceDataVersion=1&sendUpdates=none`, {
      method: 'POST',
      headers: await this.headers(),
      body: JSON.stringify({
        summary: i.summary,
        description: i.description,
        start: { dateTime: i.startIso, timeZone: i.timeZone },
        end: { dateTime: i.endIso, timeZone: i.timeZone },
        attendees: [{ email: i.attendeeEmail, displayName: i.attendeeName }],
        conferenceData: { createRequest: { requestId: i.requestId, conferenceSolutionKey: { type: 'hangoutsMeet' } } },
        reminders: { useDefault: false },
        guestsCanModify: false,
      }),
    });
    if (!res.ok) throw new Error(`createEvent ${res.status}: ${await res.text()}`);
    let data = await res.json();
    let meetUrl = extractMeet(data);
    // Meet link can be provisioned a beat after creation — resolve once if pending.
    if (!meetUrl && data.conferenceData?.status?.statusCode === 'pending') {
      const r2 = await fetch(`${API}/calendars/${encodeURIComponent(CAL)}/events/${data.id}?conferenceDataVersion=1`, {
        headers: await this.headers(),
      });
      if (r2.ok) data = await r2.json();
      meetUrl = extractMeet(data);
    }
    return { eventId: data.id, meetUrl: meetUrl ?? '' };
  }

  async updateEvent(eventId: string, patch: { startIso: string; endIso: string; timeZone: string }): Promise<void> {
    const res = await fetch(`${API}/calendars/${encodeURIComponent(CAL)}/events/${eventId}?conferenceDataVersion=1&sendUpdates=none`, {
      method: 'PATCH',
      headers: await this.headers(),
      body: JSON.stringify({
        start: { dateTime: patch.startIso, timeZone: patch.timeZone },
        end: { dateTime: patch.endIso, timeZone: patch.timeZone },
      }),
    });
    if (!res.ok) throw new Error(`updateEvent ${res.status}: ${await res.text()}`);
  }

  async deleteEvent(eventId: string): Promise<void> {
    const res = await fetch(`${API}/calendars/${encodeURIComponent(CAL)}/events/${eventId}?sendUpdates=none`, {
      method: 'DELETE',
      headers: await this.headers(),
    });
    if (!res.ok && res.status !== 404 && res.status !== 410) {
      throw new Error(`deleteEvent ${res.status}: ${await res.text()}`);
    }
  }
}

function extractMeet(data: any): string {
  if (data?.hangoutLink) return data.hangoutLink;
  const ep = data?.conferenceData?.entryPoints?.find((e: any) => e.entryPointType === 'video');
  return ep?.uri ?? '';
}

// Deterministic fixtures — active whenever GOOGLE_SA_KEY is unset. Lets the full
// flow (DB write, branded email, .ics) run for real, with a fake Meet link.
class MockCalendarClient implements CalendarClient {
  freeBusy(): Promise<BusyInterval[]> {
    return Promise.resolve([]);
  }
  createEvent(i: CreateEventInput): Promise<{ eventId: string; meetUrl: string }> {
    return Promise.resolve({ eventId: `mock_${i.requestId}`, meetUrl: 'https://meet.google.com/mck-abcd-efg' });
  }
  updateEvent(): Promise<void> {
    return Promise.resolve();
  }
  deleteEvent(): Promise<void> {
    return Promise.resolve();
  }
}

export function makeCalendarClient(): CalendarClient {
  return Deno.env.get('GOOGLE_SA_KEY') ? new GoogleCalendarClient() : new MockCalendarClient();
}

export function isMockCalendar(): boolean {
  return !Deno.env.get('GOOGLE_SA_KEY');
}
