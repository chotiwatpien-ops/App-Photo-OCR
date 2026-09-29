import { useEffect, useState } from 'react'
import { api } from './api.js'

// 'งานซ้ำ' — every album of the week and whether it repeats, readable on a phone without opening
// the Excel report (Fiat 2026-09-29: "เช็คงานซ้ำแบบไม่เปิดคอม ง่ายๆ ที่สุด ไม่ต้อง Details").
// Same numbers as the report's first sheet (duplicate_report.album_overview); newest album on top,
// because what someone checks from a phone is what just came in.

const fmt = (n) => (n ?? 0).toLocaleString('th-TH')
const when = (s) => {
  if (!s) return ''
  const d = new Date(s.replace(' ', 'T'))
  return Number.isNaN(d.getTime()) ? s
    : d.toLocaleString('th-TH', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

function AlbumRow({ a }) {
  const dup = a.status === 'ซ้ำ'
  return (
    <li className={`px-4 py-3 border-b border-slate-100 last:border-b-0 ${dup ? 'bg-red-50/60' : ''}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-medium break-words">{a.album}</p>
          <p className="text-xs text-slate-500 mt-0.5 tabular-nums">
            {when(a.first)} · อ่าน {fmt(a.read)}
            {a.left ? <span className="text-amber-700"> · ค้างในกอง {fmt(a.left)}</span> : null}
          </p>
        </div>
        <span className={`shrink-0 text-sm font-semibold rounded-full px-3 py-1 tabular-nums ${dup
          ? 'bg-red-100 text-red-700' : 'bg-emerald-50 text-emerald-700'}`}>
          {dup ? `ซ้ำ ${fmt(a.dup)}` : 'ไม่ซ้ำ'}
        </span>
      </div>
      {dup && a.with && (
        <p className="text-xs text-red-700 mt-1 break-words">ซ้ำกับ {a.with}</p>
      )}
    </li>
  )
}

export default function DupAlbums() {
  const [week, setWeek] = useState('')
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [onlyDup, setOnlyDup] = useState(false)

  useEffect(() => {
    setError('')
    api.duplicateAlbums(week).then(setData).catch((e) => setError(e.message))
  }, [week])

  if (error) return <p className="text-sm text-red-600">โหลดไม่ได้: {error}</p>
  if (!data) return <p className="text-sm text-slate-400">กำลังโหลด…</p>
  if (!data.week) return <p className="text-sm text-slate-400">ยังไม่มีสัปดาห์ให้ดู</p>

  const albums = [...data.albums].reverse()            // newest first
  const nDup = albums.filter((a) => a.status === 'ซ้ำ').length
  const shown = onlyDup ? albums.filter((a) => a.status === 'ซ้ำ') : albums

  return (
    <div className="max-w-2xl mx-auto space-y-3">
      <div className="flex items-center gap-2 overflow-x-auto">
        {data.weeks.map((w) => (
          <button key={w.date_from} onClick={() => setWeek(w.date_from)}
            className={`shrink-0 min-h-10 px-4 rounded-full text-sm border ${w.date_from === data.week
              ? 'bg-slate-900 text-white border-slate-900' : 'bg-white text-slate-600 border-slate-300'}`}>
            {w.label.replace(/^\d{4}-/, '')}
          </button>
        ))}
      </div>

      <section className="bg-white rounded-xl border border-slate-200 shadow-sm">
        <div className="px-4 py-3 border-b border-slate-200">
          <div className="flex items-baseline justify-between gap-2">
            <h2 className="font-semibold">งานซ้ำรายอัลบั้ม · {data.label.replace(/^\d{4}-/, '')}</h2>
            <p className="text-xs text-slate-400">ข้อมูล ณ {when(data.as_of)}</p>
          </div>
          <p className="text-sm text-slate-600 mt-1 tabular-nums">
            {fmt(albums.length)} อัลบั้ม ·{' '}
            <span className="text-red-700 font-semibold">ซ้ำ {fmt(nDup)}</span> ·{' '}
            <span className="text-emerald-700">ไม่ซ้ำ {fmt(albums.length - nDup)}</span>
          </p>
          <div className="flex gap-2 mt-2">
            {[[false, 'ทั้งหมด'], [true, 'เฉพาะที่ซ้ำ']].map(([v, label]) => (
              <button key={label} onClick={() => setOnlyDup(v)}
                className={`min-h-9 px-3 rounded-lg text-sm ${onlyDup === v
                  ? 'bg-slate-100 text-slate-900 font-medium' : 'text-slate-500'}`}>
                {label}
              </button>
            ))}
          </div>
          <p className="text-xs text-slate-400 mt-1">ล่าสุดอยู่บน · นับเฉพาะซ้ำในสัปดาห์เดียวกัน</p>
        </div>
        {shown.length === 0
          ? <p className="px-4 py-6 text-sm text-slate-400">ไม่มีอัลบั้มที่ซ้ำ</p>
          : <ul>{shown.map((a) => <AlbumRow key={a.album} a={a} />)}</ul>}
      </section>
    </div>
  )
}
