import { useCallback, useEffect, useState } from 'react'

// Support — the vendor's view of a customer's system (production phase, 2026-10-02: "ต้องมี Log
// ให้ทางผม MA หรือเช็คได้"). Opened at /#support. It reads only /api/diag/*, which answers to the
// diag key in a header OR to a logged-in session, so support needs neither the customer's
// password nor anything that changes data. The key stays in this tab (sessionStorage).

const KEY = 'pocr:diag-key'
const fmt = (n) => (n ?? 0).toLocaleString('th-TH')
const when = (s) => {
  if (!s) return '–'
  const d = new Date(String(s).replace(' ', 'T'))
  return Number.isNaN(d.getTime()) ? s
    : d.toLocaleString('th-TH', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}
const ago = (s) => {
  if (!s) return ''
  const m = Math.round((Date.now() - new Date(String(s).replace(' ', 'T')).getTime()) / 60000)
  return m < 60 ? `${m} นาทีก่อน` : m < 48 * 60 ? `${Math.round(m / 60)} ชม.ก่อน` : `${Math.round(m / 1440)} วันก่อน`
}

function useDiag() {
  const [key, setKey] = useState(() => { try { return sessionStorage.getItem(KEY) || '' } catch { return '' } })
  const get = useCallback(async (path) => {
    const res = await fetch(path, { headers: key ? { 'X-Diag-Key': key } : {} })
    if (res.status === 401) throw new Error('need-key')
    if (!res.ok) {
      let msg = `HTTP ${res.status}`
      try { msg = (await res.json()).detail || msg } catch { /* keep */ }
      throw new Error(msg)
    }
    return res.json()
  }, [key])
  const save = (k) => { setKey(k); try { sessionStorage.setItem(KEY, k) } catch { /* private tab */ } }
  return { get, key, save }
}

function Tile({ label, value, sub, tone = 'slate' }) {
  const tones = {
    slate: 'border-slate-200', red: 'border-red-300 bg-red-50', amber: 'border-amber-300 bg-amber-50',
    green: 'border-emerald-200',
  }
  return (
    <div className={`rounded-xl border bg-white p-4 ${tones[tone]}`}>
      <p className="text-xs text-slate-500">{label}</p>
      <p className="text-xl font-semibold tabular-nums mt-0.5">{value}</p>
      {sub && <p className="text-xs text-slate-500 mt-0.5">{sub}</p>}
    </div>
  )
}

function Section({ title, right, children }) {
  return (
    <section className="bg-white rounded-xl border border-slate-200 shadow-sm">
      <div className="px-4 py-3 border-b border-slate-200 flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold text-sm">{title}</h2>
        {right}
      </div>
      <div className="p-4 overflow-x-auto">{children}</div>
    </section>
  )
}

function LogLoader({ load, render }) {
  const [open, setOpen] = useState(false)
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const toggle = () => {
    setOpen(!open)
    if (!data && !open) load().then(setData).catch((e) => setErr(e.message))
  }
  return (
    <>
      <button onClick={toggle} className="text-xs text-blue-700 hover:underline">{open ? 'ซ่อน log' : 'ดู log'}</button>
      {open && (
        <div className="mt-2">
          {err ? <p className="text-xs text-red-700">{err}</p> : !data ? <p className="text-xs text-slate-400">กำลังโหลด…</p> : render(data)}
        </div>
      )}
    </>
  )
}

const Pre = ({ children }) => (
  <pre className="text-xs bg-slate-50 rounded p-3 whitespace-pre-wrap break-words max-h-96 overflow-auto">{children}</pre>
)

export default function Support() {
  const { get, save } = useDiag()
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [draft, setDraft] = useState('')
  const [actFilter, setActFilter] = useState('')
  const [actions, setActions] = useState(null)
  const [wf, setWf] = useState('')
  const [runs, setRuns] = useState(null)

  const load = useCallback(() => {
    setError('')
    get('/api/diag/support').then(setData).catch((e) => setError(e.message))
  }, [get])
  useEffect(() => { load() }, [load])

  if (error === 'need-key') {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center p-4">
        <form onSubmit={(e) => { e.preventDefault(); save(draft.trim()) }}
          className="bg-white rounded-xl border border-slate-200 shadow-sm p-6 w-full max-w-sm space-y-3">
          <h1 className="font-semibold">Support</h1>
          <p className="text-sm text-slate-600">ใส่ diag key ของระบบนี้ (เก็บไว้เฉพาะแท็บนี้)</p>
          <input type="password" value={draft} onChange={(e) => setDraft(e.target.value)} autoFocus
            className="w-full border border-slate-300 rounded-lg px-3 py-2" aria-label="diag key" />
          <button className="w-full bg-slate-900 text-white rounded-lg py-2 text-sm">เปิด</button>
        </form>
      </div>
    )
  }
  if (error) return <p className="p-6 text-sm text-red-700">โหลดไม่ได้: {error}</p>
  if (!data) return <p className="p-6 text-sm text-slate-400">กำลังโหลด…</p>

  const last = data.ingest.last
  const ingestAge = last?.started_at ? (Date.now() - new Date(last.started_at).getTime()) / 3600000 : null
  const showActions = actions ?? data.actions
  const searchActions = () => get(`/api/diag/actions?limit=300&${actFilter.includes(':') ? 'target' : 'action'}=${encodeURIComponent(actFilter)}`)
    .then((r) => setActions(r.actions)).catch((e) => setError(e.message))
  const searchRuns = () => get(`/api/diag/runs?limit=100&workflow=${encodeURIComponent(wf)}`)
    .then((r) => setRuns(r.runs)).catch((e) => setError(e.message))

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="bg-slate-900 text-white px-4 sm:px-6 py-3 flex items-center justify-between">
        <div>
          <h1 className="font-semibold">Support · Rider Photo OCR</h1>
          <p className="text-xs text-slate-400">ข้อมูล ณ {when(data.now)} · อ่านอย่างเดียว</p>
        </div>
        <button onClick={load} className="text-sm rounded-lg px-3 py-1.5 bg-white/10 hover:bg-white/20">รีเฟรช</button>
      </header>
      <main className="max-w-6xl mx-auto p-4 sm:p-6 space-y-4">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <Tile label="ingest รอบล่าสุด" value={last ? ago(last.started_at) : '–'}
            sub={last ? (last.finished_at ? `จบ ${when(last.finished_at)} · error ${fmt(last.errors)}` : 'กำลังรัน') : ''}
            tone={!last ? 'amber' : ingestAge > 8 ? 'red' : last.errors ? 'amber' : 'green'} />
          <Tile label="รออ่าน / รอผล batch" value={fmt(data.counts.pending)}
            sub={data.batches.open ? `batch ค้าง ${data.batches.open} ชุด ตั้งแต่ ${when(data.batches.oldest)}` : 'ไม่มี batch ค้าง'}
            tone={data.batches.oldest && (Date.now() - new Date(data.batches.oldest).getTime()) > 24 * 3600000 ? 'red' : 'slate'} />
          <Tile label="คิวตรวจ / อ่านไม่สำเร็จ" value={`${fmt(data.counts.waiting)} / ${fmt(data.counts.errors)}`}
            tone={data.counts.errors ? 'amber' : 'slate'} />
          <Tile label="workflow ล้ม 7 วัน" value={fmt(data.failed_runs.length)}
            sub={`เก็บ log ล่าสุด ${when(data.archived_last)}`} tone={data.failed_runs.length ? 'red' : 'green'} />
        </div>

        {data.issues.length > 0 && (
          <Section title={`ปัญหาที่ ingest เจอ ยังไม่ปิด (${data.issues.length})`}>
            <ul className="text-sm space-y-1">
              {data.issues.map((i) => (
                <li key={i.id || i.key} className="flex gap-2">
                  <span className="text-xs rounded bg-amber-50 text-amber-800 px-1.5 py-0.5 shrink-0">{i.kind}</span>
                  <span className="break-words">{i.message}</span>
                  <span className="text-xs text-slate-400 shrink-0">เห็น {i.times_seen} ครั้ง</span>
                </li>
              ))}
            </ul>
          </Section>
        )}

        <Section title="รอบปิดสัปดาห์ล่าสุด">
          {data.close_runs.length === 0 ? <p className="text-sm text-slate-400">ยังไม่เคยกดปิดสัปดาห์จากเว็บ</p> : (
            <ul className="space-y-3">
              {data.close_runs.map((r) => (
                <li key={r.id} className="text-sm border-b border-slate-100 pb-3 last:border-b-0">
                  <p>
                    <span className="font-medium">#{r.id} {r.mode === 'apply' ? 'ปิดจริง' : 'ดูแผน'} {r.week_from}</span>
                    {' · '}<span className={r.status === 'failed' || r.status === 'blocked' ? 'text-red-700' : 'text-slate-600'}>{r.status}</span>
                    {' · '}<span className="text-slate-500">{when(r.created_at)}</span>
                  </p>
                  {r.message && <p className="text-xs text-slate-600 mt-0.5">{r.message}</p>}
                  <LogLoader load={() => get(`/api/diag/close-runs/${r.id}`)} render={(full) => (
                    <div className="space-y-2">
                      {full.steps.map((s) => (
                        <details key={s.key}>
                          <summary className="text-xs cursor-pointer">{s.status} · {s.title}</summary>
                          <Pre>{s.log || s.summary || '(ไม่มี)'}</Pre>
                        </details>
                      ))}
                    </div>
                  )} />
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="ใครทำอะไร (action log)" right={
          <form onSubmit={(e) => { e.preventDefault(); searchActions() }} className="flex gap-2">
            <input value={actFilter} onChange={(e) => setActFilter(e.target.value)} placeholder="trip:123 หรือ trip."
              className="border border-slate-300 rounded-lg px-2 py-1 text-xs w-40" aria-label="กรอง action log" />
            <button className="text-xs rounded-lg border border-slate-300 px-2 py-1">ค้น</button>
          </form>}>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-slate-500 border-b border-slate-200">
                <th className="py-1.5 pr-3 font-normal">เวลา</th><th className="py-1.5 pr-3 font-normal">ทำอะไร</th>
                <th className="py-1.5 pr-3 font-normal">กับอะไร</th><th className="py-1.5 pr-3 font-normal">ผล</th>
                <th className="py-1.5 pr-3 font-normal">จาก</th><th className="py-1.5 font-normal">รายละเอียด</th>
              </tr>
            </thead>
            <tbody>
              {showActions.map((a) => (
                <tr key={a.id} className="border-b border-slate-100 align-top">
                  <td className="py-1.5 pr-3 whitespace-nowrap">{when(a.at)}</td>
                  <td className="py-1.5 pr-3 font-mono">{a.action}</td>
                  <td className="py-1.5 pr-3 font-mono">{a.target || ''}</td>
                  <td className={`py-1.5 pr-3 ${a.status >= 400 ? 'text-red-700' : 'text-emerald-700'}`}>{a.status}</td>
                  <td className="py-1.5 pr-3 text-slate-500" title={a.user_agent}>{a.ip}</td>
                  <td className="py-1.5">
                    {a.detail ? <details><summary className="cursor-pointer text-blue-700">ดู</summary>
                      <Pre>{JSON.stringify(a.detail, null, 2)}</Pre></details> : ''}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {showActions.length === 0 && <p className="text-sm text-slate-400 mt-2">ยังไม่มีบันทึก</p>}
        </Section>

        <Section title="workflow บน GitHub (เก็บ 400 วัน)" right={
          <form onSubmit={(e) => { e.preventDefault(); searchRuns() }} className="flex gap-2">
            <input value={wf} onChange={(e) => setWf(e.target.value)} placeholder="ชื่อ workflow เช่น ingest"
              className="border border-slate-300 rounded-lg px-2 py-1 text-xs w-44" aria-label="กรองชื่อ workflow" />
            <button className="text-xs rounded-lg border border-slate-300 px-2 py-1">ค้น</button>
          </form>}>
          <ul className="space-y-2 text-sm">
            {(runs ?? data.failed_runs).map((r) => (
              <li key={r.id} className="border-b border-slate-100 pb-2 last:border-b-0">
                <p>
                  <span className={r.conclusion === 'success' ? 'text-emerald-700' : 'text-red-700'}>{r.conclusion}</span>
                  {' · '}{r.workflow}{' · '}<span className="text-slate-500">{when(r.started_at)} · {r.event}</span>
                  {' · '}<a href={r.url} target="_blank" rel="noreferrer" className="text-blue-700 hover:underline">GitHub ↗</a>
                </p>
                <LogLoader load={() => get(`/api/diag/runs/${r.id}`)} render={(full) => <Pre>{full.log_tail}</Pre>} />
              </li>
            ))}
          </ul>
          {(runs ?? data.failed_runs).length === 0 && (
            <p className="text-sm text-slate-400">{runs ? 'ไม่พบ' : 'ไม่มี workflow ล้มใน 7 วัน'}</p>
          )}
        </Section>
      </main>
    </div>
  )
}
