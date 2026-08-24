import { useCallback, useEffect, useState } from 'react'
import { api, exportUrl } from './api.js'
import NewJobForm from './NewJobForm.jsx'
import { RunsOverview, IssuesPanel } from './RunsIssues.jsx'

const fmt = (n) => (n ?? 0).toLocaleString('th-TH', { maximumFractionDigits: 0 })
const driveFile = (id) => `https://drive.google.com/file/d/${id}/view`
const driveFolder = (id) => `https://drive.google.com/drive/folders/${id}`

function RunStatus({ run, canTrigger, onTriggered }) {
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
            {(run.started_at || '').replace('T', ' ')} · รูปใหม่ {run.files_new} · อนุมัติอัตโนมัติ {run.auto_approved} · รอคน {run.flagged}
            {run.errors ? <span className="text-red-600"> · error {run.errors}</span> : ''}
          </p>
        ) : <p className="text-sm text-slate-400 mt-1">ยังไม่เคยรัน</p>}
        {run?.notes && <p className="text-xs text-amber-700 mt-1 whitespace-pre-line">⚠ {run.notes}</p>}
        {msg && <p className="text-xs text-slate-600 mt-1">{msg}</p>}
      </div>
      <div className="text-right text-xs text-slate-500">
        <p>ตั้งเวลา: ทุกวัน 08:00 / 11:00 / 14:00 / 17:00 / 20:00</p>
        <button onClick={trigger} disabled={busy || running || !canTrigger}
          title={canTrigger ? 'สั่ง GitHub Actions รันทันที' : 'ยังไม่ได้ตั้งค่า GITHUB_TOKEN — รันได้จากแท็บ Actions บน GitHub'}
          className="mt-1 bg-slate-900 hover:bg-slate-700 disabled:bg-slate-300 text-white rounded-lg px-4 py-2 text-sm font-medium">
          {busy ? 'กำลังสั่ง…' : running ? 'กำลังรันอยู่' : '▶ ดูดรูปตอนนี้'}
        </button>
      </div>
    </section>
  )
}

function JobRow({ j, onOpen }) {
  const st = j.pending ? ['กำลังอ่าน', 'bg-amber-100 text-amber-700']
    : j.waiting ? [`รอคน ${j.waiting}`, 'bg-red-100 text-red-700']
    : j.done ? ['ครบ', 'bg-emerald-100 text-emerald-700'] : ['ว่าง', 'bg-slate-100 text-slate-500']
  return (
    <tr className="border-b border-slate-100 hover:bg-slate-50">
      <td className="py-1.5 pr-3 font-medium">{j.driver_name}
        {!j.category && <span className="ml-2 text-[10px] text-slate-400 border border-slate-200 rounded px-1">มือ</span>}
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
      <RunStatus run={data.last_run} canTrigger={data.can_trigger} onTriggered={() => setTimeout(load, 3000)} />
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
                    <tbody>{g.jobs.map((j) => <JobRow key={j.id} j={j} onOpen={onOpenJob} />)}</tbody>
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
