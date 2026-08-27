import { useCallback, useEffect, useState } from 'react'
import { api, exportUrl } from './api.js'
import NewJobForm from './NewJobForm.jsx'
import { RunsOverview, IssuesPanel } from './RunsIssues.jsx'

const fmt = (n) => (n ?? 0).toLocaleString('th-TH', { maximumFractionDigits: 0 })
const driveFile = (id) => `https://drive.google.com/file/d/${id}/view`
const driveFolder = (id) => `https://drive.google.com/drive/folders/${id}`

function RunStatus({ run, canTrigger, onTriggered, batchWaiting = 0, batchSince = null }) {
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const running = run && !run.finished_at
  const trigger = async () => {
    setBusy(true); setMsg('')
    try {
      const r = await api.triggerIngest()
      setMsg(`สั่งรันแล้ว — ดูความคืบหน้าที่ GitHub Actions (${r.url})`)
      onTriggered()
    } catch (e) { setMsg(e.message) } finally { setBusy(false) }
  }
  return (
    <section className="bg-white rounded-xl border border-slate-200 p-5 flex flex-wrap items-center gap-4">
      <div className="flex-1 min-w-64">
        <h2 className="font-semibold">ดูดรูปจาก Google Drive</h2>
        {run ? (
          <p className="text-sm text-slate-600 mt-1">
            {running ? <span className="text-amber-600 font-medium">● กำลังรัน… </span> : 'รอบล่าสุด '}
            {(run.started_at || '').replace('T', ' ')} · รูปใหม่ {run.files_new}{running && run.files_total ? ` / ${run.files_total}` : ''} · อนุมัติอัตโนมัติ {run.auto_approved} · รอคน {run.flagged}
            {run.errors ? <span className="text-red-600"> · error {run.errors}</span> : ''}
          </p>
        ) : <p className="text-sm text-slate-400 mt-1">ยังไม่เคยรัน</p>}
        {running && run?.files_total > 0 && (() => {
          const done = run.files_new || 0
          const pct = Math.min(100, Math.round(done * 100 / run.files_total))
          let eta = ''
          const t0 = Date.parse((run.started_at || '').replace(' ', 'T'))
          if (done > 0 && t0) {
            const mins = Math.round(((Date.now() - t0) / done) * (run.files_total - done) / 60000)
            if (mins >= 0 && mins < 600) eta = mins >= 60 ? ` · เหลือ ~${Math.floor(mins / 60)} ชม. ${mins % 60} นาที` : ` · เหลือ ~${mins} นาที`
          }
          return (
            <div className="mt-2 max-w-md">
              <div className="h-2 bg-slate-200 rounded-full overflow-hidden">
                <div className="h-full bg-amber-500 rounded-full transition-all" style={{ width: pct + '%' }} />
              </div>
              <p className="text-xs text-slate-500 mt-1">อ่านแล้ว {done.toLocaleString()} / {run.files_total.toLocaleString()} รูป ({pct}%){eta}</p>
            </div>
          )
        })()}
        {(() => {
          // rounds are 4h apart now; nothing for 9h means at least two slots were skipped
          const last = run?.finished_at || run?.started_at
          if (!last || running) return null
          const hrs = (Date.now() - Date.parse(last.replace(' ', 'T'))) / 36e5
          if (hrs < 9) return null
          return (
            <p className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 mt-2">
              ⏰ ไม่มีรอบดูดรูปมา {Math.floor(hrs)} ชั่วโมงแล้ว — รอบตามตารางอาจถูกข้าม
              กด “▶ ดูดรูปตอนนี้” เพื่อรันเลยได้
            </p>
          )
        })()}
        {batchWaiting > 0 && (
          <p className="text-xs text-sky-800 bg-sky-50 border border-sky-200 rounded-lg px-3 py-2 mt-2">
            📤 ส่งรูปให้ AI อ่านแบบประหยัด (ครึ่งราคา) {batchWaiting.toLocaleString()} รูป — ผลจะเข้ามาในรอบถัดไป
            {batchSince ? ` · ส่งเมื่อ ${batchSince.replace('T', ' ').slice(5, 16)}` : ''}
          </p>
        )}
        {run?.notes && <p className="text-xs text-amber-700 mt-1 whitespace-pre-line">⚠ {run.notes}</p>}
        {msg && <p className="text-xs text-slate-600 mt-1">{msg}</p>}
      </div>
      <div className="text-right text-xs text-slate-500">
        <p>ตั้งเวลา: ทุก 4 ชม. (08:23 12:23 16:23 20:23 00:23 04:23)</p>
        <button onClick={trigger} disabled={busy || running || !canTrigger}
          title={canTrigger ? 'สั่งรันรอบทันที: เก็บผล batch ที่อ่านเสร็จ แล้วส่งรูปใหม่เข้า batch (ผลของรูปใหม่จะมารอบถัดไป)' : 'ยังไม่ได้ตั้งค่า GITHUB_TOKEN — รันได้จากแท็บ Actions บน GitHub'}
          className="mt-1 bg-slate-900 hover:bg-slate-700 disabled:bg-slate-300 text-white rounded-lg px-4 py-2 text-sm font-medium">
          {busy ? 'กำลังสั่ง…' : running ? 'กำลังรันอยู่' : '▶ ดูดรูปตอนนี้'}
        </button>
      </div>
    </section>
  )
}

function JobRow({ j, onOpen, onRenamed }) {
  const rename = async () => {
    const name = prompt(`ชื่อไรเดอร์ของ job #${j.id}
(โฟลเดอร์บน Drive ควรใช้ชื่อเดียวกัน ไม่งั้นรอบหน้าจะสร้าง job ใหม่)`, j.driver_name)
    if (!name || name.trim() === j.driver_name) return
    try {
      const r = await api.renameJobRider(j.id, name.trim())
      alert(`เปลี่ยนชื่อ ${r.old} → ${r.new} แล้ว (${r.trips} แถว)`)
      onRenamed && onRenamed()
    } catch (e) { alert(e.message) }
  }

  const st = j.pending ? ['กำลังอ่าน', 'bg-amber-100 text-amber-700']
    : j.waiting ? [`รอคน ${j.waiting}`, 'bg-red-100 text-red-700']
    : j.done ? ['ครบ', 'bg-emerald-100 text-emerald-700'] : ['ว่าง', 'bg-slate-100 text-slate-500']
  return (
    <tr className="border-b border-slate-100 hover:bg-slate-50">
      <td className="py-1.5 pr-3 font-medium">{j.driver_name}
        {!j.category && <span className="ml-2 text-[10px] text-slate-400 border border-slate-200 rounded px-1">มือ</span>}
        {/^\d+$/.test(j.driver_name || '') && (
          <span className="ml-2 text-[10px] text-amber-700 bg-amber-50 border border-amber-200 rounded px-1"
            title="โฟลเดอร์บน Drive ไม่มีชื่อคน — แก้ก่อนแถวเข้า Excel">ไม่มีชื่อ</span>
        )}
        <button onClick={rename} title="เปลี่ยนชื่อไรเดอร์ของ job นี้"
          className="ml-2 text-slate-300 hover:text-blue-600 text-xs">✎</button>
      </td>
      <td className="py-1.5 pr-3 text-right tabular-nums text-slate-500">{j.images}</td>
      <td className="py-1.5 pr-3 text-right tabular-nums">{j.done}</td>
      <td className="py-1.5 pr-3 text-right tabular-nums text-emerald-700">{j.approved}<span className="text-slate-400 text-xs"> ({j.auto} auto)</span></td>
      <td className="py-1.5 pr-3 text-right tabular-nums">฿{fmt(j.net)}</td>
      <td className="py-1.5 pr-3"><span className={`text-xs rounded-full px-2 py-0.5 ${st[1]}`}>{st[0]}</span></td>
      <td className="py-1.5 text-right whitespace-nowrap text-sm">
        {j.rider_folder && <a href={driveFolder(j.rider_folder)} target="_blank" rel="noreferrer" className="text-slate-500 hover:underline mr-3" title="รูปส่งลูกค้าบน Drive">รูป ↗</a>}
        <a href={exportUrl({ jobId: j.id, committedOnly: false })} className="text-emerald-700 hover:underline mr-3">Excel</a>
        <button onClick={() => onOpen(j.id)} className="text-blue-600 hover:underline">เปิด</button>
      </td>
    </tr>
  )
}

const BATCH_STATE = {
  JOB_STATE_PENDING: ['รอคิว', 'bg-slate-100 text-slate-600'],
  JOB_STATE_RUNNING: ['กำลังอ่าน', 'bg-amber-100 text-amber-700'],
  JOB_STATE_SUCCEEDED: ['อ่านเสร็จ', 'bg-emerald-100 text-emerald-700'],
  JOB_STATE_FAILED: ['ล้มเหลว', 'bg-red-100 text-red-700'],
  JOB_STATE_CANCELLED: ['ถูกยกเลิก', 'bg-red-100 text-red-700'],
  JOB_STATE_EXPIRED: ['หมดอายุ', 'bg-red-100 text-red-700'],
}

function since(ts) {
  if (!ts) return ''
  const mins = Math.round((Date.now() - Date.parse(ts.replace(' ', 'T'))) / 60000)
  if (mins < 1) return 'เมื่อครู่'
  if (mins < 60) return `${mins} นาทีที่แล้ว`
  const h = Math.floor(mins / 60)
  return h < 24 ? `${h} ชม. ${mins % 60} นาทีที่แล้ว` : `${Math.floor(h / 24)} วันที่แล้ว`
}

function BatchPanel({ onCollected }) {
  const [data, setData] = useState(null)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const load = useCallback(() => api.batches().then(setData).catch(() => {}), [])
  useEffect(() => { load() }, [load])
  useEffect(() => {
    const t = setInterval(load, 60000)
    return () => clearInterval(t)
  }, [load])

  const rows = data?.batches || []
  if (rows.length === 0) return null
  const pending = rows.filter((b) => !b.finished_at)
  const waiting = pending.reduce((n, b) => n + (b.n_trips || 0), 0)
  const ready = pending.filter((b) => b.state === 'JOB_STATE_SUCCEEDED')
    .reduce((n, b) => n + (b.n_trips || 0), 0)

  const collect = async () => {
    setBusy(true); setMsg('')
    try {
      const r = await api.collectBatches()
      setMsg(r.trips
        ? `เก็บผลแล้ว ${r.trips} รูป · ${r.jobs} ไรเดอร์${r.waiting ? ` · ยังรออีก ${r.waiting} รูป` : ''} — รูปส่งลูกค้า/Excel บน Drive จะอัพเดตในรอบถัดไป`
        : 'ยังไม่มีก้อนไหนอ่านเสร็จ — รอสักครู่แล้วลองใหม่')
      load(); onCollected && onCollected()
    } catch (err) { setMsg(err.message) } finally { setBusy(false) }
  }

  return (
    <section className="bg-white rounded-xl border border-slate-200">
      <div className="px-5 py-3 text-sm flex flex-wrap items-center gap-2">
        <button onClick={() => setOpen(!open)} className="text-left flex items-center gap-2">
          <span className="text-slate-400">{open ? '▾' : '▸'}</span>
          <span className="text-slate-700 font-medium">งานที่ส่งให้ AI อ่าน (batch · ครึ่งราคา)</span>
        </button>
        {waiting > 0
          ? <span className="text-sky-700 bg-sky-50 border border-sky-200 rounded-full px-2 py-0.5 text-xs">
              กำลังรอผล {pending.length} ก้อน · {waiting.toLocaleString()} รูป
            </span>
          : <span className="text-slate-400 text-xs">ไม่มีก้อนที่ค้าง — ผลเข้าครบแล้ว</span>}
        <div className="ml-auto flex items-center gap-3">
          {pending.length > 0 && (
            <button onClick={collect} disabled={busy}
              title="ดึงผลที่ AI อ่านเสร็จแล้วเข้าระบบทันที ไม่ต้องรอรอบถัดไป (รูปส่งลูกค้า/Excel บน Drive ยังต้องรอรอบ)"
              className={`rounded-lg px-3 py-1.5 text-xs font-medium ${busy ? 'bg-slate-300 text-white' : ready > 0 ? 'bg-emerald-600 hover:bg-emerald-700 text-white' : 'border border-slate-300 text-slate-600 hover:bg-slate-50'}`}>
              {busy ? 'กำลังเก็บ…' : ready > 0 ? `📥 เก็บผลตอนนี้ (${ready.toLocaleString()} รูปพร้อมแล้ว)` : '📥 เก็บผลตอนนี้'}
            </button>
          )}
          <span className="text-xs text-slate-400">{rows.length} ก้อนล่าสุด</span>
        </div>
      </div>
      {msg && <p className="px-5 pb-2 text-xs text-slate-600">{msg}</p>}
      {open && (
        <div className="px-5 pb-4 overflow-x-auto">
          <table className="w-full text-sm min-w-[720px]">
            <thead><tr className="text-left text-slate-500 border-b border-slate-200 text-xs">
              <th className="py-1 pr-3">ส่งเมื่อ</th><th className="py-1 pr-3 text-right">รูป</th>
              <th className="py-1 pr-3">สถานะ</th><th className="py-1 pr-3">ไรเดอร์</th>
              <th className="py-1 pr-3">โมเดล</th><th className="py-1">รหัสก้อน</th>
            </tr></thead>
            <tbody>
              {rows.map((b) => {
                const st = BATCH_STATE[b.state] || [b.state || '-', 'bg-slate-100 text-slate-600']
                return (
                  <tr key={b.name} className="border-b border-slate-100">
                    <td className="py-1.5 pr-3 whitespace-nowrap">
                      {(b.created_at || '').replace('T', ' ').slice(5, 16)}
                      <span className="text-slate-400 text-xs ml-1">({since(b.created_at)})</span>
                    </td>
                    <td className="py-1.5 pr-3 text-right tabular-nums">{b.n_trips}</td>
                    <td className="py-1.5 pr-3">
                      <span className={`text-xs rounded-full px-2 py-0.5 ${st[1]}`}>{st[0]}</span>
                      {b.finished_at && <span className="text-slate-400 text-xs ml-1">เก็บผลแล้ว</span>}
                      {b.state_error && <span className="text-red-600 text-xs ml-1" title={b.state_error}>เช็คสถานะไม่ได้</span>}
                    </td>
                    <td className="py-1.5 pr-3 text-slate-600">{(b.riders || []).join(', ') || '-'}</td>
                    <td className="py-1.5 pr-3 text-slate-500 text-xs">{(b.model || '').replace('gemini-', '')}</td>
                    <td className="py-1.5 text-slate-400 text-xs font-mono">{(b.name || '').slice(-10)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          {rows.some((b) => b.note) && (
            <p className="text-xs text-amber-700 mt-2">
              ⚠ {rows.filter((b) => b.note).map((b) => `${(b.name || '').slice(-10)}: ${b.note}`).join(' · ')}
            </p>
          )}
        </div>
      )}
    </section>
  )
}

export default function Home({ onOpenJob, onJobCreated }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [showUpload, setShowUpload] = useState(false)
  const [openWeeks, setOpenWeeks] = useState({})

  const load = useCallback(() => api.weeks().then(setData).catch((e) => setErr(e.message)), [])
  useEffect(() => { load() }, [load])
  useEffect(() => {
    if (!data?.last_run || data.last_run.finished_at) return
    const t = setInterval(load, 10000)
    return () => clearInterval(t)
  }, [data, load])

  if (err) return <p className="text-red-600">⚠️ {err}</p>
  if (!data) return <p className="text-slate-400">กำลังโหลด...</p>
  const weeks = data.weeks
  const isOpen = (wk, i) => openWeeks[wk] ?? (i === 0)

  return (
    <div className="space-y-6">
      <RunStatus run={data.last_run} canTrigger={data.can_trigger} batchWaiting={data.batch_waiting}
        batchSince={data.batch_since} onTriggered={() => setTimeout(load, 3000)} />
      <BatchPanel onCollected={load} />
      <IssuesPanel issues={data.issues} />
      <RunsOverview runs={data.runs} />

      {weeks.length === 0 && (
        <div className="bg-white rounded-xl border border-slate-200 p-10 text-center text-slate-400">
          ยังไม่มีข้อมูล — รอรอบดูดรูปจาก Drive หรืออัปโหลดมือด้านล่าง
        </div>
      )}

      {weeks.map((W, i) => (
        <section key={W.week} className="bg-white rounded-xl border border-slate-200">
          <button onClick={() => setOpenWeeks({ ...openWeeks, [W.week]: !isOpen(W.week, i) })}
            className="w-full flex flex-wrap items-center gap-x-6 gap-y-2 px-5 py-4 text-left">
            <div className="min-w-40">
              <div className="font-semibold text-lg">{W.week}</div>
              <div className="text-xs text-slate-500">{W.date_from} → {W.date_to}</div>
            </div>
            <div className="flex gap-6 text-sm">
              <div><span className="text-slate-500">ไรเดอร์</span> <b>{W.riders}</b></div>
              <div><span className="text-slate-500">งาน</span> <b>{fmt(W.trips)}</b></div>
              <div><span className="text-slate-500">อนุมัติ</span> <b className="text-emerald-700">{fmt(W.approved)}</b> <span className="text-xs text-slate-400">({W.auto} auto)</span></div>
              <div><span className="text-slate-500">รอคน</span> <b className={W.waiting ? 'text-red-600' : ''}>{W.waiting}</b></div>
              {W.pending > 0 && <div className="text-amber-600">กำลังอ่าน {W.pending}</div>}
              <div><span className="text-slate-500">รายได้</span> <b>฿{fmt(W.net)}</b></div>
            </div>
            <div className="ml-auto flex items-center gap-3 text-sm">
              {W.xlsx
                ? <a href={driveFile(W.xlsx)} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg px-3 py-1.5">📄 Excel บน Drive ↗</a>
                : <a href={exportUrl({ dateFrom: W.date_from, dateTo: W.date_to, committedOnly: true })} onClick={(e) => e.stopPropagation()} className="border border-emerald-600 text-emerald-700 rounded-lg px-3 py-1.5">⬇ Excel</a>}
              {W.folder && <a href={driveFolder(W.folder)} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} className="text-slate-600 hover:underline">🖼 รูปส่งลูกค้า ↗</a>}
              <span className="text-slate-400">{isOpen(W.week, i) ? '▾' : '▸'}</span>
            </div>
          </button>
          {isOpen(W.week, i) && (
            <div className="px-5 pb-4 space-y-4">
              {W.groups.map((g) => (
                <div key={g.category}>
                  <h3 className="text-sm font-semibold text-slate-700 mb-1">{g.category} <span className="text-slate-400 font-normal">· {g.jobs.length} คน</span></h3>
                  <table className="w-full text-sm">
                    <thead><tr className="text-left text-slate-500 border-b border-slate-200 text-xs">
                      <th className="py-1 pr-3">ไรเดอร์</th><th className="py-1 pr-3 text-right">รูป</th><th className="py-1 pr-3 text-right">งาน</th>
                      <th className="py-1 pr-3 text-right">อนุมัติ</th><th className="py-1 pr-3 text-right">รายได้</th><th className="py-1 pr-3">สถานะ</th><th></th>
                    </tr></thead>
                    <tbody>{g.jobs.map((j) => <JobRow key={j.id} j={j} onOpen={onOpenJob} onRenamed={load} />)}</tbody>
                  </table>
                </div>
              ))}
            </div>
          )}
        </section>
      ))}

      <section className="bg-white rounded-xl border border-slate-200 p-5">
        <button onClick={() => setShowUpload(!showUpload)} className="text-sm text-slate-600 hover:text-slate-900">
          {showUpload ? '▾' : '▸'} อัปโหลดมือ (กรณีไรเดอร์ส่งรูปนอกรอบ / ไม่ได้ผ่าน Drive)
        </button>
        {showUpload && <div className="mt-4 max-w-md"><NewJobForm onCreated={(job) => { onJobCreated(job) }} /></div>}
      </section>
    </div>
  )
}
