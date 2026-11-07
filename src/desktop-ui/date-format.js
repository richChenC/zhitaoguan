// Shared presentation formatter for local timestamps.
// Database values remain unchanged; this only controls how timestamps are shown.
(function installDateFormatter(global) {
  function formatDateTime(value) {
    if (value == null || String(value).trim() === '') return '/';
    const raw = String(value).trim();
    const localIso = raw.match(/^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})(?::(\d{2}))?(?:\.\d+)?$/);
    if (localIso) return `${localIso[1]} ${localIso[2]}:${localIso[3] || '00'}`;
    const parsed = Date.parse(raw);
    if (!Number.isFinite(parsed)) return raw;
    const parts = new Intl.DateTimeFormat('zh-CN', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
      hour12: false,
    }).formatToParts(new Date(parsed));
    const get = type => parts.find(part => part.type === type)?.value || '';
    return `${get('year')}-${get('month')}-${get('day')} ${get('hour')}:${get('minute')}:${get('second')}`;
  }
  global.formatDateTime = formatDateTime;
})(window);
