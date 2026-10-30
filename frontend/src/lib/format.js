const MONTHS = {
  en: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
  de: ['Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun', 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez'],
};
const pad = (n) => String(n).padStart(2, '0');

export function todayIso(now = new Date()) {
  const parts = new Intl.DateTimeFormat('en', {
    timeZone: 'Europe/Bratislava', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(now);
  const part = (type) => parts.find((p) => p.type === type).value;
  return `${part('year')}-${part('month')}-${part('day')}`;
}

/** '15 Apr 2016' in English, '15.04.2016' in German. */
export function formatDate(iso, lang = 'en') {
  if (!iso) return '—';
  const [y, m, d] = iso.split('-').map(Number);
  return lang === 'de' ? `${pad(d)}.${pad(m)}.${y}` : `${pad(d)} ${MONTHS.en[m - 1]} ${y}`;
}

/** 'Apr 2016' / 'Apr 2016' (German month abbreviations). */
export function formatMonth(iso, lang = 'en') {
  if (!iso) return '—';
  const [y, m] = iso.split('-').map(Number);
  return `${(MONTHS[lang] ?? MONTHS.en)[m - 1]} ${y}`;
}

export function ageOn(birthIso, onIso) {
  const [by, bm, bd] = birthIso.split('-').map(Number);
  const [y, m, d] = onIso.split('-').map(Number);
  return y - by - (m < bm || (m === bm && d < bd) ? 1 : 0);
}

export function formatTimestamp(date) {
  const hh = pad(date.getHours());
  const mm = pad(date.getMinutes());
  return `${pad(date.getDate())} ${MONTHS.en[date.getMonth()]} ${date.getFullYear()} ${hh}:${mm}`;
}
