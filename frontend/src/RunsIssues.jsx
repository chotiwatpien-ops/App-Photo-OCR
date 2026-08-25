import { useState } from 'react'

// what the team should do about each kind of ingest problem
const HINTS = {
  folder: 'แก้ชื่อ/ตำแหน่งโฟลเดอร์ใน Drive ให้ตรงรูปแบบ (Week D-D Mon / กลุ่มรถ / Admin / NN-ชื่อ) — รอบถัดไประบบจะอ่านให้เอง',
  download: 'โหลดรูปจาก Drive ไม่สำเร็จ — เช็คว่าไฟล์ยังอยู่และแชร์สิทธิ์ถูกต้อง ระบบจะลองใหม่รอบถัดไปอัตโนมัติ',
  process: 'AI อ่านรูปไม่สำเร็จ — เปิด job ดูรูปว่าเสีย/ไม่ใช่สลิปหรือไม่ ถ้าใช่ให้ลบแถวนั้นทิ้ง',
  images: 'อัพโหลดรูปส่งลูกค้าขึ้น Drive ไม่สำเร็จ — มักเป็นปัญหาชั่วคราว ระบบจะลองใหม่รอบถัดไป ถ้าค้างหลายรอบแจ้งแอดมินระบบ',
  xlsx: 'อัพโหลดไฟล์ Excel ขึ้น Drive ไม่สำเร็จ — มักเป็นปัญหาชั่วคราว ระบบจะลองใหม่รอบถัดไป ถ้าค้างหลายรอบแจ้งแอดมินระบบ',
}
export const hintFor = (kind) => HINTS[kind] || 'ดูรายละเอียดในข้อความ แล้วแก้ที่ต้นทาง — หายเมื่อรอบถัดไปไม่เจอซ้ำ'

const ts = (s) => (s || '').replace('T', ' ')

export function RunsOverview({ runs }) {
  const [open, setOpen] = useState(false)
  if (!runs?.length) return null
  const shown = open ? runs : runs.slice(0, 3)
  return (
    <section className="bg-white rounded-xl border border-slate-200 p-5">
      <h2 className="font-semibold mb-2">รอบดูดรูปที่ผ่านมา</h2>
      <table className="w-full text-sm">
        <thead><tr className="text-left text-slate-500 border-b border-slate-200 text-xs">
          <th className="py-1 pr-3">เวลา</th><th className="py-1 pr-3">ผล</th>
          <th className="py-1 pr-3 text-right">รูปใหม่</th><th className="py-1 pr-3 text-right">อนุมัติอัตโนมัติ</th>
          <th className="py-1 pr-3 text-right">รอคน</th><th className="py-1 text-right">ปัญหา</th>
        </tr></thead>
        <tbody>
          {shown.map((r) => {
            const running = !r.finished_at
            const cancelled = (r.notes || '').includes('ไม่จบตามปกติ')
            const pass = !running && !cancelled && !r.errors
            return (
              <tr key={r.id} className="border-b border-slate-100">
                <td className="py-1.5 pr-3 whitespace-nowrap">{ts(r.started_at)}</td>
                <td className="py-1.5 pr-3">
                  {running
                    ? <span className="text-xs rounded-full px-2 py-0.5 bg-amber-100 text-amber-700">● กำลังรัน</span>
                    : cancelled
                      ? <span className="text-xs rounded-full px-2 py-0.5 bg-slate-200 text-slate-600" title="รอบนี้ถูกยกเลิก/ถูกตัดกลางทาง — งานที่ค้างถูกรอบถัดไปเก็บให้แล้ว">⊘ ถูกตัดกลางทาง</span>
                      : pass
                        ? <span className="text-xs rounded-full px-2 py-0.5 bg-emerald-100 text-emerald-700">✓ ผ่าน</span>
                        : <span className="text-xs rounded-full px-2 py-0.5 bg-red-100 text-red-700">✗ มีปัญหา</span>}
                </td>
                <td className="py-1.5 pr-3 text-right tabular-nums">{r.files_new}{running && r.files_total ? <span className="text-slate-400">/{r.files_total}</span> : ''}</td>
                <td className="py-1.5 pr-3 text-right tabular-nums text-emerald-700">{r.auto_approved}</td>
                <td className={`py-1.5 pr-3 text-right tabular-nums ${r.flagged ? 'text-amber-600' : 'text-slate-400'}`}>{r.flagged}</td>
                <td className={`py-1.5 text-right tabular-nums ${r.errors ? 'text-red-600 font-medium' : 'text-slate-400'}`}>{r.errors || '—'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {runs.length > 3 && (
        <button onClick={() => setOpen(!open)} className="mt-2 text-xs text-blue-600 hover:underline">
          {open ? '▾ ย่อ' : `▸ ดูทั้งหมด ${runs.length} รอบ`}
        </button>
      )}
    </section>
  )
}

export function IssuesPanel({ issues }) {
  const [showResolved, setShowResolved] = useState(false)
  if (!issues?.length) return null
  const open = issues.filter((i) => !i.resolved_at)
  const resolved = issues.filter((i) => i.resolved_at)
  if (!open.length && !resolved.length) return null
  return (
    <section className="bg-white rounded-xl border border-slate-200 p-5 space-y-2">
      <h2 className="font-semibold">
        ปัญหาจากการดูดรูป
        {open.length
          ? <span className="ml-2 text-xs rounded-full px-2 py-0.5 bg-red-100 text-red-700">{open.length} ค้างอยู่</span>
          : <span className="ml-2 text-xs rounded-full px-2 py-0.5 bg-emerald-100 text-emerald-700">ไม่มีค้าง 🎉</span>}
      </h2>
      {open.map((i) => (
        <div key={i.id} className="border border-red-200 bg-red-50 rounded-lg p-3 text-sm">
          <p className="text-red-800">⚠ {i.message}</p>
          <p className="text-xs text-red-600 mt-1">แก้ยังไง: {hintFor(i.kind)}</p>
          <p className="text-[11px] text-slate-500 mt-1">เจอครั้งแรกรอบ #{i.first_run} · เจอซ้ำ {i.times_seen} รอบ · ล่าสุดรอบ #{i.last_run}</p>
        </div>
      ))}
      {resolved.length > 0 && (
        <div>
          <button onClick={() => setShowResolved(!showResolved)} className="text-xs text-slate-500 hover:underline">
            {showResolved ? '▾' : '▸'} แก้แล้ว {resolved.length} เรื่อง (log เก็บไว้)
          </button>
          {showResolved && resolved.map((i) => (
            <div key={i.id} className="border border-slate-200 bg-slate-50 rounded-lg p-2.5 text-xs text-slate-500 mt-1.5">
              <span className="text-emerald-600 mr-1">✓</span>{i.message}
              <span className="ml-2 text-slate-400">— หายไปเองรอบ #{i.resolved_run} ({ts(i.resolved_at)}) · เคยเจอ {i.times_seen} รอบ</span>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
