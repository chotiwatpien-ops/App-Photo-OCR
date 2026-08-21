import { useEffect, useState } from 'react'
import { api, exportUrl } from './api.js'

const fmt = (n) => (n ?? 0).toLocaleString('th-TH', { maximumFractionDigits: 0 })
const fmt2 = (n) => (n ?? 0).toLocaleString('th-TH', { maximumFractionDigits: 2 })

function Kpi({ label, value, sub, tone = '' }) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-4">
      <p className="text-xs text-slate-500">{label}</p>
      <p className={`text-2xl font-semibold tabular-nums ${tone}`}>{value}</p>
      {sub && <p className="text-xs text-slate-400 mt-0.5">{sub}</p>}
    </div>
  )
}

export default function Dashboard() {
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    const p = {}
    if (from) p.date_from = from
    if (to) p.date_to = to
    api.summary(p).then(setData).catch((e) => setErr(e.message))
  }, [from, to])

  if (err) return <p className="text-red-600">⚠️ {err}</p>
  if (!data) return <p className="text-slate-400">กำลังโหลด...</p>
  const t = data.totals
  const avg = t.approved ? t.net / t.approved : 0
  const perKm = t.km ? t.net / t.km : 0

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end gap-3 text-sm">
        <label className="block">
          <span className="block text-slate-600 mb-1">ตั้งแต่</span>
          <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="border border-slate-300 rounded-lg px-3 py-2" />
        </label>
        <label className="block">
          <span className="block text-slate-600 mb-1">ถึง</span>
          <input type="date" value={to} onChange={(e) => setTo(e.target.value)} className="border border-slate-300 rounded-lg px-3 py-2" />
        </label>
        {(from || to) && (
          <button onClick={() => { setFrom(''); setTo('') }} className="text-slate-500 hover:underline">ล้างตัวกรอง</button>
        )}
        <a href={exportUrl({ dateFrom: from, dateTo: to, committedOnly: true })}
          className="ml-auto bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg px-4 py-2 font-medium">⬇ Excel ช่วงนี้</a>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <Kpi label="เที่ยวทั้งหมด" value={fmt(t.trips)} />
        <Kpi label="อนุมัติแล้ว" value={fmt(t.approved)} tone="text-emerald-700" />
        <Kpi label="รอคนตรวจ" value={fmt(t.waiting)} tone={t.waiting ? 'text-amber-600' : ''} />
        <Kpi label="รายได้รวม (อนุมัติ)" value={`฿${fmt(t.net)}`} sub={`เฉลี่ย ฿${fmt(avg)}/เที่ยว`} />
        <Kpi label="ระยะทางรวม" value={`${fmt(t.km)} กม.`} sub={`฿${fmt2(perKm)}/กม.`} />
        <Kpi label="งาน Surge / เงินสด" value={`${fmt(t.surge)} / ${fmt(t.cash)}`} sub="จำนวนเที่ยว" />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="bg-white rounded-xl border border-slate-200 p-5 overflow-x-auto">
          <h2 className="font-semibold mb-3">รายสัปดาห์</h2>
          <table className="w-full text-sm">
            <thead><tr className="text-left text-slate-500 border-b border-slate-200">
              <th className="py-2 pr-3">สัปดาห์</th><th className="py-2 pr-3 text-right">ไรเดอร์</th>
              <th className="py-2 pr-3 text-right">เที่ยว</th><th className="py-2 pr-3 text-right">รอคน</th>
              <th className="py-2 pr-3 text-right">รายได้</th><th className="py-2 text-right">กม.</th>
            </tr></thead>
            <tbody>
              {data.by_week.map((w) => (
                <tr key={w.week} className="border-b border-slate-100">
                  <td className="py-2 pr-3 font-medium">{w.week}</td>
                  <td className="py-2 pr-3 text-right tabular-nums">{w.riders}</td>
                  <td className="py-2 pr-3 text-right tabular-nums">{fmt(w.trips)}</td>
                  <td className={`py-2 pr-3 text-right tabular-nums ${w.waiting ? 'text-amber-600 font-medium' : 'text-slate-400'}`}>{w.waiting}</td>
                  <td className="py-2 pr-3 text-right tabular-nums">฿{fmt(w.net)}</td>
                  <td className="py-2 text-right tabular-nums">{fmt(w.km)}</td>
                </tr>
              ))}
              {data.by_week.length === 0 && <tr><td colSpan={6} className="py-4 text-slate-400">ยังไม่มีข้อมูล</td></tr>}
            </tbody>
          </table>
        </section>

        <section className="bg-white rounded-xl border border-slate-200 p-5 overflow-x-auto">
          <h2 className="font-semibold mb-3">รายไรเดอร์ (เรียงตามรายได้)</h2>
          <table className="w-full text-sm">
            <thead><tr className="text-left text-slate-500 border-b border-slate-200">
              <th className="py-2 pr-3">ไรเดอร์</th><th className="py-2 pr-3 text-right">เที่ยว</th>
              <th className="py-2 pr-3 text-right">รอคน</th><th className="py-2 pr-3 text-right">รายได้</th>
              <th className="py-2 pr-3 text-right">฿/เที่ยว</th><th className="py-2 text-right">Surge</th>
            </tr></thead>
            <tbody>
              {data.by_rider.map((r) => (
                <tr key={r.driver_name} className="border-b border-slate-100">
                  <td className="py-2 pr-3 font-medium">{r.driver_name}</td>
                  <td className="py-2 pr-3 text-right tabular-nums">{fmt(r.trips)}</td>
                  <td className={`py-2 pr-3 text-right tabular-nums ${r.waiting ? 'text-amber-600 font-medium' : 'text-slate-400'}`}>{r.waiting}</td>
                  <td className="py-2 pr-3 text-right tabular-nums">฿{fmt(r.net)}</td>
                  <td className="py-2 pr-3 text-right tabular-nums">{r.approved ? fmt(r.net / r.approved) : '—'}</td>
                  <td className="py-2 text-right tabular-nums">{r.surge || '—'}</td>
                </tr>
              ))}
              {data.by_rider.length === 0 && <tr><td colSpan={6} className="py-4 text-slate-400">ยังไม่มีข้อมูล</td></tr>}
            </tbody>
          </table>
        </section>
      </div>

      <section className="bg-white rounded-xl border border-slate-200 p-5 overflow-x-auto">
        <h2 className="font-semibold mb-3">การดูดรูปจาก Drive ล่าสุด</h2>
        {data.ingest_runs.length === 0 ? (
          <p className="text-sm text-slate-400">ยังไม่เคยรัน ingest (ข้อมูลทั้งหมดมาจากการอัปโหลดมือ)</p>
        ) : (
          <table className="w-full text-sm">
            <thead><tr className="text-left text-slate-500 border-b border-slate-200">
              <th className="py-2 pr-3">เริ่ม</th><th className="py-2 pr-3 text-right">รูปใหม่</th>
              <th className="py-2 pr-3 text-right">อนุมัติอัตโนมัติ</th><th className="py-2 pr-3 text-right">รอคน</th>
              <th className="py-2 pr-3 text-right">error</th><th className="py-2">หมายเหตุ</th>
            </tr></thead>
            <tbody>
              {data.ingest_runs.map((r) => (
                <tr key={r.id} className="border-b border-slate-100 align-top">
                  <td className="py-2 pr-3 whitespace-nowrap">{(r.started_at || '').replace('T', ' ')}</td>
                  <td className="py-2 pr-3 text-right tabular-nums">{r.files_new}</td>
                  <td className="py-2 pr-3 text-right tabular-nums text-emerald-700">{r.auto_approved}</td>
                  <td className={`py-2 pr-3 text-right tabular-nums ${r.flagged ? 'text-amber-600' : ''}`}>{r.flagged}</td>
                  <td className={`py-2 pr-3 text-right tabular-nums ${r.errors ? 'text-red-600' : 'text-slate-400'}`}>{r.errors}</td>
                  <td className="py-2 text-xs text-slate-500 whitespace-pre-line">{r.notes || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}
