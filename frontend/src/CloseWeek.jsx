import { useCallback, useEffect, useState } from 'react'
import { api } from './api.js'

// 'ปิดสัปดาห์' — one button instead of six GitHub workflows pressed in an order only Fiat knew
// (production phase 1, 2026-10-02). The checks say what still stands in the way, 'ดูแผน' runs
// every step report-only, 'ปิดสัปดาห์' runs them for real. The steps run on GitHub Actions;
// this page reads their progress back from the database (close_week.py).

const fmt = (n) => (n ?? 0).toLocaleString('th-TH')
const when = (s) => {
  if (!s) return ''
  const d = new Date(s.replace(' ', 'T'))
  return Number.isNaN(d.getTime()) ? s
    : d.toLocaleString('th-TH', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}
const SERVICES = ['Saver Bike', 'Standard Bike', 'Standard Car']
const RUN_TH = {
  queued: ['รอคิว GitHub', 'bg-slate-100 text-slate-600'],
  running: ['กำลังทำ', 'bg-blue-50 text-blue-700'],
  done: ['เสร็จ', 'bg-emerald-50 text-emerald-700'],
  failed: ['ล้ม', 'bg-red-50 text-red-700'],
  blocked: ['ไม่ได้เริ่ม', 'bg-amber-50 text-amber-800'],
}
const STEP_MARK = {
  waiting: ['○', 'text-slate-300'],
  running: ['◐', 'text-blue-600 animate-pulse'],
  done: ['✓', 'text-emerald-600'],
  failed: ['✗', 'text-red-600'],
  skipped: ['–', 'text-slate-400'],
}

function Checks({ pre }) {
  return (
    <ul className="divide-y divide-slate-100">
      {pre.checks.map((c) => {
        const bad = !c.ok
        const tone = !bad ? 'text-emerald-600' : c.level === 'block' ? 'text-red-600' : 'text-amber-600'
        return (
          <li key={c.key} className="flex items-start gap-3 py-2">
            <span className={`w-5 shrink-0 text-center font-semibold ${tone}`} aria-hidden="true">
              {!bad ? '✓' : c.level === 'block' ? '✗' : '!'}
            </span>
            <div className="min-w-0">
              <p className="text-sm">{c.label}</p>
              <p className={`text-xs ${bad ? tone : 'text-slate-500'}`}>{c.detail}</p>
            </div>
          </li>
        )
      })}
    </ul>
  )
}

function Score({ card, target, title }) {
  if (!card) return null
  return (
    <div>
      {title && <p className="text-xs text-slate-500 mb-1">{title}</p>}
      <table className="w-full text-sm tabular-nums">
        <thead>
          <tr className="text-left text-xs text-slate-500 border-b border-slate-200">
            <th className="py-1.5 pr-2 font-normal">Service Type</th>
            <th className="py-1.5 pr-2 font-normal text-right">มี</th>
            <th className="py-1.5 font-normal text-right">เทียบเป้า {fmt(target)}</th>
          </tr>
        </thead>
        <tbody>
          {SERVICES.map((s) => {
            const n = card.by_service?.[s] ?? 0
            const d = n - target
            return (
              <tr key={s} className="border-b border-slate-100 last:border-b-0">
                <td className="py-1.5 pr-2">{s}</td>
                <td className="py-1.5 pr-2 text-right">{fmt(n)}</td>
                <td className={`py-1.5 text-right ${d === 0 ? 'text-emerald-700' : d > 0 ? 'text-amber-700' : 'text-red-700'}`}>
                  {d === 0 ? 'ครบ' : d > 0 ? `เกิน ${fmt(d)}` : `ขาด ${fmt(-d)}`}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {Object.keys(card.staged || {}).length > 0 && (
        <p className="text-xs text-slate-500 mt-1">
          รอลงโฟลเดอร์ใน _พร้อมอ่าน: {Object.entries(card.staged).map(([k, v]) => `${k} ${fmt(v)}`).join(' · ')}
        </p>
      )}
    </div>
  )
}

function RunView({ run, target }) {
  const [open, setOpen] = useState({})
  const [label, cls] = RUN_TH[run.status] || [run.status, 'bg-slate-100']
  const res = run.result || {}
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`text-xs rounded-full px-2.5 py-1 font-medium ${cls}`}>{label}</span>
        <span className="text-sm font-medium">{run.mode === 'apply' ? 'ปิดจริง' : 'ดูแผน'} #{run.id}</span>
        <span className="text-xs text-slate-500">{when(run.created_at)}{run.finished_at ? ` → ${when(run.finished_at)}` : ''}</span>
      </div>
      {run.message && (
        <p className={`text-sm rounded-lg px-3 py-2 ${run.status === 'failed' || run.status === 'blocked'
          ? 'bg-red-50 text-red-800' : 'bg-slate-50 text-slate-700'}`}>{run.message}</p>
      )}
      <ol className="space-y-1">
        {run.steps.map((s) => {
          const [mark, tone] = STEP_MARK[s.status] || ['?', '']
          const can = !!s.summary
          return (
            <li key={s.key} className="rounded-lg border border-slate-100">
              <button type="button" disabled={!can} onClick={() => setOpen((o) => ({ ...o, [s.key]: !o[s.key] }))}
                className="w-full flex items-center gap-3 px-3 py-2 text-left disabled:cursor-default">
                <span className={`w-5 text-center font-semibold ${tone}`} aria-hidden="true">{mark}</span>
                <span className={`text-sm flex-1 ${s.status === 'skipped' ? 'text-slate-400' : ''}`}>{s.title}</span>
                {s.flag === 'block' && <span className="text-xs rounded-full bg-red-50 text-red-700 px-2 py-0.5">พบปัญหา</span>}
                {s.flag === 'warn' && <span className="text-xs rounded-full bg-amber-50 text-amber-800 px-2 py-0.5">มีข้อสังเกต</span>}
                {can && <span className="text-slate-400 text-xs">{open[s.key] ? '▲' : '▼'}</span>}
              </button>
              {open[s.key] && (
                <pre className="mx-3 mb-3 text-xs bg-slate-50 rounded p-3 whitespace-pre-wrap break-words overflow-x-auto">{s.summary}</pre>
              )}
            </li>
          )
        })}
      </ol>
      {res.after && (
        <div className="grid gap-4 sm:grid-cols-2">
          <Score card={res.after} target={target} title={run.mode === 'apply' ? 'สัปดาห์นี้หลังปิด' : 'สัปดาห์นี้หลังปิด (คาด)'} />
          {res.next_week && <Score card={res.next_week} target={target}
            title={run.mode === 'apply' ? 'สัปดาห์หน้า' : 'สัปดาห์หน้า (ตอนนี้ ก่อนรับงานที่ยกไป)'} />}
        </div>
      )}
      {res.file && (
        <a href={res.file} target="_blank" rel="noreferrer" className="inline-block text-sm text-emerald-700 hover:underline">
          เปิดไฟล์ Phase 3 บน Drive ↗
        </a>
      )}
    </div>
  )
}

export default function CloseWeek() {
  const [week, setWeek] = useState('')
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback((w) => api.closeWeekPage(w).then((d) => { setData(d); setError('') })
    .catch((e) => setError(e.message)), [])
  useEffect(() => { load(week) }, [week, load])

  const latest = data?.runs?.[0]
  const live = latest && (latest.status === 'queued' || latest.status === 'running')
  useEffect(() => {
    if (!live) return
    const t = setInterval(() => load(data.week), 8000)
    return () => clearInterval(t)
  }, [live, data?.week, load])

  if (error && !data) return <p className="text-sm text-red-600">โหลดไม่ได้: {error}</p>
  if (!data) return <p className="text-sm text-slate-400">กำลังโหลด…</p>
  if (!data.week) return <p className="text-sm text-slate-400">ยังไม่มีสัปดาห์ให้ปิด</p>

  const pre = data.preflight
  const blocked = !pre.ok
  const other = data.active && (!latest || data.active !== latest.id)
  const start = (mode) => {
    if (mode === 'apply' && !window.confirm(
      `ปิด ${data.label} จริง?\n\nระบบจะย้ายกลุ่ม ยกงานที่เกินไปสัปดาห์หน้า ดึงงานกลับถ้าขาด ` +
      'สร้างรูปใหม่ ออกไฟล์ Phase 3 แล้ว audit — ถ้า audit ผ่านจะติดป้ายปิดให้\n\nใช้เวลาประมาณ 10–30 นาที')) return
    setBusy(true)
    api.closeWeekStart(data.week, mode).then(() => load(data.week))
      .catch((e) => setError(e.message)).finally(() => setBusy(false))
  }

  const reopen = () => {
    if (!window.confirm(`เปิด ${data.label} อีกครั้ง? งานอัตโนมัติจะกลับมาแตะสัปดาห์นี้ได้ และกดปิดใหม่ได้`)) return
    setBusy(true)
    api.reopenWeek(data.week).then(() => load(data.week))
      .catch((e) => setError(e.message)).finally(() => setBusy(false))
  }

  return (
    <div className="max-w-3xl mx-auto space-y-4">
      <div className="flex items-center gap-2 overflow-x-auto">
        {data.weeks.map((w) => (
          <button key={w.date_from} onClick={() => setWeek(w.date_from)}
            className={`shrink-0 min-h-10 px-4 rounded-full text-sm border ${w.date_from === data.week
              ? 'bg-slate-900 text-white border-slate-900' : 'bg-white text-slate-600 border-slate-300'}`}>
            {w.label.replace(/^\d{4}-/, '')}{w.closed ? ' · ปิดแล้ว' : ''}
          </button>
        ))}
      </div>

      <section className="bg-white rounded-xl border border-slate-200 shadow-sm">
        <div className="px-5 py-4 border-b border-slate-200 flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <h2 className="font-semibold">ปิดสัปดาห์ · {data.label.replace(/^\d{4}-/, '')}</h2>
            <p className="text-xs text-slate-500">{data.week} – {data.week_to}</p>
          </div>
          {data.closed
            ? <span className="flex items-center gap-2">
                <span className="text-xs rounded-full bg-emerald-50 text-emerald-700 px-3 py-1">ปิดแล้ว {when(data.closed.closed_at)}</span>
                <button onClick={reopen} disabled={busy || live}
                  className="text-xs text-slate-600 hover:underline disabled:opacity-40">เปิดใหม่</button>
              </span>
            : <span className={`text-xs rounded-full px-3 py-1 ${blocked ? 'bg-red-50 text-red-700' : 'bg-blue-50 text-blue-700'}`}>
                {blocked ? 'ยังปิดไม่ได้' : 'พร้อมปิด'}
              </span>}
        </div>
        <div className="p-5 grid gap-6 md:grid-cols-[1fr_260px]">
          <div>
            <h3 className="text-sm font-medium mb-1">ก่อนปิด ต้องผ่าน</h3>
            <Checks pre={pre} />
          </div>
          <Score card={pre.card} target={data.target} title="ตอนนี้" />
        </div>
        <div className="px-5 py-4 border-t border-slate-200 space-y-2">
          {!data.can_dispatch && (
            <p className="text-xs text-amber-800 bg-amber-50 rounded px-3 py-2">
              เซิร์ฟเวอร์ยังสั่ง GitHub ไม่ได้ — ต้องตั้งค่า GITHUB_TOKEN บน Render ก่อน
            </p>
          )}
          {other && <p className="text-xs text-amber-800">มีรอบปิด #{data.active} ของอีกสัปดาห์กำลังรันอยู่ — รอให้จบก่อน</p>}
          {error && <p className="text-xs text-red-700">{error}</p>}
          <div className="flex flex-wrap gap-2">
            <button onClick={() => start('plan')} disabled={busy || live || other || !data.can_dispatch}
              className="min-h-10 px-4 rounded-lg border border-slate-300 bg-white text-sm hover:bg-slate-50 disabled:opacity-40">
              ดูแผน
            </button>
            <button onClick={() => start('apply')}
              disabled={busy || live || other || blocked || !data.plan_ok || !data.can_dispatch || !!data.closed}
              className="min-h-10 px-4 rounded-lg bg-slate-900 text-white text-sm hover:bg-slate-800 disabled:opacity-40">
              ปิดสัปดาห์
            </button>
          </div>
          {!data.closed && !data.plan_ok && !blocked && (
            <p className="text-xs text-slate-500">กด 'ดูแผน' ก่อน — ปุ่มปิดจะเปิดเมื่อมีแผนที่ทำไม่เกิน 12 ชม.</p>
          )}
        </div>
      </section>

      {latest && (
        <section className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
          <RunView run={latest} target={data.target} />
        </section>
      )}
      {data.runs.length > 1 && (
        <details className="text-sm text-slate-600">
          <summary className="cursor-pointer">รอบก่อนหน้า ({data.runs.length - 1})</summary>
          <ul className="mt-2 space-y-1">
            {data.runs.slice(1).map((r) => (
              <li key={r.id} className="text-xs">
                #{r.id} {r.mode === 'apply' ? 'ปิดจริง' : 'ดูแผน'} · {(RUN_TH[r.status] || [r.status])[0]} · {when(r.created_at)}
                {r.message ? ` — ${r.message}` : ''}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}
