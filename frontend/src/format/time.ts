import { dayLabel } from "./display";

// Saatler her zaman İstanbul'a göre (K-99); tarayıcının saat dilimi önemsizdir.
const PARTS = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/Istanbul",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

export interface LocalMoment {
  date: string;
  time: string;
}

export function istanbul(moment: Date): LocalMoment {
  const parts = Object.fromEntries(
    PARTS.formatToParts(moment).map((part) => [part.type, part.value]),
  );
  return {
    date: `${parts.year}-${parts.month}-${parts.day}`,
    time: `${parts.hour}:${parts.minute}`,
  };
}

function parseMoment(text: string): Date {
  const moment = new Date(text);
  if (Number.isNaN(moment.getTime())) {
    throw new Error(`Zaman bekleniyordu: ${JSON.stringify(text)}`);
  }
  return moment;
}

export function localTime(text: string, today: string): string {
  const { date, time } = istanbul(parseMoment(text));
  return `${dayLabel(date, { today })} ${time}`;
}

export function localDay(text: string, today: string): string {
  return dayLabel(istanbul(parseMoment(text)).date, { today });
}
