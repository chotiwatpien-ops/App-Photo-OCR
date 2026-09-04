import { useCallback, useEffect, useState } from 'react'
import { api, exportUrl } from './api.js'
import Dashboard from './Dashboard.jsx'
import Home from './Home.jsx'
import DataView from './DataView.jsx'
import Login from './Login.jsx'
import NewJobForm from './NewJobForm.jsx'
import ReviewGrid from './ReviewGrid.jsx'
import ReviewQueue from './ReviewQueue.jsx'

const STATUS_TH = {
  running: { label: 'กำลังอ่านรูป', cls: 'bg-amber-100 text-amber-700' },
  review: { label: 'รอตรวจสอบ', cls: 'bg-blue-100 text-blue-700' },
  committed: { label: 'อนุมัติแล้ว', cls: 'bg-emerald-100 text-emerald-700' },
}

function ExportBar() {
  const [drivers, setDrivers] = useState([])
  const [driver, setDriver] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  useEffect(() => { api.drivers().then((r) => setDrivers(r.drivers)).catch(() => {}) }, [])
  const href = exportUrl({ dateFrom: from, dateTo: to, driver, committedOnly: true })
  return (
    <section className="bg-white rounded-xl shadow-sm border border-slate-200 p-5">
      <h2 className="font-semibold mb-3">ดาวน์โหลด Excel (เฉพาะที่อนุมัติแล้ว)</h2>
      <div className="flex flex-wrap items-end gap-3 text-sm">
        <label className="block">
          <span className="block text-slate-600 mb-1">ไรเดอร์</span>
          <select value={driver} onChange={(e) => setDriver(e.target.value)}
            className="border border-slate-300 rounded-lg px-3 py-2 bg-white min-w-48">
            <option value="">ทุกคน</option>
            {drivers.map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="block text-slate-600 mb-1">ตั้งแต่</span>
          <input type="date" value={from} onChange={(e) => setFrom(e.target.value)}
            className="border border-slate-300 rounded-lg px-3 py-2" />
        </label>
        <label className="block">
          <span className="block text-slate-600 mb-1">ถึง</span>
          <input type="date" value={to} onChange={(e) => setTo(e.target.value)}
            className="border border-slate-300 rounded-lg px-3 py-2" />
        </label>
        <a href={href}
          className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg px-4 py-2 font-medium">
          ⬇ ดาวน์โหลด .xlsx
        </a>
      </div>
    </section>
  )
}

export default function App() {
  const [auth, setAuth] = useState(null) // {auth_required, logged_in}
  const [health, setHealth] = useState(null)
  const [jobList, setJobList] = useState([])
  const [activeJob, setActiveJob] = useState(null)
  const [view, setView] = useState('home') // home | jobs | dashboard | data | queue
  const [queueCount, setQueueCount] = useState(0)

  const refreshJobs = useCallback(() => {
    api.jobs().then((r) => setJobList(r.jobs)).catch(() => {})
  }, [])

  const boot = useCallback(() => {
    api.me().then(setAuth).catch(() => setAuth({ auth_required: false, logged_in: true }))
  }, [])

  useEffect(() => { boot() }, [boot])

  useEffect(() => {
    const onNeedLogin = () => setAuth((a) => ({ ...(a || {}), auth_required: true, logged_in: false }))
    window.addEventListener('pocr:login-required', onNeedLogin)
    return () => window.removeEventListener('pocr:login-required', onNeedLogin)
  }, [])

  const loggedIn = auth && (!auth.auth_required || auth.logged_in)

  useEffect(() => {
    if (!loggedIn) return
    api.health().then(setHealth).catch(() => setHealth({ ok: false }))
    refreshJobs()
    api.reviewQueue().then((r) => setQueueCount(r.rows.length)).catch(() => {})
  }, [loggedIn, refreshJobs, view, activeJob])

  // poll active job while extraction is running
  useEffect(() => {
    if (!activeJob || activeJob.status !== 'running') return
    const t = setInterval(() => {
      api.job(activeJob.id).then(setActiveJob).catch(() => {})
    }, 1500)
    return () => clearInterval(t)
  }, [activeJob])

  if (!auth) return null
  if (!loggedIn) return <Login onLoggedIn={boot} />

  const openJob = (id) => api.job(id).then(setActiveJob)
  const NAV = [
    ['home', 'หน้าหลัก'], ['queue', `คิวตรวจ${queueCount ? ` (${queueCount})` : ''}`],
    ['data', 'ข้อมูลทั้งหมด'], ['dashboard', 'Dashboard'],
  ]
  const logout = () => api.logout().then(() => { setActiveJob(null); boot() })

  return (
    <div className="min-h-screen">
      <header className="bg-slate-900 text-white px-6 py-3 flex items-center justify-between shadow">
        <div className="flex items-center gap-3">
          <span className="text-2xl">📸</span>
          <div>
            <h1 className="font-semibold text-lg leading-tight">Rider Photo OCR</h1>
            <p className="text-xs text-slate-400">
              Google Drive → AI → Excel{health?.model ? ` · ${health.model}` : ''}
            </p>
          </div>
        </div>
        <nav className="hidden md:flex items-center gap-1 text-sm">
          {NAV.map(([k, label]) => (
            <button key={k} onClick={() => { setActiveJob(null); setView(k) }}
              className={`px-3 py-1.5 rounded-lg ${view === k && !activeJob ? 'bg-white/15 text-white' : 'text-slate-300 hover:text-white hover:bg-white/10'}`}>
              {label}
            </button>
          ))}
        </nav>
        <div className="flex items-center gap-3">
          {health?.excel_append && health.excel_locked && (
            <span className="text-xs bg-red-500/20 text-red-300 border border-red-500/40 rounded px-3 py-1">
              ⚠️ ไฟล์ {health.excel_name} เปิดอยู่ — ปิดก่อนกดบันทึก
            </span>
          )}
          {auth.auth_required && (
            <button onClick={logout} className="text-xs text-slate-300 hover:text-white">ออกจากระบบ</button>
          )}
        </div>
      </header>

      <main className="max-w-screen-2xl mx-auto p-6">
        {activeJob ? (
          <ReviewGrid
            job={activeJob}
            health={health}
            onBack={() => { setActiveJob(null); refreshJobs() }}
            onJobUpdate={setActiveJob}
          />
        ) : view === 'home' ? (
          <Home onOpenJob={openJob} onJobCreated={(job) => { setActiveJob(job); refreshJobs() }} />
        ) : view === 'dashboard' ? (
          <Dashboard onOpenJob={openJob} onGoQueue={() => setView('queue')} />
        ) : view === 'data' ? (
          <DataView onOpenJob={openJob} />
        ) : view === 'queue' ? (
          <ReviewQueue onOpenJob={openJob} />
        ) : (
          <div className="grid gap-6 lg:grid-cols-[420px_1fr]">
            <NewJobForm onCreated={(job) => { setActiveJob(job); refreshJobs() }} />
            <div className="space-y-6">
              <section className="bg-white rounded-xl shadow-sm border border-slate-200 p-5">
                <h2 className="font-semibold mb-3">งานล่าสุด</h2>
                {jobList.length === 0 ? (
                  <p className="text-sm text-slate-400">ยังไม่มีงาน — เริ่มจากอัปโหลดรูปด้านซ้าย</p>
                ) : (
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-slate-500 border-b border-slate-200">
                        <th className="py-2 pr-3">#</th>
                        <th className="py-2 pr-3">ไรเดอร์</th>
                        <th className="py-2 pr-3">ช่วงวันที่</th>
                        <th className="py-2 pr-3">รูป</th>
                        <th className="py-2 pr-3">สถานะ</th>
                        <th className="py-2"></th>
                      </tr>
                    </thead>
                    <tbody>
                      {jobList.map((j) => {
                        const st = STATUS_TH[j.status] || { label: j.status, cls: 'bg-slate-100' }
                        return (
                          <tr key={j.id} className="border-b border-slate-100 hover:bg-slate-50">
                            <td className="py-2 pr-3 text-slate-400">{j.id}</td>
                            <td className="py-2 pr-3 font-medium">{j.driver_name}</td>
                            <td className="py-2 pr-3 text-slate-500">{j.date_from} → {j.date_to}</td>
                            <td className="py-2 pr-3">
                              {j.done_count}/{j.trip_count}
                              {j.error_count > 0 && <span className="text-red-500 ml-1">({j.error_count} พลาด)</span>}
                            </td>
                            <td className="py-2 pr-3">
                              <span className={`text-xs rounded-full px-2 py-0.5 ${st.cls}`}>{st.label}</span>
                            </td>
                            <td className="py-2 text-right whitespace-nowrap">
                              <a href={exportUrl({ jobId: j.id, committedOnly: false })}
                                className="text-emerald-700 hover:underline text-sm mr-3" title="ดาวน์โหลด Excel ของ job นี้">⬇ Excel</a>
                              <button onClick={() => openJob(j.id)} className="text-blue-600 hover:underline text-sm">เปิด</button>
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                )}
              </section>
              <ExportBar />
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
