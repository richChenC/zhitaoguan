(function () {
  const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
  const duration = seconds => {
    const value = Math.max(0, Math.ceil(Number(seconds) || 0));
    return value < 60 ? `${value}秒` : `${Math.floor(value / 60)}分${value % 60}秒`;
  };
  window.importProgressDetails = task => ({
    percent: task.percent,
    label: task.stage,
    meta: task.unavailable ? '等待本机返回处理结果' : task.total == null ? `已处理 ${task.completed} ${task.unit}` :
      `已处理 ${task.completed} / ${task.total} ${task.unit}`,
    timing: task.unavailable ? '' : `已用 ${duration(task.elapsed_seconds)} · ${task.remaining_seconds == null ?
      '正在估算全程剩余时间' : `预计剩余 ${duration(task.remaining_seconds)}`}`,
  });
  window.runImportRequest = async (url, payload, onProgress, options = {}) => {
    const token = crypto.randomUUID();
    const monitor = new AbortController();
    let finished = false;
    let monitoringUnavailable = false;
    let latest = null;
    const unavailable = () => {
      monitoringUnavailable = true;
      if (!finished) onProgress?.({status: 'running', stage: '正在处理（实时进度暂不可用）',
        completed: 0, total: null, percent: null, unit: '行',
        elapsed_seconds: 0, remaining_seconds: null, unavailable: true});
    };
    const poll = (async () => {
      await delay(150);
      while (!finished) {
        try {
          const response = await fetch(`/api/import-progress?id=${encodeURIComponent(token)}`, {
            signal: monitor.signal, cache: 'no-store', headers: {'X-Thimble-Progress': '1'},
          });
          if (response.ok) {
            const task = await response.json();
            if (!finished && task.status !== 'pending') {latest = task; onProgress?.(task);}
            if (!['running', 'pending'].includes(task.status)) break;
          } else if (response.status !== 404) {
            unavailable();
            break;
          }
        } catch (error) {
          if (!monitor.signal.aborted) unavailable();
          break;
        }
        await delay(350);
      }
    })();
    try {
      const response = await fetch(url, {
        method: 'POST', signal: options.signal,
        headers: {'Content-Type': 'application/json', 'X-Thimble-Task': token},
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) {
        const error = new Error(data.error || '导入处理失败');
        error.details = data;
        error.batchId = data.batch_id;
        throw error;
      }
      if (data.requires_indication_decision) {
        // A confirmation pause is not a completed import.
        onProgress?.({...latest, status: 'awaiting_confirmation', stage: '等待确认三字符处理方式',
          percent: latest?.percent ?? (url === '/api/import-excel' ? 35 : 70),
          completed: data.parsed || 0, total: data.parsed || 0, unit: '行'});
      } else {
        onProgress?.({...latest, unavailable: false, status: 'succeeded', stage: '处理完成', percent: 100,
          completed: latest?.total ?? 0, total: latest?.total ?? null, unit: latest?.unit || '行',
          remaining_seconds: 0});
      }
      return data;
    } finally {
      finished = true;
      monitor.abort();
      await poll;
      if (monitoringUnavailable) console.warn('实时进度暂不可用，导入结果仍由主请求确认');
    }
  };
})();
