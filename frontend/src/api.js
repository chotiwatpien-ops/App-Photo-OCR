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
  batches: () => fetch('/api/batches').then(handle),
  collectBatches: () => fetch('/api/batches/collect', { method: 'POST' }).then(handle),
  renameJobRider: (jobId, name) => fetch(`/api/jobs/${jobId}/rider`, json('PATCH', { name })).then(handle),
  triggerIngest: () => fetch('/api/ingest/trigger', { method: 'POST' }).then(handle),
  summary: (params = {}) => fetch(`/api/summary?${new URLSearchParams(params)}`).then(handle),
  trips: (params = {}) => fetch(`/api/trips?${new URLSearchParams(params)}`).then(handle),
  reviewQueue: () => fetch('/api/review-queue').then(handle),
  completeness: () => fetch('/api/completeness').then(handle),
  spreadDates: (jobId, allRows = false) =>
    fetch(`/api/jobs/${jobId}/spread-dates?all_rows=${allRows}`, { method: 'POST' }).then(handle),
  approveTrip: (id) => fetch(`/api/trips/${id}/approve`, { method: 'POST' }).then(handle),
  approvePassing: () => fetch('/api/review-queue/approve-passing', { method: 'POST' }).then(handle),
  discarded: () => fetch('/api/review-queue/discarded').then(handle),
  restoreTrip: (id) => fetch(`/api/trips/${id}/restore`, { method: 'POST' }).then(handle),
  commit: (id, force = false) =>
    fetch(`/api/jobs/${id}/commit${force ? '?force=true' : ''}`, { method: 'POST' }).then(handle),
}
