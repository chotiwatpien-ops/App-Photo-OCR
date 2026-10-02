import { useCallback, useEffect, useState } from 'react'
import { api } from './api.js'
import Icon from './Icon.jsx'

// ปิดสัปดาห์และไฟล์ — check the week is ready, see what closing would do, close it, take the
// files (production phase 1, 2026-10-02; redesigned 2026-10 as four visible steps). The work runs
// on GitHub Actions (close_week.py); this page reads its progress back from the database. Every
// file the customer receives sits in the last card, so nobody has to know where Drive keeps it.

const fmt = (n) => (n ?? 0).toLocaleString('th-TH')
const TH_MONTHS = ['ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.', 'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.']
const wk = (label) => (label || '').replace(/^\d{4}-W/, 'WK')
const day = (iso) => { const d = new Date(`${iso}T00:00:00`); return `${d.getDate()} ${TH_MONTHS[d.getMonth()]}` }
const when = (s) => {
  if (!s) return ''
  const d = new Date(String(s).replace(' ', 'T'))
  return Number.isNaN(d.getTime()) ? s
    : `${d.getDate()} ${TH_MONTHS[d.getMonth()]} ${d.toLocaleTimeString('th-TH', { hour: '2-digit', minute: '2-digit' })}`
}
const SERVICES = ['Saver Bike', 'Standard Bike', 'Standard Car']
const RUN_TH = {
  queued: ['รอคิว', 'bg-wait-bg text-wait-ink'], running: ['กำลังทำ', 'bg-accent-bg text-accent'],
  done: ['เสร็จ', 'bg-ok-bg text-ok-ink'], failed: ['ไม่สำเร็จ', 'bg-danger-bg text-danger-ink'],
  blocked: ['ไม่ได้เริ่ม', 'bg-warn-bg text-warn-ink'],
}
const STEP_MARK = {
  waiting: ['○', 'text-muted'], running: ['◐', 'text-accent animate-pulse'], done: ['✓', 'text-ok'],
  failed: ['✗', 'text-danger'], skipped: ['–', 'text-muted'],
}

function Card({ children, className = '', ...rest }) {
  return <section className={`bg-white border border-line rounded-xl ${className}`} {...rest}>{children}</section>
}

function Stepper({ steps }) {
  return (
    <ol aria-label="ขั้นตอน" className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      {steps.map((s, i) => (
        <li key={s.title} aria-current={s.state === 'now' ? 'step' : undefined}
          className={`bg-white rounded-xl border px-4 py-3.5 flex items-center gap-3 ${s.state === 'now' ? 'border-accent' : 'border-line'}`}>
          <span className={`w-8 h-8 shrink-0 rounded-full flex items-center justify-center text-sm font-semibold ${
            s.state === 'done' ? 'bg-ok-bg text-ok-ink' : s.state === 'now' ? 'bg-accent text-white' : 'bg-line-soft text-muted'}`}>
            {s.state === 'done' ? <Icon name="check" size={16} /> : i + 1}
          </span>
          <span className="min-w-0">
            <span className="block font-semibold">{s.title}</span>
            <span className="block text-sm text-muted truncate">{s.sub}</span>
          </span>
        </li>
      ))}
    </ol>
  )
}

function Checks({ pre }) {
  return (
    <ul>
      {pre.checks.map((c) => {
        const tone = c.ok ? 'bg-ok-bg text-ok-ink' : c.level === 'block' ? 'bg-danger-bg text-danger-ink' : 'bg-warn-bg text-warn-ink'
        return (
          <li key={c.key} className="flex gap-3 py-2.5 border-t border-line-soft first:border-t-0">
            <span className={`w-6 h-6 shrink-0 rounded-full flex items-center justify-center text-[13px] font-semibold ${tone}`} aria-hidden="true">
              {c.ok ? <Icon name="check" size={14} /> : c.level === 'block' ? '✗' : '!'}
            </span>
            <div className="min-w-0">
              <p className="text-sm">{c.label}</p>
              <p className={`text-sm ${c.ok ? 'text-muted' : c.level === 'block' ? 'text-danger-ink' : 'text-warn-ink'}`}>{c.detail}</p>
            </div>
          </li>
        )
      })}
    </ul>
  )
}

function PlanTable({ before, after, target, nextLabel }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-muted">
            <th scope="col" className="font-normal py-2 border-b border-line-soft">Service Type</th>
            <th scope="col" className="font-normal py-2 border-b border-line-soft text-right">ตอนนี้</th>
            <th scope="col" className="font-normal py-2 border-b border-line-soft text-right">หลังปิด</th>
            <th scope="col" className="font-normal py-2 border-b border-line-soft text-right">ยกไป {nextLabel}</th>
          </tr>
        </thead>
        <tbody>
          {SERVICES.map((s) => {
            const now = before?.by_service?.[s] ?? 0
            const then = after?.by_service?.[s] ?? now
            const moved = now - then
            return (
              <tr key={s}>
                <td className="py-2.5 border-b border-line-soft">{s}</td>
                <td className="py-2.5 border-b border-line-soft text-right">{fmt(now)}</td>
                <td className={`py-2.5 border-b border-line-soft text-right font-semibold ${then >= target ? 'text-ok-ink' : 'text-warn-ink'}`}>
                  {fmt(then)}{then < target ? <span className="font-normal"> (ขาด {fmt(target - then)})</span> : ''}
                </td>
                <td className="py-2.5 border-b border-line-soft text-right">
                  {moved > 0 ? fmt(moved) : moved < 0 ? <span className="text-ok-ink">ดึงกลับ {fmt(-moved)}</span> : '0'}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function Steps({ run }) {
  const [open, setOpen] = useState({})
  return (
    <ol className="flex flex-col gap-1">
      {run.steps.map((s) => {
        const [mark, tone] = STEP_MARK[s.status] || ['?', '']
        return (
          <li key={s.key} className="rounded-lg border border-line-soft">
            <button type="button" disabled={!s.summary} onClick={() => setOpen((o) => ({ ...o, [s.key]: !o[s.key] }))}
              className="w-full min-h-11 flex items-center gap-3 px-3 text-left disabled:cursor-default">
              <span className={`w-5 text-center font-semibold ${tone}`} aria-hidden="true">{mark}</span>
              <span className={`flex-1 text-sm ${s.status === 'skipped' ? 'text-muted' : ''}`}>{s.title}</span>
              {s.flag === 'block' && <span className="text-xs rounded-full bg-danger-bg text-danger-ink px-2 py-0.5">พบปัญหา</span>}
              {s.flag === 'warn' && <span className="text-xs rounded-full bg-warn-bg text-warn-ink px-2 py-0.5">มีข้อสังเกต</span>}
              {s.summary && <Icon name="chevron" size={16} className={`text-muted transition-transform ${open[s.key] ? 'rotate-90' : ''}`} />}
            </button>
            {open[s.key] && (
              <pre className="mx-3 mb-3 text-xs bg-ground rounded p-3 whitespace-pre-wrap break-words overflow-x-auto">{s.summary}</pre>
            )}
          </li>
        )
      })}
    </ol>
  )
}

function FileCard({ title, sub, actions, muted }) {
  return (
    <div className={`border border-line rounded-xl px-4 py-3.5 flex flex-col gap-1.5 ${muted ? 'bg-ground' : 'bg-white'}`}>
      <p className="font-medium break-words">{title}</p>
      <p className="text-sm text-muted">{sub}</p>
      <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
        {actions.map(([label, href, icon, download]) => (href ? (
          <a key={label} href={href} target={download ? undefined : '_blank'} rel="noreferrer"
            className="min-h-9 inline-flex items-center gap-1.5 text-sm text-accent hover:underline">
            <Icon name={icon} size={16} />{label}
          </a>
        ) : (
          <span key={label} className="min-h-9 inline-flex items-center text-sm text-muted">{label}</span>
        )))}
      </div>
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

  if (error && !data) return <p className="text-sm text-danger-ink">โหลดไม่ได้: {error}</p>
  if (!data) return <p className="text-sm text-muted">กำลังโหลด…</p>
  if (!data.week) return <p className="text-sm text-muted">ยังไม่มีสัปดาห์ให้ปิด</p>

  const pre = data.preflight
  const ready = pre.ok
  const closed = !!data.closed
  const plan = data.runs.find((r) => r.mode === 'plan' && r.status === 'done')
  const other = data.active && (!latest || data.active !== latest.id)
  const n = data.label.match(/W(\d+)$/)
  const nextLabel = n ? `WK${+n[1] + 1}` : 'สัปดาห์หน้า'
  const label = wk(data.label)
  const applying = live && latest.mode === 'apply'

  const start = (mode) => {
    if (mode === 'apply' && !window.confirm(
      `ปิด ${label} จริง?\n\nระบบจะย้ายแถวตาม Service Type ยกงานที่เกินไป ${nextLabel} ดึงงานกลับถ้ากลุ่มไหนขาด ` +
      'สร้างรูปใหม่ ออกไฟล์ แล้วตรวจซ้ำ — ถ้าตรวจผ่านจะติดป้ายปิดให้เอง\n\nใช้เวลาประมาณ 10–30 นาที')) return
    setBusy(true)
    api.closeWeekStart(data.week, mode).then(() => load(data.week))
      .catch((e) => setError(e.message)).finally(() => setBusy(false))
  }
  const reopen = () => {
    if (!window.confirm(`เปิด ${label} อีกครั้ง?\n\nงานอัตโนมัติจะกลับมาแตะสัปดาห์นี้ได้ และกดปิดใหม่ได้`)) return
    setBusy(true)
    api.reopenWeek(data.week).then(() => load(data.week)).catch((e) => setError(e.message)).finally(() => setBusy(false))
  }

  const steps = [
    { title: 'ตรวจความพร้อม', state: closed || ready ? 'done' : 'now', sub: closed || ready ? 'ผ่านครบ' : 'ยังมีเรื่องค้าง' },
    { title: 'ดูแผน', state: closed || data.plan_ok ? 'done' : ready ? 'now' : 'todo',
      sub: closed ? 'เสร็จ' : data.plan_ok ? `เมื่อ ${when(plan?.finished_at)}` : 'ยังไม่ได้ทำ' },
    { title: 'ปิดสัปดาห์', state: closed ? 'done' : applying || (ready && data.plan_ok) ? 'now' : 'todo',
      sub: closed ? `ปิดแล้ว ${when(data.closed.closed_at)}` : applying ? 'กำลังทำ…' : ready && data.plan_ok ? 'พร้อมกด' : 'รอขั้นก่อนหน้า' },
    { title: 'รับไฟล์', state: closed ? 'now' : 'todo', sub: closed ? 'พร้อมแล้ว' : 'หลังปิดเสร็จ' },
  ]
  const show = live ? latest : (closed && lastClose(data)) || plan
  const showResult = show?.result || {}

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm text-muted">ปิดสัปดาห์ → ได้ไฟล์ส่งลูกค้า</p>
          <h1 className="text-2xl sm:text-[28px] font-semibold tracking-tight">
            {label} <span className="font-normal text-ink-soft text-base sm:text-xl">· {day(data.week)} – {day(data.week_to)}</span>
          </h1>
        </div>
        <div role="group" aria-label="เลือกสัปดาห์" className="flex gap-2 overflow-x-auto">
          {[...data.weeks].reverse().map((w) => {
            const on = w.date_from === data.week
            return (
              <button key={w.date_from} onClick={() => setWeek(w.date_from)} aria-pressed={on}
                className={`shrink-0 min-h-10 px-4 rounded-full text-sm border ${on ? 'bg-ink text-white border-ink' : 'bg-white text-ink-soft border-line'}`}>
                {wk(w.label)}{w.closed ? ' · ปิดแล้ว' : ''}
              </button>
            )
          })}
        </div>
      </div>

      <Stepper steps={steps} />

      {!data.can_dispatch && (
        <p className="text-sm text-warn-ink bg-warn-bg rounded-lg px-4 py-3">
          ตอนนี้ปิดสัปดาห์จากหน้านี้ยังไม่ได้ — ระบบยังไม่ได้ตั้งค่าการสั่งงาน ให้แจ้งผู้ดูแลระบบ
        </p>
      )}
      {other && <p className="text-sm text-warn-ink">มีการปิดสัปดาห์อื่นกำลังทำอยู่ — รอให้เสร็จก่อน</p>}
      {error && <p className="text-sm text-danger-ink">{error}</p>}

      <div className="grid gap-5 lg:grid-cols-2">
        <Card aria-labelledby="ready-h" className="p-4 sm:px-6 sm:py-5">
          <h2 id="ready-h" className="text-[17px] font-semibold mb-1">ความพร้อม</h2>
          {pre.checks.every((c) => c.ok) ? (
            // all clear says so in one line; the list is there for whoever wants it
            <details>
              <summary className="cursor-pointer min-h-10 flex items-center gap-2 text-sm text-ok-ink">
                <Icon name="check" size={16} />ผ่านครบทุกข้อ ({pre.checks.length}) · ดูรายการ
              </summary>
              <Checks pre={pre} />
            </details>
          ) : <Checks pre={pre} />}
        </Card>

        <Card aria-labelledby="plan-h" className="p-4 sm:px-6 sm:py-5 flex flex-col gap-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 id="plan-h" className="text-[17px] font-semibold">
              {live ? (applying ? 'กำลังปิดสัปดาห์' : 'กำลังทำแผน') : closed ? 'ผลการปิด' : 'ผลหลังปิด (จากแผนล่าสุด)'}
            </h2>
            {show && (
              <span className={`text-xs font-medium rounded-full px-2.5 py-1 ${(RUN_TH[show.status] || [])[1] || ''}`}>
                {(RUN_TH[show.status] || [show.status])[0]} · {when(show.finished_at || show.created_at)}
              </span>
            )}
          </div>
          {live ? (
            <>
              <p className="text-sm text-ink-soft">ใช้เวลาประมาณ 10–30 นาที หน้านี้อัปเดตเองทุก 8 วินาที ปิดหน้าไปก่อนได้</p>
              <Steps run={latest} />
            </>
          ) : show ? (
            <>
              <PlanTable before={showResult.before} after={showResult.after} target={data.target} nextLabel={nextLabel} />
              {show.message && <p className="text-sm text-ink-soft bg-ground rounded-lg px-3 py-2.5">{show.message}</p>}
            </>
          ) : (
            <p className="text-sm text-muted bg-ground rounded-lg px-3 py-3">
              กด "ดูแผน" เพื่อดูว่าหลังปิดแต่ละ Service Type จะเหลือเท่าไหร่ และจะยกไป {nextLabel} กี่เที่ยว — ดูแผนไม่เปลี่ยนอะไร
            </p>
          )}
          {!closed && !live && (
            <p className="text-sm text-ink-soft">
              ปิดแล้ว ระบบจะย้ายแถวตาม Service Type ยกงานที่เกินไป {nextLabel} สร้างรูปใหม่ ออกไฟล์ และตรวจซ้ำให้เอง
            </p>
          )}
          <div className="mt-auto flex flex-wrap gap-2.5 pt-1">
            {closed ? (
              <button onClick={reopen} disabled={busy || live}
                className="min-h-11 px-4 rounded-lg border border-line bg-white hover:bg-ground text-sm disabled:opacity-40">
                เปิดสัปดาห์นี้อีกครั้ง
              </button>
            ) : (
              <>
                <button onClick={() => start('apply')}
                  disabled={busy || live || other || !ready || !data.plan_ok || !data.can_dispatch}
                  className="min-h-11 px-5 rounded-lg bg-accent hover:bg-accent-hover text-white text-[15px] font-semibold disabled:opacity-40">
                  ปิดสัปดาห์ {label}
                </button>
                <button onClick={() => start('plan')} disabled={busy || live || other || !data.can_dispatch}
                  className="min-h-11 px-4 rounded-lg border border-line bg-white hover:bg-ground text-sm disabled:opacity-40">
                  {data.plan_ok ? 'ทำแผนใหม่' : 'ดูแผน'}
                </button>
              </>
            )}
          </div>
          {!closed && !live && ready && !data.plan_ok && (
            <p className="text-sm text-muted">ปุ่มปิดจะกดได้เมื่อมีแผนที่ทำไม่เกิน 12 ชั่วโมง</p>
          )}
        </Card>
      </div>

      <Card aria-labelledby="files-h" className="p-4 sm:px-6 sm:py-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="files-h" className="text-[17px] font-semibold">ไฟล์ส่งลูกค้า</h2>
          <span className="text-sm text-muted">
            {closed ? 'ฉบับสุดท้ายของสัปดาห์นี้' : 'ดาวน์โหลดได้ตลอด แต่ตัวเลขสุดท้ายคือหลังปิดสัปดาห์'}
          </span>
        </div>
        <div className="grid gap-3 mt-3 sm:grid-cols-2 lg:grid-cols-4">
          <FileCard title={`Rider Trips ${label}.xlsx`} sub="Excel ตาม template ลูกค้า (Phase 3)" muted={!closed}
            actions={[['ดาวน์โหลด', api.weekFileUrl(data.week), 'download', true],
              ...(data.files?.phase3 ? [['เปิดใน Drive', data.files.phase3, 'external']] : [])]} />
          <FileCard title={`รูปส่งลูกค้า ${label}`} sub="โฟลเดอร์รูปรายเที่ยว แยกตามไรเดอร์" muted={!closed}
            actions={[[data.files?.pictures ? 'เปิดโฟลเดอร์' : 'ยังไม่มีโฟลเดอร์', data.files?.pictures, 'external']]} />
          <FileCard title={`รายงานตรวจ ${label}`} sub="งานซ้ำ · รูปหาย · ตัวเลขไม่ลงตัว" muted={!data.files?.audit}
            actions={[[data.files?.audit ? 'เปิดรายงาน' : 'มีหลังปิดสัปดาห์', data.files?.audit, 'external']]} />
          <FileCard title={`รายงานงานซ้ำ ${label}`} sub="รายอัลบั้มและรายใบ ไว้แจ้งแอดมิน"
            actions={[['ดาวน์โหลด', api.duplicateReportUrl(data.week), 'download', true]]} />
        </div>
      </Card>

      {data.runs.length > 0 && (
        <details className="bg-white border border-line rounded-xl px-4 sm:px-6 py-3.5">
          <summary className="cursor-pointer font-medium min-h-8 flex items-center">ประวัติการปิดสัปดาห์นี้ ({data.runs.length})</summary>
          <ul className="mt-2 flex flex-col gap-3">
            {data.runs.map((r) => (
              <li key={r.id} className="text-sm border-t border-line-soft pt-3">
                <p>
                  <span className="font-medium">{r.mode === 'apply' ? 'ปิดจริง' : 'ดูแผน'}</span>
                  {' · '}<span className={`text-xs rounded-full px-2 py-0.5 ${(RUN_TH[r.status] || [])[1] || ''}`}>{(RUN_TH[r.status] || [r.status])[0]}</span>
                  {' · '}<span className="text-muted">{when(r.created_at)}</span>
                </p>
                {r.message && <p className="text-ink-soft mt-0.5">{r.message}</p>}
                <details className="mt-1">
                  <summary className="cursor-pointer text-accent text-sm">ดูทีละขั้น</summary>
                  <div className="mt-2"><Steps run={r} /></div>
                </details>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

// the run whose numbers a closed week shows: its last real close, else nothing
function lastClose(data) {
  return data.runs.find((r) => r.mode === 'apply' && r.status === 'done') || null
}
