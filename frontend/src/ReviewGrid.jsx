import { useMemo, useState } from 'react'
import { api, exportUrl } from './api.js'

const SERVICE_OPTIONS = ['Saver Bike', 'Standard Bike', 'Saver Car', 'Standard Car']
const PAYMENT_OPTIONS = ['CASH', 'GRAB PAY', 'QR PAY', 'UNKNOWN']
const PROVINCE_OPTIONS = ['BKK', 'NBI', 'PTE', 'SPK', 'SKN', 'NPT', 'CBI', 'AYA', 'OTHER']

const THAI_DAYS = ['อา', 'จ', 'อ', 'พ', 'พฤ', 'ศ', 'ส']

function localISO(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function dateRange(from, to) {
  const out = []
  const d = new Date(from + 'T00:00:00')
  const end = new Date(to + 'T00:00:00')
  while (d <= end && out.length < 62) {
    out.push(localISO(d))  // not toISOString(): UTC conversion shifts Thai dates back a day
    d.setDate(d.getDate() + 1)
  }
  return out
}

function fmtDateOption(iso) {
  const d = new Date(iso + 'T00:00:00')
  return `${THAI_DAYS[d.getDay()]} ${d.getDate()}/${d.getMonth() + 1}`
}

function TripExtras({ trip }) {
  return (
    <>
      {trip.surge ? <span title="งาน Surge (Higher due to surge)">🔥</span> : null}
      {trip.queue_type ? (
        <span title={`คิว: ${trip.queue_type}`} className="text-[10px] rounded-full px-1.5 py-0.5 bg-orange-100 text-orange-700">
          {trip.queue_type}
        </span>
      ) : null}
    </>
  )
}

function CheckBadge({ trip }) {
  if (trip.auto_approved) {
    return <span title="ผ่านทุกการตรวจ — อนุมัติอัตโนมัติโดยระบบ ingest" className="text-xs rounded-full px-2 py-0.5 bg-emerald-100 text-emerald-700 cursor-help">✓ auto</span>
  }
  if (trip.duplicate_of) {
    return <span title={trip.note || 'รูปซ้ำ'} className="text-xs rounded-full px-2 py-0.5 bg-red-100 text-red-700 cursor-help">ซ้ำ</span>
  }
  const map = {
    pass: { label: '✓', cls: 'bg-emerald-100 text-emerald-700', tip: 'เลขในรูปตรวจทานกันเองแล้วตรงกัน' },
    fail: { label: '✗', cls: 'bg-red-100 text-red-700', tip: 'เลขในรูปขัดแย้งกันเอง — ตรวจแถวนี้' },
    no_data: { label: '?', cls: 'bg-amber-100 text-amber-700', tip: 'รูปไม่มีข้อมูลพอให้ตรวจทาน — ดูด้วยตา' },
  }
  const b = map[trip.check_status]
  if (!b) return null
  return <span title={b.tip} className={`text-xs rounded-full px-2 py-0.5 cursor-help ${b.cls}`}>{b.label}</span>
}

export default function ReviewGrid({ job, health, onBack, onJobUpdate }) {
  const appendsToFile = !!health?.excel_append
  const [modalTrip, setModalTrip] = useState(null)
  const [committing, setCommitting] = useState(false)
  const [msg, setMsg] = useState(null) // {type:'ok'|'err', text}
  const [bulkDate, setBulkDate] = useState('')

  const dates = useMemo(() => dateRange(job.date_from, job.date_to), [job.date_from, job.date_to])
  const trips = useMemo(() => {
    // group same-day trips together: sort by screen time, unknown times last
    return [...(job.trips || [])].sort((a, b) => {
      const ta = a.trip_time || '99:99'
      const tb = b.trip_time || '99:99'
      return ta === tb ? a.id - b.id : ta.localeCompare(tb)
    })
  }, [job.trips])
  const done = trips.filter((t) => t.status === 'done')
  const waiting = done.filter((t) => !t.committed)
  const pending = trips.filter((t) => t.status === 'pending')
  const errors = trips.filter((t) => t.status === 'error')
  const totalNet = done.reduce((s, t) => s + (t.net_earnings || 0), 0)
  const missingDates = waiting.filter((t) => !t.trip_date).length
  const passCount = done.filter((t) => t.check_status === 'pass' && !t.duplicate_of).length
  const attnCount = done.length - passCount
  const isCommitted = job.status === 'committed'
  const locked = (t) => isCommitted || !!t.committed

  const patch = async (tripId, fields) => {
    try {
      const updated = await api.patchTrip(tripId, fields)
      onJobUpdate({ ...job, trips: trips.map((t) => (t.id === tripId ? updated : t)) })
    } catch (e) {
      setMsg({ type: 'err', text: e.message })
    }
  }

  const removeTrip = async (tripId) => {
    if (!confirm('ลบรายการนี้?')) return
    try {
      await api.deleteTrip(tripId)
      onJobUpdate({ ...job, trips: trips.filter((t) => t.id !== tripId) })
    } catch (e) {
      setMsg({ type: 'err', text: e.message })
    }
  }

  const commit = async (force = false) => {
    setMsg(null)
    setCommitting(true)
    try {
      const r = await api.commit(job.id, force)
      setMsg({
        type: 'ok',
        text: r.file
          ? `บันทึก ${r.written} รายการลงไฟล์ ${r.file} เรียบร้อย ✅`
          : `อนุมัติ ${r.written} รายการแล้ว ✅ กด "⬇ Excel" เพื่อดาวน์โหลด`,
      })
      onJobUpdate({ ...job, status: 'committed' })
    } catch (e) {
      if (!force && e.message.includes('บันทึกซ้ำ')) {
        if (confirm(`⚠️ ${e.message}\n\nยืนยันบันทึกซ้ำหรือไม่?`)) {
          setCommitting(false)
          return commit(true)
        }
      }
      setMsg({ type: 'err', text: e.message })
    } finally {
      setCommitting(false)
    }
  }

  const bulkAssignDate = async (onlyEmpty) => {
    if (!bulkDate) return
    const targets = waiting.filter((t) => (onlyEmpty ? !t.trip_date : true))
    if (targets.length === 0) return
    try {
      const updated = await Promise.all(targets.map((t) => api.patchTrip(t.id, { trip_date: bulkDate })))
      const byId = Object.fromEntries(updated.map((u) => [u.id, u]))
      onJobUpdate({ ...job, trips: trips.map((t) => byId[t.id] || t) })
    } catch (e) {
      setMsg({ type: 'err', text: e.message })
    }
  }

  const textCell = (t, field, w = 'w-24', placeholder = '') => (
    <input
      key={`${t.id}:${field}:${t[field]}`}
      defaultValue={t[field] ?? ''}
      placeholder={placeholder}
      disabled={locked(t)}
      onBlur={(e) => e.target.value !== (t[field] ?? '') && patch(t.id, { [field]: e.target.value || null })}
      className={`${w} border border-slate-200 rounded px-2 py-1 text-sm bg-white disabled:bg-slate-50 disabled:text-slate-400`}
    />
  )

  const numCell = (t, field, w = 'w-20') => (
    <input
      key={`${t.id}:${field}:${t[field]}`}
      type="number" step="any"
      defaultValue={t[field] ?? ''}
      disabled={locked(t)}
      onBlur={(e) => {
        const v = e.target.value === '' ? null : Number(e.target.value)
        if (v !== t[field]) patch(t.id, { [field]: v })
      }}
      className={`${w} border border-slate-200 rounded px-2 py-1 text-right text-sm bg-white disabled:bg-slate-50 disabled:text-slate-400`}
    />
  )

  const selCell = (t, field, options, w = 'w-28') => (
    <select
      value={t[field] ?? ''}
      disabled={locked(t)}
      onChange={(e) => patch(t.id, { [field]: e.target.value })}
      className={`${w} border border-slate-200 rounded px-1.5 py-1 text-sm bg-white disabled:bg-slate-50 disabled:text-slate-400`}
    >
      {!options.includes(t[field]) && <option value={t[field] ?? ''}>{t[field] ?? '—'}</option>}
      {options.map((o) => <option key={o} value={o}>{o}</option>)}
    </select>
  )

  return (
    <div>
      <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
        <div className="flex items-center gap-4">
          <button onClick={onBack} className="text-sm text-blue-600 hover:underline">← กลับ</button>
          <div>
            <h2 className="font-semibold text-lg">{job.driver_name}</h2>
            <p className="text-sm text-slate-500">
              {job.date_from} → {job.date_to} · {trips.length} รูป
            </p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <div className="text-right text-sm">
            <p className="text-slate-500">รวมรายได้ที่อ่านได้</p>
            <p className="font-semibold text-emerald-600 text-lg">฿{totalNet.toLocaleString()}</p>
            {done.length > 0 && (
              <p className="text-xs text-slate-500">
                ✓ ผ่านตรวจ {passCount}{attnCount > 0 && <span className="text-amber-600"> · ต้องดู {attnCount}</span>}
              </p>
            )}
          </div>
          <a
            href={exportUrl({ jobId: job.id, committedOnly: false })}
            className="border border-emerald-600 text-emerald-700 hover:bg-emerald-50 rounded-lg px-4 py-2.5 text-sm font-medium"
            title="ดาวน์โหลด Excel ของ job นี้ (รวมแถวที่ยังไม่อนุมัติ)"
          >⬇ Excel</a>
          <button
            onClick={() => commit()}
            disabled={committing || isCommitted || pending.length > 0 || waiting.length === 0 || missingDates > 0}
            className="bg-emerald-600 hover:bg-emerald-700 disabled:bg-slate-300 text-white rounded-lg px-5 py-2.5 text-sm font-medium"
          >
            {isCommitted ? 'อนุมัติแล้ว ✓'
              : committing ? 'กำลังบันทึก...'
              : appendsToFile ? `อนุมัติ + บันทึกลง Excel (${waiting.length})` : `อนุมัติ (${waiting.length})`}
          </button>
        </div>
      </div>

      {pending.length > 0 && (
        <div className="mb-4 bg-white border border-slate-200 rounded-xl p-4">
          <div className="flex justify-between text-sm mb-2">
            <span>กำลังอ่านรูปด้วย AI...</span>
            <span className="text-slate-500">{done.length + errors.length}/{trips.length}</span>
          </div>
          <div className="h-2 bg-slate-200 rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-500 transition-all duration-500"
              style={{ width: `${((done.length + errors.length) / Math.max(trips.length, 1)) * 100}%` }}
            />
          </div>
        </div>
      )}

      {!isCommitted && done.length > 0 && (
        <div className="mb-3 flex items-center gap-2 flex-wrap bg-white border border-slate-200 rounded-lg px-4 py-2 text-sm">
          <span className="text-slate-600">📅 ใส่วันที่ทีเดียว:</span>
          <select
            value={bulkDate}
            onChange={(e) => setBulkDate(e.target.value)}
            className="border border-slate-300 rounded px-2 py-1 bg-white"
          >
            <option value="">— เลือกวันที่ —</option>
            {dates.map((d) => <option key={d} value={d}>{fmtDateOption(d)}</option>)}
          </select>
          <button
            onClick={() => bulkAssignDate(true)}
            disabled={!bulkDate || missingDates === 0}
            className="border border-blue-300 text-blue-700 hover:bg-blue-50 disabled:opacity-40 rounded px-3 py-1"
          >ใส่ให้แถวที่ยังว่าง ({missingDates})</button>
          <button
            onClick={() => bulkAssignDate(false)}
            disabled={!bulkDate}
            className="border border-slate-300 text-slate-600 hover:bg-slate-50 disabled:opacity-40 rounded px-3 py-1"
          >ใส่ให้ทุกแถว</button>
          {missingDates > 0 && (
            <span className="text-amber-700">ยังไม่ได้เลือกวันที่ {missingDates} รายการ (วันที่ไม่มีในรูป ต้องเลือกเอง)</span>
          )}
        </div>
      )}
      {msg && (
        <p className={`mb-3 text-sm rounded-lg px-4 py-2 border ${
          msg.type === 'ok'
            ? 'text-emerald-700 bg-emerald-50 border-emerald-200'
            : 'text-red-700 bg-red-50 border-red-200'
        }`}>{msg.text}</p>
      )}

      <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-x-auto">
        <table className="w-full text-sm min-w-[1100px]">
          <thead>
            <tr className="text-left text-slate-500 border-b border-slate-200 bg-slate-50">
              <th className="p-2">รูป</th>
              <th className="p-2" title="ตรวจทานเลขในรูปกันเองอัตโนมัติ">ตรวจ</th>
              <th className="p-2">วันที่ *</th>
              <th className="p-2">เวลา</th>
              <th className="p-2">Service</th>
              <th className="p-2">จ่ายด้วย</th>
              <th className="p-2">รับ</th>
              <th className="p-2">ส่ง</th>
              <th className="p-2 text-right">กม.</th>
              <th className="p-2 text-right">นาที</th>
              <th className="p-2 text-right">รายได้</th>
              <th className="p-2 text-right">ค่าโดยสาร</th>
              <th className="p-2 text-right">โบนัส</th>
              <th className="p-2 text-right">Turbo</th>
              <th className="p-2 text-right">ทางด่วน</th>
              <th className="p-2 text-right" title="รวมค่าโดยสารของผู้โดยสาร (คอลัมน์ P)">ผู้โดยสารจ่าย</th>
              <th className="p-2 text-right" title="คำนวณ: ผู้โดยสารจ่าย − ค่าโดยสาร (คอลัมน์ Q)">ค่าคอม</th>
              <th className="p-2">เขตรับ</th>
              <th className="p-2">เขตส่ง</th>
              <th className="p-2 text-right" title="เงินคืนค่าโดยสาร">เงินคืน</th>
              <th className="p-2"></th>
            </tr>
          </thead>
          <tbody>
            {trips.map((t) => (
              <tr key={t.id} className={`border-b border-slate-100 ${
                t.status === 'error' || t.duplicate_of ? 'bg-red-50'
                  : t.status === 'pending' ? 'bg-slate-50 opacity-60'
                  : t.check_status === 'fail' ? 'bg-red-50/50' : ''
              }`}>
                <td className="p-2">
                  <button onClick={() => t.status !== 'pending' && setModalTrip(t)} title={t.file_name + (t.booking_code ? ` · ${t.booking_code}` : '')}>
                    <img
                      src={`/api/trips/${t.id}/image`}
                      alt={t.file_name}
                      className="h-14 w-14 object-cover rounded-lg border border-slate-200 hover:ring-2 hover:ring-blue-400"
                      loading="lazy"
                    />
                  </button>
                </td>
                {t.status === 'pending' ? (
                  <td colSpan={19} className="p-2 text-slate-400">กำลังอ่าน...</td>
                ) : t.status === 'error' ? (
                  <td colSpan={19} className="p-2 text-red-600 text-xs">
                    อ่านไม่สำเร็จ: {t.error}
                  </td>
                ) : (
                  <>
                    <td className="p-2">
                      <div className="flex items-center gap-1">
                        <CheckBadge trip={t} />
                        <TripExtras trip={t} />
                      </div>
                    </td>
                    <td className="p-2">
                      <select
                        value={t.trip_date ?? ''}
                        disabled={locked(t)}
                        onChange={(e) => patch(t.id, { trip_date: e.target.value || null })}
                        className={`w-28 border rounded px-1.5 py-1 text-sm bg-white disabled:bg-slate-50 disabled:text-slate-400 ${
                          t.trip_date ? 'border-slate-200' : 'border-amber-400 bg-amber-50'
                        }`}
                      >
                        <option value="">— เลือก —</option>
                        {dates.map((d) => <option key={d} value={d}>{fmtDateOption(d)}</option>)}
                      </select>
                    </td>
                    <td className="p-2">
                      <input
                        defaultValue={t.trip_time ?? ''}
                        placeholder="HH:MM"
                        disabled={locked(t)}
                        onBlur={(e) => e.target.value !== (t.trip_time ?? '') && patch(t.id, { trip_time: e.target.value || null })}
                        className="w-16 border border-slate-200 rounded px-2 py-1 text-sm bg-white disabled:bg-slate-50 disabled:text-slate-400"
                      />
                    </td>
                    <td className="p-2">{selCell(t, 'service_type', SERVICE_OPTIONS, 'w-32')}</td>
                    <td className="p-2">{selCell(t, 'payment_method', PAYMENT_OPTIONS, 'w-26')}</td>
                    <td className="p-2">{selCell(t, 'pickup_code', PROVINCE_OPTIONS, 'w-20')}</td>
                    <td className="p-2">{selCell(t, 'dropoff_code', PROVINCE_OPTIONS, 'w-20')}</td>
                    <td className="p-2">{numCell(t, 'distance_km')}</td>
                    <td className="p-2">{numCell(t, 'duration_mins', 'w-16')}</td>
                    <td className="p-2">{numCell(t, 'net_earnings')}</td>
                    <td className="p-2">{numCell(t, 'base_fare')}</td>
                    <td className="p-2">{numCell(t, 'bonus', 'w-16')}</td>
                    <td className="p-2">{numCell(t, 'turbo', 'w-16')}</td>
                    <td className="p-2">{numCell(t, 'tolls', 'w-16')}</td>
                    <td className="p-2">{numCell(t, 'passenger_total', 'w-20')}</td>
                    <td className="p-2 text-right text-slate-500">
                      {t.passenger_total != null && t.base_fare != null
                        ? (t.passenger_total - t.base_fare).toLocaleString()
                        : '—'}
                    </td>
                    <td className="p-2">{textCell(t, 'pickup_district', 'w-24')}</td>
                    <td className="p-2">{textCell(t, 'dropoff_district', 'w-24')}</td>
                    <td className="p-2">{numCell(t, 'fare_refund', 'w-16')}</td>
                  </>
                )}
                <td className="p-2 text-right">
                  <div className="flex items-center gap-1 justify-end">
                    {t.note && (
                      <span title={t.note} className="text-amber-500 cursor-help">⚠️</span>
                    )}
                    {!locked(t) && (
                      <button
                        onClick={() => removeTrip(t.id)}
                        className="text-slate-300 hover:text-red-500 px-1"
                        title="ลบรายการ"
                      >✕</button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {modalTrip && (
        <div
          className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-6"
          onClick={() => setModalTrip(null)}
        >
          <div className="bg-white rounded-xl p-3 max-h-full overflow-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex justify-between items-center mb-2 px-1">
              <span className="text-sm text-slate-600">
                {modalTrip.file_name}{modalTrip.booking_code ? ` · ${modalTrip.booking_code}` : ''}
              </span>
              <button onClick={() => setModalTrip(null)} className="text-slate-400 hover:text-slate-700 text-xl px-2">✕</button>
            </div>
            <div className="flex gap-4 items-start">
              <img src={`/api/trips/${modalTrip.id}/image`} alt="" className="max-w-[55vw] max-h-[78vh] rounded-lg" />
              <div className="text-sm w-64 space-y-2 pt-1">
                <div>
                  <p className="text-xs text-slate-400">จุดรับ {modalTrip.pickup_district ? `(${modalTrip.pickup_district})` : ''}</p>
                  <p>{modalTrip.pickup_text || '—'}</p>
                </div>
                <div>
                  <p className="text-xs text-slate-400">จุดส่ง {modalTrip.dropoff_district ? `(${modalTrip.dropoff_district})` : ''}</p>
                  <p>{modalTrip.dropoff_text || '—'}</p>
                </div>
                <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs pt-2 border-t border-slate-100">
                  <span className="text-slate-400">จุดแวะ</span><span>{modalTrip.num_stops ?? '—'}</span>
                  <span className="text-slate-400">Surge</span><span>{modalTrip.surge ? '🔥 ใช่' : 'ไม่'}</span>
                  <span className="text-slate-400">คิว</span><span>{modalTrip.queue_type || 'ปกติ'}</span>
                  <span className="text-slate-400">ค่าธรรมเนียมแอป</span><span>{modalTrip.app_fee ?? '—'}</span>
                  <span className="text-slate-400">ส่วนลด/อื่นๆ</span><span>{modalTrip.other_adj ?? '—'}</span>
                  <span className="text-slate-400">เงินคืน</span><span>{modalTrip.fare_refund ?? '—'}</span>
                </div>
                {modalTrip.source_url && (
                  <a href={modalTrip.source_url} target="_blank" rel="noreferrer" className="text-xs text-blue-600 hover:underline block">เปิดรูปต้นฉบับใน Drive ↗</a>
                )}
                {modalTrip.note && (
                  <p className="text-xs text-amber-700 bg-amber-50 rounded p-2">⚠️ {modalTrip.note}</p>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
