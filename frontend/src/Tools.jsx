import { useEffect, useState } from 'react'
import { api } from './api.js'
import Icon from './Icon.jsx'
import NewJobForm from './NewJobForm.jsx'

// เครื่องมือเพิ่มเติม — what is needed now and then, kept off the five tabs (redesign 2026-10):
// the all-weeks workbooks, pushing them to Drive without waiting for a round, uploading a rider's
// pictures by hand, and the screens from before the redesign for whoever still needs them.

const fmt = (n) => (n ?? 0).toLocaleString('th-TH')

function Card({ title, sub, children }) {
  return (
    <section className="bg-white border border-line rounded-xl p-4 sm:px-6 sm:py-5 flex flex-col gap-3">
      <div>
        <h2 className="text-[17px] font-semibold">{title}</h2>
        {sub && <p className="text-sm text-muted">{sub}</p>}
      </div>
      {children}
    </section>
  )
}

function Sync() {
  const [st, setSt] = useState(null)
  const [msg, setMsg] = useState('')
  useEffect(() => { api.exportSyncStatus().then(setSt).catch(() => {}) }, [])
  useEffect(() => {
    if (st?.state !== 'running') return undefined
    const t = setInterval(() => api.exportSyncStatus().then(setSt).catch(() => {}), 3000)
    return () => clearInterval(t)
  }, [st?.state])
  const start = () => { setMsg(''); api.exportSync().then(setSt).catch((e) => setMsg(e.message)) }
  const running = st?.state === 'running'
  return (
    <div className="flex flex-wrap items-center gap-3">
      <button onClick={start} disabled={running}
        className="min-h-11 px-4 rounded-lg border border-line bg-white hover:bg-ground text-sm flex items-center gap-2 disabled:opacity-50">
        <Icon name="refresh" size={18} />{running ? 'กำลังเขียนขึ้น Drive…' : 'เขียนไฟล์ขึ้น Drive ตอนนี้'}
      </button>
      {st?.state === 'done' && (
        <span className="text-sm text-ok-ink">
          {st.unchanged ? `ไม่มีอะไรเปลี่ยนตั้งแต่ครั้งก่อน (${st.finished_at?.slice(11, 16)})`
            : `ขึ้น Drive แล้ว ${st.finished_at?.slice(11, 16)} · ${fmt(st.rows)} แถว`}
        </span>
      )}
      {st?.state === 'error' && <span className="text-sm text-danger-ink">เขียนไม่สำเร็จ: {st.error}</span>}
      {msg && <span className="text-sm text-danger-ink">{msg}</span>}
    </div>
  )
}

export default function Tools({ onGo, onJobCreated }) {
  const files = [
    ['Rider Trips.xlsx', 'ทุกสัปดาห์ · template เดิม 17 คอลัมน์', '/api/export'],
    ['Rider Trips Phase 2.xlsx', 'ทุกสัปดาห์ · มีที่อยู่รับ-ส่งจริง', '/api/export/phase2'],
    ['Rider Trips Phase 3.xlsx', 'ทุกสัปดาห์ · มีทุกบรรทัดค่าโดยสารผู้โดยสาร', '/api/export/phase3'],
  ]
  return (
    <div className="flex flex-col gap-5">
      <div>
        <p className="text-sm text-muted">ใช้นานๆ ครั้ง</p>
        <h1 className="text-2xl sm:text-[28px] font-semibold tracking-tight">เครื่องมือเพิ่มเติม</h1>
      </div>

      <Card title="ไฟล์รวมทุกสัปดาห์" sub="สร้างจากข้อมูลล่าสุดตอนกด · ไฟล์ของสัปดาห์เดียวอยู่ที่แท็บปิดสัปดาห์">
        <div className="grid gap-3 sm:grid-cols-3">
          {files.map(([name, sub, href]) => (
            <a key={href} href={href} className="border border-line rounded-xl px-4 py-3.5 hover:bg-ground flex flex-col gap-1">
              <span className="font-medium break-words">{name}</span>
              <span className="text-sm text-muted">{sub}</span>
              <span className="mt-1 text-sm text-accent flex items-center gap-1.5"><Icon name="download" size={16} />ดาวน์โหลด</span>
            </a>
          ))}
        </div>
        <p className="text-sm text-muted">ระบบเขียนไฟล์เหล่านี้ขึ้น Drive เองทุกรอบอ่านรูป ถ้าเพิ่งอนุมัติแล้วอยากให้ใน Drive ตรงทันที กดปุ่มนี้</p>
        <Sync />
      </Card>

      <Card title="อัปโหลดรูปเอง" sub="กรณีไรเดอร์ส่งรูปนอกรอบ หรือไม่ได้ผ่าน Google Drive">
        <NewJobForm onCreated={onJobCreated} />
      </Card>

      <Card title="หน้าจอเดิม" sub="หน้าจอก่อนปรับใหม่ ยังเปิดได้สำหรับผู้ดูแลระบบ">
        <div className="flex flex-wrap gap-2">
          <button onClick={() => onGo('home')} className="min-h-11 px-4 rounded-lg border border-line bg-white hover:bg-ground text-sm">
            การอ่านรูปและรายชื่อรายสัปดาห์
          </button>
          <button onClick={() => onGo('dashboard')} className="min-h-11 px-4 rounded-lg border border-line bg-white hover:bg-ground text-sm">
            Dashboard รายโฟลเดอร์
          </button>
        </div>
      </Card>
    </div>
  )
}
