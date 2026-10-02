import { useCallback, useEffect, useState } from 'react'
import { api, exportUrl } from './api.js'
import Dashboard from './Dashboard.jsx'
import Home from './Home.jsx'
import Icon from './Icon.jsx'
import Overview from './Overview.jsx'
import DataView from './DataView.jsx'
import DupAlbums from './DupAlbums.jsx'
import CloseWeek from './CloseWeek.jsx'
import Login from './Login.jsx'
import NewJobForm from './NewJobForm.jsx'
import ReviewGrid from './ReviewGrid.jsx'
import ReviewQueue from './ReviewQueue.jsx'
import Support from './Support.jsx'

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
  const [view, setView] = useState('overview') // overview | queue | dups | data | close · legacy: home | dashboard
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

  // the vendor's support view: diag key or login, read-only, outside the customer's tabs
  if (window.location.hash === '#support') return <Support />
  if (!auth) return null
  if (!loggedIn) return <Login onLoggedIn={boot} />

  const openJob = (id) => api.job(id).then(setActiveJob)
  // five tabs: what the customer does every week, in the order they do it (redesign 2026-10)
  const NAV = [
    ['overview', 'ภาพรวม', 'overview'], ['queue', 'คิวตรวจ', 'queue'], ['dups', 'งานซ้ำ', 'dups'],
    ['data', 'ข้อมูล', 'data'], ['close', 'ปิดสัปดาห์', 'close'],
  ]
  // the screens from before the redesign stay reachable here until each has a new home
  const LEGACY = [['home', 'การอ่านรูปและสัปดาห์'], ['dashboard', 'Dashboard (เดิม)']]
  const go = (k) => { setActiveJob(null); setView(k); window.scrollTo(0, 0) }
  const logout = () => api.logout().then(() => { setActiveJob(null); boot() })
  const badge = (k) => (k === 'queue' && queueCount ? queueCount : 0)

  return (
    <div className="min-h-screen pb-20 md:pb-0">
      <header className="bg-white border-b border-line">
        <div className="max-w-screen-xl mx-auto px-4 sm:px-8 h-16 flex items-center gap-6 lg:gap-10">
          <button onClick={() => go('overview')} className="flex items-center gap-2.5 shrink-0">
            <span className="w-8 h-8 rounded-lg bg-ink text-white flex items-center justify-center font-semibold">R</span>
            <span className="font-semibold">Rider Photo OCR</span>
          </button>
          <nav aria-label="เมนูหลัก" className="hidden md:flex items-stretch gap-1 h-16">
            {NAV.map(([k, label]) => {
              const on = view === k && !activeJob
              return (
                <button key={k} onClick={() => go(k)} aria-current={on ? 'page' : undefined}
                  className={`flex items-center gap-2 px-3.5 border-b-2 text-[15px] ${on
                    ? 'border-ink text-ink font-semibold' : 'border-transparent text-ink-soft hover:text-ink'}`}>
                  {label}
                  {badge(k) > 0 && <span className="text-xs font-semibold bg-danger text-white rounded-full px-2 py-px">{badge(k).toLocaleString('th-TH')}</span>}
                </button>
              )
            })}
          </nav>
          <div className="ml-auto flex items-center gap-3">
            {health?.excel_append && health.excel_locked && (
              <span className="text-xs bg-danger-bg text-danger-ink rounded px-3 py-1">
                ไฟล์ {health.excel_name} เปิดอยู่ — ปิดก่อนกดบันทึก
              </span>
            )}
            <details className="relative">
              <summary className="list-none cursor-pointer w-10 h-10 rounded-lg flex items-center justify-center text-ink-soft hover:bg-ground"
                aria-label="เมนูเพิ่มเติม"><Icon name="tools" /></summary>
              <div className="absolute right-0 mt-2 w-60 bg-white border border-line rounded-xl shadow-lg py-2 z-30">
                <p className="px-4 py-1 text-xs text-muted">หน้าจอเดิม (กำลังย้ายเข้าแท็บใหม่)</p>
                {LEGACY.map(([k, label]) => (
                  <button key={k} onClick={(e) => { e.currentTarget.closest('details').open = false; go(k) }}
                    className="w-full text-left px-4 py-2.5 text-sm hover:bg-ground">{label}</button>
                ))}
                {auth.auth_required && (
                  <button onClick={logout} className="w-full text-left px-4 py-2.5 text-sm hover:bg-ground border-t border-line-soft mt-1 flex items-center gap-2">
                    <Icon name="logout" size={16} />ออกจากระบบ</button>
                )}
              </div>
            </details>
          </div>
        </div>
      </header>
      {/* phones: the tabs live at the bottom, where a thumb reaches them */}
      <nav aria-label="เมนูหลัก" className="md:hidden fixed bottom-0 inset-x-0 z-20 bg-white border-t border-line grid grid-cols-5 pb-[env(safe-area-inset-bottom)]">
        {NAV.map(([k, label, icon]) => {
          const on = view === k && !activeJob
          return (
            <button key={k} onClick={() => go(k)} aria-current={on ? 'page' : undefined}
              className={`relative min-h-14 flex flex-col items-center justify-center gap-0.5 text-[11px] ${on ? 'text-ink font-semibold' : 'text-ink-soft'}`}>
              <Icon name={icon} size={22} />{label}
              {badge(k) > 0 && <span className="absolute top-1.5 left-[55%] text-[11px] font-semibold bg-danger text-white rounded-full px-1.5">{badge(k)}</span>}
            </button>
          )
        })}
      </nav>

      <main className="max-w-screen-xl mx-auto p-4 sm:px-8 sm:py-7">
        {activeJob ? (
          <ReviewGrid
            job={activeJob}
            health={health}
            onBack={() => { setActiveJob(null); refreshJobs() }}
            onJobUpdate={setActiveJob}
          />
        ) : view === 'overview' ? (
          <Overview onGo={go} />
        ) : view === 'home' ? (
          <Home onOpenJob={openJob} onJobCreated={(job) => { setActiveJob(job); refreshJobs() }} />
        ) : view === 'dashboard' ? (
          <Dashboard onOpenJob={openJob} onGoQueue={() => setView('queue')} />
        ) : view === 'data' ? (
          <DataView onOpenJob={openJob} />
        ) : view === 'queue' ? (
          <ReviewQueue onOpenJob={openJob} />
        ) : view === 'dups' ? (
          <DupAlbums />
        ) : view === 'close' ? (
          <CloseWeek />
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
