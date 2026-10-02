import { useEffect, useMemo, useState } from 'react'
import { api, exportUrl } from './api.js'
import Icon from './Icon.jsx'

// ข้อมูล — every trip, filtered, in the columns of the customer's file (redesign 2026-10).
// Thai headings with the template's English name where the customer knows it by that name.

const SIZE = 50
const TH_MONTHS = ['ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.', 'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.']
const fmt = (v) => (v === null || v === undefined || v === '' ? '—' : Number(v).toLocaleString('th-TH'))
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const short = (d) => `${d.getDate()} ${TH_MONTHS[d.getMonth()]}`

/** The last few weeks, Monday to Sunday, newest first — the way everything else is counted. */
function recentWeeks(n = 6) {
  const today = new Date()
  const monday = new Date(today)
  monday.setDate(today.getDate() - ((today.getDay() + 6) % 7))
  return Array.from({ length: n }, (_, i) => {
    const a = new Date(monday); a.setDate(monday.getDate() - 7 * i)
    const b = new Date(a); b.setDate(a.getDate() + 6)
    const t = new Date(Date.UTC(a.getFullYear(), a.getMonth(), a.getDate() + 3))
    const y0 = new Date(Date.UTC(t.getUTCFullYear(), 0, 4))
    const wk = 1 + Math.round(((t - y0) / 86400000 - 3 + ((y0.getUTCDay() + 6) % 7)) / 7)
    return { from: iso(a), to: iso(b), label: `WK${wk} · ${short(a)} – ${short(b)}` }
  })
}

const COLS = [
  ['ไรเดอร์', 'Driver Name'], ['วันที่', 'Date'], ['ช่วงเวลา', 'Time'], ['Service Type'], ['การจ่ายเงิน', 'Payment'],
  ['จุดรับ', 'Pick-up'], ['จุดส่ง', 'Drop-off'], ['ระยะ (กม.)', 'Distance', 'r'], ['เวลา (นาที)', 'Duration', 'r'],
  ['คุณได้รับ', 'Net', 'r'], ['ค่ารอบ', 'Base', 'r'], ['Intl Fee', '', 'r'], ['โบนัส', 'Bonus', 'r'], ['Turbo', '', 'r'],
  ['ทางด่วน', 'Tolls', 'r'], ['Passenger Fare', '', 'r'], ['Service Fee', '', 'r'], ['รูปส่งลูกค้า', 'Image'], ['สถานะ'], [''],
]

export default function DataView({ onOpenJob }) {
  const weeks = useMemo(() => recentWeeks(), [])
  const [drivers, setDrivers] = useState([])
  const [f, setF] = useState({ week: weeks[0].from, driver: '', from: weeks[0].from, to: weeks[0].to, status: 'all', q: '' })
  const [page, setPage] = useState(1)
  const [data, setData] = useState({ rows: [], total: 0 })
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => { api.drivers().then((r) => setDrivers(r.drivers)).catch(() => {}) }, [])

  useEffect(() => {
    const p = { status: f.status, page, size: SIZE }
    if (f.driver) p.driver = f.driver
    if (f.from) p.date_from = f.from
    if (f.to) p.date_to = f.to
    if (f.q) p.q = f.q
    setLoading(true)
    api.trips(p).then((d) => { setData(d); setErr('') }).catch((e) => setErr(e.message)).finally(() => setLoading(false))
  }, [f, page])

  const set = (k) => (e) => { setF({ ...f, [k]: e.target.value, ...(k === 'from' || k === 'to' ? { week: '' } : {}) }); setPage(1) }
  const pickWeek = (e) => {
    const w = weeks.find((x) => x.from === e.target.value)
    setF({ ...f, week: e.target.value, from: w ? w.from : '', to: w ? w.to : '' }); setPage(1)
  }
  const pages = Math.max(1, Math.ceil(data.total / SIZE))
  const dl = exportUrl({ dateFrom: f.from, dateTo: f.to, driver: f.driver, committedOnly: f.status !== 'all' && f.status !== 'waiting' })
  const box = 'min-h-11 border border-line rounded-lg px-3 bg-white text-[15px]'

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm text-muted">ทุกเที่ยวในคอลัมน์เดียวกับไฟล์ Excel ส่งลูกค้า</p>
          <h1 className="text-2xl sm:text-[28px] font-semibold tracking-tight">ข้อมูล <span className="font-normal text-ink-soft text-base sm:text-xl">· {fmt(data.total)} เที่ยว</span></h1>
        </div>
        <a href={dl} className="min-h-11 px-4 rounded-lg border border-line bg-white hover:bg-ground text-sm font-medium flex items-center gap-2">
          <Icon name="download" size={18} />ดาวน์โหลด Excel ตามตัวกรอง
        </a>
      </div>

      <section aria-label="ตัวกรอง" className="bg-white rounded-xl border border-line p-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-[repeat(4,minmax(0,1fr))_minmax(0,1.5fr)]">
        <label className="flex flex-col gap-1 text-sm text-ink-soft">สัปดาห์
          <select value={f.week} onChange={pickWeek} className={box}>
            {weeks.map((w) => <option key={w.from} value={w.from}>{w.label}</option>)}
            <option value="">ทุกช่วง / กำหนดเอง</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm text-ink-soft">ไรเดอร์
          <select value={f.driver} onChange={set('driver')} className={box}>
            <option value="">ทุกคน</option>
            {drivers.map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm text-ink-soft">สถานะ
          <select value={f.status} onChange={set('status')} className={box}>
            <option value="all">ทั้งหมด</option>
            <option value="approved">อนุมัติแล้ว</option>
            <option value="waiting">รอตรวจ</option>
          </select>
        </label>
        <div className="grid grid-cols-2 gap-2">
          <label className="flex flex-col gap-1 text-sm text-ink-soft">ตั้งแต่
            <input type="date" value={f.from} onChange={set('from')} className={`${box} px-2`} />
          </label>
          <label className="flex flex-col gap-1 text-sm text-ink-soft">ถึง
            <input type="date" value={f.to} onChange={set('to')} className={`${box} px-2`} />
          </label>
        </div>
        <label className="flex flex-col gap-1 text-sm text-ink-soft">ค้นหา
          <input value={f.q} onChange={set('q')} placeholder="เลขจอง ชื่อรูป หรือที่อยู่" className={box} />
        </label>
      </section>

      {err && <p role="alert" className="text-sm text-danger-ink bg-danger-bg rounded-lg px-3 py-2">โหลดข้อมูลไม่ได้: {err}</p>}

      <div className={`bg-white rounded-xl border border-line overflow-x-auto ${loading ? 'opacity-60' : ''}`}>
        <table className="w-full text-sm min-w-[1700px]">
          <thead>
            <tr className="text-left text-muted border-b border-line bg-ground">
              {COLS.map(([th, en, align], i) => (
                <th key={i} scope="col" className={`px-3 py-2.5 font-normal align-bottom ${align === 'r' ? 'text-right' : ''} ${i === 0 ? 'sticky left-0 bg-ground z-10' : ''}`}>
                  <span className="block text-ink-soft font-medium">{th}</span>
                  {en && en !== th && <span className="block text-xs">{en}</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((t) => (
              <tr key={t.id} className="border-b border-line-soft hover:bg-ground">
                <td className="px-3 py-2.5 font-medium whitespace-nowrap sticky left-0 bg-white">{t.driver_name}</td>
                <td className="px-3 py-2.5 whitespace-nowrap">{t.trip_date || '—'}</td>
                <td className="px-3 py-2.5 whitespace-nowrap">{t.time_band || '—'}</td>
                <td className="px-3 py-2.5 whitespace-nowrap">{t.service_type || '—'}</td>
                <td className="px-3 py-2.5">{t.payment_method || '—'}</td>
                <td className="px-3 py-2.5">{t.pickup_zone || '—'}</td>
                <td className="px-3 py-2.5">{t.dropoff_zone || '—'}</td>
                <td className="px-3 py-2.5 text-right">{fmt(t.distance_km)}</td>
                <td className="px-3 py-2.5 text-right">{fmt(t.duration_mins)}</td>
                <td className="px-3 py-2.5 text-right font-medium">{fmt(t.sheet_net ?? t.net_earnings)}</td>
                <td className="px-3 py-2.5 text-right">{fmt(t.base_fare)}</td>
                <td className="px-3 py-2.5 text-right text-ink-soft">{fmt(t.intl_fee ?? 0)}</td>
                <td className="px-3 py-2.5 text-right text-ink-soft">{fmt(t.bonus ?? 0)}</td>
                <td className="px-3 py-2.5 text-right text-ink-soft">{fmt(t.turbo ?? 0)}</td>
                <td className="px-3 py-2.5 text-right text-ink-soft">{fmt(t.tolls ?? 0)}</td>
                <td className="px-3 py-2.5 text-right" title={t.passenger_fare_estimated ? 'ค่าประมาณ — รูปไม่มีข้อมูลฝั่งผู้โดยสาร' : undefined}>
                  {t.passenger_fare != null ? `${t.passenger_fare_estimated ? '≈' : ''}${fmt(t.passenger_fare)}` : '—'}
                </td>
                <td className="px-3 py-2.5 text-right text-ink-soft">{fmt(t.service_fee)}</td>
                <td className="px-3 py-2.5 text-ink-soft whitespace-nowrap">
                  {t.customer_image || '—'}
                  {t.surge ? <span className="ml-1.5 text-xs rounded-full bg-warn-bg text-warn-ink px-1.5 py-0.5">Surge</span> : null}
                </td>
                <td className="px-3 py-2.5 whitespace-nowrap">
                  {t.committed
                    ? <span className="text-xs rounded-full px-2 py-0.5 bg-ok-bg text-ok-ink">{t.auto_approved ? 'อนุมัติอัตโนมัติ' : 'อนุมัติโดยคน'}</span>
                    : <span className="text-xs rounded-full px-2 py-0.5 bg-warn-bg text-warn-ink">รอตรวจ</span>}
                </td>
                <td className="px-3 py-2.5 text-right whitespace-nowrap">
                  {t.source_url && <a href={t.source_url} target="_blank" rel="noreferrer" className="text-accent hover:underline mr-3">รูปต้นฉบับ</a>}
                  <button onClick={() => onOpenJob(t.job_id)} className="min-h-9 text-accent hover:underline">งานของไรเดอร์</button>
                </td>
              </tr>
            ))}
            {data.rows.length === 0 && !loading && (
              <tr><td colSpan={COLS.length} className="p-8 text-center text-muted">ไม่พบเที่ยวตามตัวกรองนี้</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {data.rows.some((t) => t.passenger_fare_estimated) && (
        <p className="text-sm text-muted">≈ คือ Passenger Fare ที่ประมาณจากค่ารอบ เพราะในรูปไม่มีข้อมูลฝั่งผู้โดยสาร</p>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-ink-soft">
        <span>หน้า {page} จาก {pages} · {fmt(data.total)} เที่ยว</span>
        <div className="flex gap-2">
          <button disabled={page <= 1} onClick={() => setPage(page - 1)}
            className="min-h-10 px-4 rounded-lg border border-line bg-white disabled:opacity-40 flex items-center gap-1"><Icon name="back" size={16} />ก่อนหน้า</button>
          <button disabled={page >= pages} onClick={() => setPage(page + 1)}
            className="min-h-10 px-4 rounded-lg border border-line bg-white disabled:opacity-40 flex items-center gap-1">ถัดไป<Icon name="chevron" size={16} /></button>
        </div>
      </div>
    </div>
  )
}
