import { useEffect, useState } from 'react'
import { api, exportUrl } from './api.js'

const SIZE = 50

export default function DataView({ onOpenJob }) {
  const [drivers, setDrivers] = useState([])
  const [f, setF] = useState({ driver: '', from: '', to: '', status: 'all', q: '' })
  const [page, setPage] = useState(1)
  const [data, setData] = useState({ rows: [], total: 0 })
  const [err, setErr] = useState('')

  useEffect(() => { api.drivers().then((r) => setDrivers(r.drivers)).catch(() => {}) }, [])

  useEffect(() => {
    const p = { status: f.status, page, size: SIZE }
    if (f.driver) p.driver = f.driver
    if (f.from) p.date_from = f.from
    if (f.to) p.date_to = f.to
    if (f.q) p.q = f.q
    api.trips(p).then(setData).catch((e) => setErr(e.message))
  }, [f, page])

  const set = (k) => (e) => { setF({ ...f, [k]: e.target.value }); setPage(1) }
  const pages = Math.max(1, Math.ceil(data.total / SIZE))
  const dl = exportUrl({ dateFrom: f.from, dateTo: f.to, driver: f.driver, committedOnly: f.status !== 'all' && f.status !== 'waiting' })

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-xl border border-slate-200 p-4 flex flex-wrap items-end gap-3 text-sm">
        <label className="block">
          <span className="block text-slate-600 mb-1">ไรเดอร์</span>
          <select value={f.driver} onChange={set('driver')} className="border border-slate-300 rounded-lg px-3 py-2 bg-white min-w-44">
            <option value="">ทุกคน</option>
            {drivers.map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="block text-slate-600 mb-1">ตั้งแต่</span>
          <input type="date" value={f.from} onChange={set('from')} className="border border-slate-300 rounded-lg px-3 py-2" />
        </label>
        <label className="block">
          <span className="block text-slate-600 mb-1">ถึง</span>
          <input type="date" value={f.to} onChange={set('to')} className="border border-slate-300 rounded-lg px-3 py-2" />
        </label>
        <label className="block">
          <span className="block text-slate-600 mb-1">สถานะ</span>
          <select value={f.status} onChange={set('status')} className="border border-slate-300 rounded-lg px-3 py-2 bg-white">
            <option value="all">ทั้งหมด</option>
            <option value="approved">อนุมัติแล้ว</option>
            <option value="waiting">รอคนตรวจ</option>
          </select>
        </label>
        <label className="block flex-1 min-w-48">
          <span className="block text-slate-600 mb-1">ค้นหา (booking code / ไฟล์ / ที่อยู่)</span>
          <input value={f.q} onChange={set('q')} placeholder="เช่น A-9LO9AMUGXEO" className="w-full border border-slate-300 rounded-lg px-3 py-2" />
        </label>
        <a href={dl} className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg px-4 py-2 font-medium">⬇ Excel ตามตัวกรอง</a>
      </div>

      {err && <p className="text-red-600 text-sm">⚠️ {err}</p>}

      <p className="text-xs text-slate-500">คอลัมน์เรียงตาม Sheet1 ในไฟล์ Rider Trips.xlsx (A→R)</p>
      <div className="bg-white rounded-xl border border-slate-200 overflow-x-auto">
        <table className="w-full text-sm min-w-[1700px]">
          <thead><tr className="text-left text-slate-500 border-b border-slate-200 bg-slate-50 text-xs">
            <th className="p-2">Driver Name</th><th className="p-2">Date</th><th className="p-2">Time</th>
            <th className="p-2">Service Type</th><th className="p-2">Payment</th>
            <th className="p-2">Pick-up</th><th className="p-2">Drop-off</th>
            <th className="p-2 text-right">Distance</th><th className="p-2 text-right">Duration</th>
            <th className="p-2 text-right">Net</th><th className="p-2 text-right">Base</th>
            <th className="p-2 text-right">Intl Fee</th><th className="p-2 text-right">Bonus</th>
            <th className="p-2 text-right">Turbo</th><th className="p-2 text-right">Tolls</th>
            <th className="p-2 text-right">Passenger Fare</th><th className="p-2 text-right">Service Fee</th>
            <th className="p-2">Image</th>
            <th className="p-2">สถานะ</th><th className="p-2"></th>
          </tr></thead>
          <tbody>
            {data.rows.map((t) => (
              <tr key={t.id} className="border-b border-slate-100 hover:bg-slate-50">
                <td className="p-2 font-medium whitespace-nowrap">{t.driver_name}</td>
                <td className="p-2 whitespace-nowrap">{t.trip_date || '—'}</td>
                <td className="p-2 whitespace-nowrap">{t.time_band || 'N/A'}</td>
                <td className="p-2">{t.service_type}</td>
                <td className="p-2">{t.payment_method}</td>
                <td className="p-2">{t.pickup_zone || '—'}</td>
                <td className="p-2">{t.dropoff_zone || '—'}</td>
                <td className="p-2 text-right tabular-nums">{t.distance_km}</td>
                <td className="p-2 text-right tabular-nums">{t.duration_mins ?? ''}</td>
                <td className="p-2 text-right tabular-nums font-medium">{t.sheet_net ?? t.net_earnings}</td>
                <td className="p-2 text-right tabular-nums">{t.base_fare}</td>
                <td className="p-2 text-right tabular-nums text-slate-500">{t.intl_fee ?? 0}</td>
                <td className="p-2 text-right tabular-nums text-slate-500">{t.bonus ?? 0}</td>
                <td className="p-2 text-right tabular-nums text-slate-500">{t.turbo ?? 0}</td>
                <td className="p-2 text-right tabular-nums text-slate-500">{t.tolls ?? 0}</td>
                <td className="p-2 text-right tabular-nums">{t.passenger_fare ?? '—'}</td>
                <td className="p-2 text-right tabular-nums text-slate-500">{t.service_fee ?? '—'}</td>
                <td className="p-2 text-xs text-slate-500 whitespace-nowrap" title={t.file_name}>
                  {t.customer_image || t.file_name || '—'}
                  {t.surge ? ' 🔥' : ''}
                </td>
                <td className="p-2">
                  {t.committed
                    ? <span className="text-xs rounded-full px-2 py-0.5 bg-emerald-100 text-emerald-700">{t.auto_approved ? '✓ auto' : '✓ คน'}</span>
                    : <span className="text-xs rounded-full px-2 py-0.5 bg-amber-100 text-amber-700">รอตรวจ</span>}
                </td>
                <td className="p-2 text-right whitespace-nowrap">
                  {t.source_url && <a href={t.source_url} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline mr-2" title="รูปต้นฉบับใน Drive">รูป ↗</a>}
                  <button onClick={() => onOpenJob(t.job_id)} className="text-blue-600 hover:underline">job #{t.job_id}</button>
                </td>
              </tr>
            ))}
            {data.rows.length === 0 && <tr><td colSpan={20} className="p-6 text-center text-slate-400">ไม่พบข้อมูล</td></tr>}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between text-sm text-slate-600">
        <span>ทั้งหมด {data.total.toLocaleString()} แถว · หน้า {page}/{pages}</span>
        <div className="flex gap-2">
          <button disabled={page <= 1} onClick={() => setPage(page - 1)} className="border border-slate-300 rounded px-3 py-1 disabled:opacity-40">← ก่อนหน้า</button>
          <button disabled={page >= pages} onClick={() => setPage(page + 1)} className="border border-slate-300 rounded px-3 py-1 disabled:opacity-40">ถัดไป →</button>
        </div>
      </div>
    </div>
  )
}
