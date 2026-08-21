import { useCallback, useEffect, useState } from 'react'
import { api } from './api.js'

function reason(t) {
  if (t.duplicate_of) return { label: 'ซ้ำใน job', cls: 'bg-red-100 text-red-700', tip: t.note || 'booking code ซ้ำกับรูปอื่นใน job เดียวกัน' }
  if (t.seen_in_job) return { label: `เคยอนุมัติแล้ว (job #${t.seen_in_job})`, cls: 'bg-red-100 text-red-700', tip: 'booking code นี้มีแถวที่อนุมัติไปแล้ว — น่าจะเป็นรูปซ้ำ ให้ลบ' }
  if (t.check_status === 'fail') return { label: '✗ เลขขัดกัน', cls: 'bg-red-100 text-red-700', tip: 'เลขในรูปไม่สอดคล้องกัน (net ≠ base+bonus+turbo หรือสองจอไม่ตรง)' }
  if (t.check_status === 'no_data') return { label: '? ข้อมูลไม่พอ', cls: 'bg-amber-100 text-amber-700', tip: 'รูปไม่มีเลขพอให้ตรวจทานกันเอง' }
  if (!t.trip_date) return { label: 'ไม่มีวันที่', cls: 'bg-amber-100 text-amber-700', tip: 'ต้องระบุวันที่ก่อนอนุมัติ' }
  return { label: 'รอคน', cls: 'bg-slate-100 text-slate-600', tip: 'ผ่านการตรวจแต่ยังไม่ได้อนุมัติ' }
}

export default function ReviewQueue({ onOpenJob }) {
  const [rows, setRows] = useState(null)
  const [msg, setMsg] = useState('')
  const [modal, setModal] = useState(null)

  const load = useCallback(() => {
    api.reviewQueue().then((r) => setRows(r.rows)).catch((e) => setMsg(e.message))
  }, [])
  useEffect(() => { load() }, [load])

  const approve = async (t) => {
    try {
      await api.approveTrip(t.id)
      setRows(rows.filter((r) => r.id !== t.id))
    } catch (e) {
      setMsg(e.message)
    }
  }
  const remove = async (t) => {
    if (!confirm(`ลบ ${t.file_name} ออกจากระบบ?`)) return
    try {
      await api.deleteTrip(t.id)
      setRows(rows.filter((r) => r.id !== t.id))
    } catch (e) {
      setMsg(e.message)
    }
  }

  if (!rows) return <p className="text-slate-400">กำลังโหลด...</p>

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <p className="text-sm text-slate-600">
          แถวที่ระบบไม่กล้าอนุมัติเอง — <strong>{rows.length}</strong> รายการจากทุก job ·
          ดูรูปเทียบ แก้ตัวเลขใน job แล้วกดอนุมัติ หรือลบถ้าเป็นรูปซ้ำ
        </p>
        <button onClick={load} className="text-sm text-blue-600 hover:underline">รีเฟรช</button>
      </div>
      {msg && <p className="text-sm text-red-600">⚠️ {msg}</p>}

      {rows.length === 0 ? (
        <div className="bg-white rounded-xl border border-slate-200 p-10 text-center text-slate-400">
          🎉 ไม่มีอะไรรอตรวจ
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-slate-200 overflow-x-auto">
          <table className="w-full text-sm min-w-[1000px]">
            <thead><tr className="text-left text-slate-500 border-b border-slate-200 bg-slate-50">
              <th className="p-2">รูป</th><th className="p-2">เหตุผล</th><th className="p-2">ไรเดอร์ / job</th>
              <th className="p-2">วันที่</th><th className="p-2">จ่าย</th>
              <th className="p-2 text-right">กม.</th><th className="p-2 text-right">รายได้</th>
              <th className="p-2 text-right">ค่าโดยสาร</th><th className="p-2 text-right">ผู้โดยสารจ่าย</th>
              <th className="p-2">Booking</th><th className="p-2"></th>
            </tr></thead>
            <tbody>
              {rows.map((t) => {
                const r = reason(t)
                return (
                  <tr key={t.id} className="border-b border-slate-100 hover:bg-slate-50">
                    <td className="p-2">
                      <button onClick={() => setModal(t)} title={t.file_name}>
                        <img src={`/api/trips/${t.id}/image`} alt="" loading="lazy"
                          className="h-12 w-12 object-cover rounded border border-slate-200 hover:ring-2 hover:ring-blue-400"
                          onError={(e) => { e.currentTarget.style.visibility = 'hidden' }} />
                      </button>
                    </td>
                    <td className="p-2"><span title={r.tip} className={`text-xs rounded-full px-2 py-0.5 cursor-help ${r.cls}`}>{r.label}</span></td>
                    <td className="p-2">
                      <div className="font-medium">{t.driver_name}</div>
                      <button onClick={() => onOpenJob(t.job_id)} className="text-xs text-blue-600 hover:underline">job #{t.job_id} · {t.file_name}</button>
                    </td>
                    <td className="p-2 whitespace-nowrap">{t.trip_date || <span className="text-amber-600">—</span>}</td>
                    <td className="p-2">{t.payment_method}</td>
                    <td className="p-2 text-right tabular-nums">{t.distance_km}</td>
                    <td className="p-2 text-right tabular-nums font-medium">{t.net_earnings}</td>
                    <td className="p-2 text-right tabular-nums">{t.base_fare}</td>
                    <td className="p-2 text-right tabular-nums text-slate-500">{t.passenger_total ?? '—'}</td>
                    <td className="p-2 font-mono text-xs text-slate-500">{t.booking_code || '—'}</td>
                    <td className="p-2 text-right whitespace-nowrap">
                      <button onClick={() => approve(t)} disabled={!t.trip_date}
                        className="bg-emerald-600 hover:bg-emerald-700 disabled:bg-slate-300 text-white rounded px-3 py-1 text-xs mr-2"
                        title={t.trip_date ? 'อนุมัติแถวนี้' : 'ต้องใส่วันที่ใน job ก่อน'}>อนุมัติ</button>
                      <button onClick={() => remove(t)} className="text-slate-400 hover:text-red-600 text-xs">ลบ</button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {modal && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-6" onClick={() => setModal(null)}>
          <div className="bg-white rounded-xl p-3 max-h-full overflow-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex justify-between items-center mb-2 px-1 gap-6">
              <span className="text-sm text-slate-600">{modal.driver_name} · {modal.file_name}{modal.booking_code ? ` · ${modal.booking_code}` : ''}</span>
              <button onClick={() => setModal(null)} className="text-slate-400 hover:text-slate-700 text-xl px-2">✕</button>
            </div>
            <img src={`/api/trips/${modal.id}/image`} alt="" className="max-w-[80vw] max-h-[78vh] rounded-lg" />
            {modal.note && <p className="text-xs text-amber-700 bg-amber-50 rounded p-2 mt-2">⚠️ {modal.note}</p>}
          </div>
        </div>
      )}
    </div>
  )
}
