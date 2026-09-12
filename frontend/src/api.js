async function handle(res) {
  if (!res.ok) {
    let msg = `HTTP ${res.status}`
    try {
      const j = await res.json()
      msg = j.detail || msg
    } catch { /* keep default */ }
    if (res.status === 401 && msg === 'login_required') {
      window.dispatchEvent(new Event('pocr:login-required'))
    }
    throw new Error(msg)
  }
  return res.json()
}

const json = (method, body) => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export function exportUrl({ dateFrom, dateTo, driver, jobId, committedOnly = true } = {}) {
  const p = new URLSearchParams()
  if (dateFrom) p.set('date_from', dateFrom)
  if (dateTo) p.set('date_to', dateTo)
  if (driver) p.set('driver', driver)
  if (jobId) p.set('job_id', jobId)
  p.set('committed_only', committedOnly ? 'true' : 'false')
  return `/api/export?${p.toString()}`
}

export const api = {
  health: () => fetch('/api/health').then(handle),
  me: () => fetch('/api/me').then(handle),
  login: (password) => fetch('/api/login', json('POST', { password })).then(handle),
  logout: () => fetch('/api/logout', { method: 'POST' }).then(handle),
  jobs: () => fetch('/api/jobs').then(handle),
  job: (id) => fetch(`/api/jobs/${id}`).then(handle),
  drivers: () => fetch('/api/drivers').then(handle),
  createJob: (formData) => fetch('/api/jobs', { method: 'POST', body: formData }).then(handle),
  patchTrip: (id, fields) => fetch(`/api/trips/${id}`, json('PATCH', fields)).then(handle),
  deleteTrip: (id) => fetch(`/api/trips/${id}`, { method: 'DELETE' }).then(handle),
  weeks: () => fetch('/api/weeks').then(handle),
  // ปิดสัปดาห์ = ส่งไฟล์ให้ลูกค้าแล้ว งานอัตโนมัติจะไม่แตะสัปดาห์นั้นอีก (เก็บกวาดรูปซ้ำ,
  // สร้างรูปส่งลูกค้าทับของเดิม) เปิดใหม่ได้ถ้ายังต้องแก้ต่อ
  closeWeek: (dateFrom, dateTo) =>
    fetch(`/api/weeks/${dateFrom}/close?date_to=${dateTo || ''}`, { method: 'POST' }).then(handle),
  reopenWeek: (dateFrom) => fetch(`/api/weeks/${dateFrom}/reopen`, { method: 'POST' }).then(handle),
  batches: () => fetch('/api/batches').then(handle),
  collectBatches: () => fetch('/api/batches/collect', { method: 'POST' }).then(handle),
  renameJobRider: (jobId, name) => fetch(`/api/jobs/${jobId}/rider`, json('PATCH', { name })).then(handle),
  triggerIngest: () => fetch('/api/ingest/trigger', { method: 'POST' }).then(handle),
  // the two customer workbooks, rebuilt from the database right now and pushed to Drive —
  // without waiting for an ingest round (Ops, 2026-09-09)
  exportSync: () => fetch('/api/export/sync', { method: 'POST' }).then(handle),
  exportSyncStatus: () => fetch('/api/export/sync').then(handle),
  summary: (params = {}) => fetch(`/api/summary?${new URLSearchParams(params)}`).then(handle),
  trips: (params = {}) => fetch(`/api/trips?${new URLSearchParams(params)}`).then(handle),
  reviewQueue: () => fetch('/api/review-queue').then(handle),
  completeness: () => fetch('/api/completeness').then(handle),
  spreadDates: (jobId, allRows = false) =>
    fetch(`/api/jobs/${jobId}/spread-dates?all_rows=${allRows}`, { method: 'POST' }).then(handle),
  approveTrip: (id) => fetch(`/api/trips/${id}/approve`, { method: 'POST' }).then(handle),
  approvePassing: () => fetch('/api/review-queue/approve-passing', { method: 'POST' }).then(handle),
  discarded: (everything = false) =>
    fetch(`/api/review-queue/discarded?everything=${everything}`).then(handle),
  clearDiscarded: () =>
    fetch('/api/review-queue/discarded/clear', { method: 'POST' }).then(handle),
  restoreTrip: (id) => fetch(`/api/trips/${id}/restore`, { method: 'POST' }).then(handle),
  commit: (id, force = false) =>
    fetch(`/api/jobs/${id}/commit${force ? '?force=true' : ''}`, { method: 'POST' }).then(handle),
}
