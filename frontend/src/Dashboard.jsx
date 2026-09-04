import { useEffect, useMemo, useRef, useState } from 'react'
import { api, exportUrl } from './api.js'

const fmt = (n) => (n ?? 0).toLocaleString('th-TH', { maximumFractionDigits: 0 })
const fmt2 = (n) => (n ?? 0).toLocaleString('th-TH', { maximumFractionDigits: 2 })
const pct = (a, b) => (b ? Math.round((a / b) * 100) : 0)

/** "+12%" / "-4%" against the previous week, or null when there is nothing to compare with. */
function Delta({ now, prev }) {
  if (prev == null || !prev) return null
  const d = Math.round(((now - prev) / prev) * 100)
  if (d === 0) return <span className="text-slate-400">เท่าสัปดาห์ก่อน</span>
  const up = d > 0
  return (
    <span className={up ? 'text-emerald-600' : 'text-red-600'}>
      {up ? '▲' : '▼'} {Math.abs(d)}% จากสัปดาห์ก่อน
    </span>
  )
}

function Tile({ label, value, sub, tone = 'text-slate-900', bar, onClick, badge }) {
  const Box = onClick ? 'button' : 'div'
  return (
    <Box onClick={onClick}
      className={`text-left bg-white rounded-xl border border-slate-200 p-4 w-full ${onClick ? 'hover:border-slate-400 hover:shadow-sm transition' : ''}`}>
      <p className="text-xs text-slate-500 flex items-center gap-1.5">
        {label}
        {badge && <span className="rounded-full bg-amber-100 text-amber-700 px-1.5 py-0.5 text-[10px]">{badge}</span>}
      </p>
      <p className={`text-2xl font-semibold tabular-nums ${tone}`}>{value}</p>
      {bar != null && (
        <div className="mt-2 h-1.5 rounded-full bg-slate-100 overflow-hidden">
          <div className="h-full rounded-full bg-emerald-500" style={{ width: `${Math.min(100, bar)}%` }} />
        </div>
      )}
      {sub && <p className="text-xs text-slate-400 mt-1">{sub}</p>}
    </Box>
  )
}

/** Weekly revenue, most recent on the right. Plain SVG-free bars — the shape is the point. */
function Trend({ weeks, selected, onPick }) {
  const data = weeks.slice(0, 10).reverse()
  if (data.length < 2) return null
  const max = Math.max(...data.map((w) => w.net)) || 1
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-4">
      <p className="text-xs text-slate-500 mb-2">รายได้รายสัปดาห์ <span className="text-slate-400">คลิกแท่งเพื่อเลือกสัปดาห์</span></p>
      <div className="flex items-end justify-start gap-3 h-28 border-b border-slate-200">
        {data.map((w) => {
          const on = w.week === selected
          return (
            <button key={w.week} onClick={() => onPick(w)}
              title={`${w.week} · ฿${fmt(w.net)} · ${fmt(w.trips)} งาน · ไรเดอร์ ${w.riders}`}
              className="w-12 flex flex-col justify-end items-center group h-full">
              <span className={`text-[11px] mb-1 tabular-nums ${on ? 'text-slate-800 font-medium' : 'text-slate-400 opacity-0 group-hover:opacity-100'}`}>
                ฿{fmt(Math.round(w.net / 1000))}k
              </span>
              <span className={`w-8 rounded-t ${on ? 'bg-slate-800' : 'bg-slate-300 group-hover:bg-slate-400'}`}
                style={{ height: `${Math.max(6, (w.net / max) * 74)}px` }} />
            </button>
          )
        })}
      </div>
      <div className="flex justify-start gap-3 mt-1">
        {data.map((w) => (
          <span key={w.week} className={`w-12 text-center text-[11px] ${w.week === selected ? 'text-slate-800 font-medium' : 'text-slate-400'}`}>
            {w.week.slice(-3)}
          </span>
        ))}
      </div>
    </div>
  )
}

/** Who is short this week, worst first. A rider one slip short is not the same problem as a
 *  rider who has sent nothing, so the two are told apart and the long tail stays folded away. */
function Shortfall({ week, expected, onOpenJob }) {
  const [comp, setComp] = useState(null)
  const [all, setAll] = useState(false)
  useEffect(() => { api.completeness().then(setComp).catch(() => {}) }, [])
  if (!comp) return null
  const w = comp.weeks.find((x) => x.week === week) || comp.weeks[0]
  if (!w) return null

  const rows = [...w.incomplete].sort((a, b) => (b.missing || 0) - (a.missing || 0))
  const short = rows.filter((r) => r.missing > 0)
  const onlyWaiting = rows.filter((r) => !r.missing)
  const shown = all ? short : short.slice(0, 12)
  const totalMissing = short.reduce((s, r) => s + r.missing, 0) + w.absent.length * (expected || 21)

  return (
    <section className="bg-white rounded-xl border border-slate-200 p-5">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <h2 className="font-semibold">
          ยังไม่ครบ <span className="text-sm font-normal text-slate-400">สัปดาห์ {w.week} · เกณฑ์ {comp.expected} งาน/คน</span>
        </h2>
        <p className="text-sm text-slate-500">
          ขาดรวม <span className="font-semibold text-red-600 tabular-nums">{fmt(totalMissing)}</span> งาน
          {' · '}คนที่ยังขาด {short.length + w.absent.length}
        </p>
      </div>

      {short.length === 0 && w.absent.length === 0 ? (
        <p className="text-sm text-emerald-700 mt-3">ครบทุกคนแล้ว</p>
      ) : (
        <div className="mt-3 space-y-1.5">
          {shown.map((r) => (
            <button key={r.job_id} onClick={() => onOpenJob?.(r.job_id)}
              className="w-full flex items-center gap-3 text-sm rounded-lg px-2 py-1.5 hover:bg-slate-50 text-left">
              <span className="w-36 truncate font-medium">{r.driver_name}</span>
              <span className="w-24 text-xs text-slate-400 truncate">{r.category}</span>
              <span className="flex-1 h-2 rounded-full bg-slate-100 overflow-hidden min-w-24">
                <span className="block h-full bg-emerald-500" style={{ width: `${pct(r.approved, comp.expected)}%` }} />
              </span>
              <span className="w-16 text-right tabular-nums text-slate-600">{r.approved}/{comp.expected}</span>
              <span className="w-24 text-right text-red-600 tabular-nums">ขาด {r.missing}</span>
            </button>
          ))}
          {short.length > shown.length && (
            <button onClick={() => setAll(true)} className="text-sm text-blue-600 hover:underline px-2">
              ดูอีก {short.length - shown.length} คน
            </button>
          )}
          {all && short.length > 12 && (
            <button onClick={() => setAll(false)} className="text-sm text-slate-500 hover:underline px-2">ย่อ</button>
          )}

          {w.absent.length > 0 && (
            <p className="text-sm text-slate-500 pt-2">
              ยังไม่ส่งรูปเลย {w.absent.length} คน:{' '}
              <span className="text-slate-700">{w.absent.slice(0, 12).join(', ')}</span>
              {w.absent.length > 12 && ` และอีก ${w.absent.length - 12} คน`}
            </p>
          )}
          {onlyWaiting.length > 0 && (
            <p className="text-xs text-amber-700 pt-1">
              อีก {onlyWaiting.length} คนครบแล้วแต่ยังรอตรวจ/รออ่าน
            </p>
          )}
        </div>
      )}
    </section>
  )
}

export default function Dashboard({ onOpenJob, onGoQueue }) {
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [week, setWeek] = useState('')          // '' = every week
  const [data, setData] = useState(null)
  const [all, setAll] = useState(null)          // unfiltered, for the trend + week pills
  const [q, setQ] = useState('')
  const [showRiders, setShowRiders] = useState(20)
  const [err, setErr] = useState('')
  const [ready, setReady] = useState(false)     // a week has been chosen; safe to load figures
  const seq = useRef(0)

  useEffect(() => { api.summary({}).then(setAll).catch((e) => setErr(e.message)) }, [])

  // open on the newest week rather than on everything ever recorded
  useEffect(() => {
    if (!all || ready) return
    if (all.by_week.length) pickWeek(all.by_week[0])
    setReady(true)
  }, [all])                                                              // eslint-disable-line

  // two requests can be in flight at once (the wide one is slower); only the newest may win
  useEffect(() => {
    if (!ready) return
    const p = {}
    if (from) p.date_from = from
    if (to) p.date_to = to
    const mine = ++seq.current
    api.summary(p).then((r) => { if (mine === seq.current) setData(r) }).catch((e) => setErr(e.message))
  }, [from, to, ready])

  const pickWeek = (w) => {
    if (!w) { setWeek(''); setFrom(''); setTo(''); return }
    setWeek(w.week)
    setFrom(w.date_from || '')
    setTo(w.date_to || '')
  }

  const prevWeek = useMemo(() => {
    if (!all || !week) return null
    const i = all.by_week.findIndex((w) => w.week === week)
    return i >= 0 ? all.by_week[i + 1] : null
  }, [all, week])

  if (err) return <p className="text-red-600">⚠️ {err}</p>
  if (!data || !all) return <p className="text-slate-400">กำลังโหลด...</p>

  const t = data.totals
  const cur = week ? all.by_week.find((w) => w.week === week) : null
  const avg = t.approved ? t.net / t.approved : 0
  const perKm = t.km ? t.net / t.km : 0
  const riders = data.by_rider.filter((r) => !q || r.driver_name.includes(q))

  return (
    <div className="space-y-5">
      {/* which week am I looking at */}
      <div className="flex flex-wrap items-center gap-2 text-sm">
        {all.by_week.slice(0, 6).map((w) => (
          <button key={w.week} onClick={() => pickWeek(w)}
            className={`rounded-full px-3 py-1.5 border ${week === w.week
              ? 'bg-slate-900 text-white border-slate-900'
              : 'bg-white border-slate-300 text-slate-600 hover:border-slate-400'}`}>
            {w.week}
          </button>
        ))}
        <button onClick={() => pickWeek(null)}
          className={`rounded-full px-3 py-1.5 border ${!week && !from && !to
            ? 'bg-slate-900 text-white border-slate-900'
            : 'bg-white border-slate-300 text-slate-600 hover:border-slate-400'}`}>
          ทุกสัปดาห์
        </button>
        <details className="ml-auto">
          <summary className="cursor-pointer text-slate-500 hover:text-slate-700 list-none">ช่วงวันที่เอง ▾</summary>
          <div className="flex items-end gap-2 mt-2">
            <input type="date" value={from} onChange={(e) => { setWeek(''); setFrom(e.target.value) }}
              className="border border-slate-300 rounded-lg px-3 py-1.5" />
            <span className="text-slate-400 pb-2">→</span>
            <input type="date" value={to} onChange={(e) => { setWeek(''); setTo(e.target.value) }}
              className="border border-slate-300 rounded-lg px-3 py-1.5" />
          </div>
        </details>
        <a href={exportUrl({ dateFrom: from, dateTo: to, committedOnly: true })}
          className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg px-4 py-2 font-medium">⬇ Excel ช่วงนี้</a>
      </div>

      {/* the four numbers worth acting on */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Tile label="อนุมัติแล้ว" value={fmt(t.approved)}
          bar={pct(t.approved, t.trips)}
          sub={`จาก ${fmt(t.trips)} งานที่อ่านแล้ว (${pct(t.approved, t.trips)}%)`} tone="text-emerald-700" />
        <Tile label="รอคนตรวจ" value={fmt(t.waiting)} onClick={t.waiting ? onGoQueue : undefined}
          tone={t.waiting ? 'text-amber-600' : 'text-slate-400'}
          sub={t.waiting ? 'กดเพื่อไปคิวตรวจ' : 'ไม่มีงานค้าง'} />
        <Tile label="รายได้รวม (อนุมัติแล้ว)" value={`฿${fmt(t.net)}`}
          sub={cur && prevWeek ? <Delta now={cur.net} prev={prevWeek.net} /> : `เฉลี่ย ฿${fmt(avg)}/งาน`} />
        <Tile label="ตรวจเงินไม่ผ่าน" value={fmt(t.failed)}
          tone={t.failed ? 'text-red-600' : 'text-slate-400'}
          badge={t.duplicates ? `ซ้ำ ${t.duplicates}` : null}
          sub={t.failed ? 'ตัวเลขในรูปไม่ลงตัว — ต้องมีคนดู' : 'ทุกงานตัวเลขลงตัว'} />
      </div>

      <div className="grid gap-5 lg:grid-cols-[1fr_1.4fr]">
        <Trend weeks={all.by_week} selected={week} onPick={pickWeek} />
        <div className="bg-white rounded-xl border border-slate-200 p-4 grid grid-cols-3 gap-4 text-sm">
          <div>
            <p className="text-xs text-slate-500">ไรเดอร์ในช่วงนี้</p>
            <p className="text-xl font-semibold tabular-nums">{fmt(cur ? cur.riders : new Set(data.by_rider.map((r) => r.driver_name)).size)}</p>
          </div>
          <div>
            <p className="text-xs text-slate-500">ระยะทางรวม</p>
            <p className="text-xl font-semibold tabular-nums">{fmt(t.km)} กม.</p>
            <p className="text-xs text-slate-400">฿{fmt2(perKm)}/กม.</p>
          </div>
          <div>
            <p className="text-xs text-slate-500">Surge / เงินสด</p>
            <p className="text-xl font-semibold tabular-nums">{fmt(t.surge)} / {fmt(t.cash)}</p>
            <p className="text-xs text-slate-400">จำนวนงาน</p>
          </div>
        </div>
      </div>

      <Shortfall week={week || all.by_week[0]?.week} expected={21} onOpenJob={onOpenJob} />

      <section className="bg-white rounded-xl border border-slate-200 p-5">
        <div className="flex items-center justify-between gap-3 flex-wrap mb-3">
          <h2 className="font-semibold">รายไรเดอร์ <span className="text-sm font-normal text-slate-400">เรียงตามรายได้</span></h2>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="ค้นหาชื่อไรเดอร์"
            className="border border-slate-300 rounded-lg px-3 py-1.5 text-sm w-56" />
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="text-left text-slate-500 border-b border-slate-200">
              <th className="py-2 pr-3">ไรเดอร์</th><th className="py-2 pr-3 text-right">งาน</th>
              <th className="py-2 pr-3 text-right">รอตรวจ</th><th className="py-2 pr-3 text-right">รายได้</th>
              <th className="py-2 pr-3 text-right">฿/งาน</th><th className="py-2 text-right">ไม่ผ่าน</th>
            </tr></thead>
            <tbody>
              {riders.slice(0, showRiders).map((r) => (
                <tr key={r.driver_name} className="border-b border-slate-100 hover:bg-slate-50">
                  <td className="py-2 pr-3 font-medium">{r.driver_name}</td>
                  <td className="py-2 pr-3 text-right tabular-nums">{fmt(r.trips)}</td>
                  <td className={`py-2 pr-3 text-right tabular-nums ${r.waiting ? 'text-amber-600 font-medium' : 'text-slate-400'}`}>{r.waiting || '—'}</td>
                  <td className="py-2 pr-3 text-right tabular-nums">฿{fmt(r.net)}</td>
                  <td className="py-2 pr-3 text-right tabular-nums text-slate-500">{r.approved ? fmt(r.net / r.approved) : '—'}</td>
                  <td className={`py-2 text-right tabular-nums ${r.failed ? 'text-red-600' : 'text-slate-300'}`}>{r.failed || '—'}</td>
                </tr>
              ))}
              {riders.length === 0 && <tr><td colSpan={6} className="py-4 text-slate-400">ไม่พบไรเดอร์ที่ค้นหา</td></tr>}
            </tbody>
          </table>
        </div>
        {riders.length > showRiders && (
          <button onClick={() => setShowRiders(riders.length)} className="mt-3 text-sm text-blue-600 hover:underline">
            ดูทั้งหมด {riders.length} คน
          </button>
        )}
      </section>

      <details className="bg-white rounded-xl border border-slate-200 p-5">
        <summary className="font-semibold cursor-pointer">รอบดูดรูปจาก Drive ล่าสุด <span className="text-sm font-normal text-slate-400">({data.ingest_runs.length} รอบ)</span></summary>
        {data.ingest_runs.length === 0 ? (
          <p className="text-sm text-slate-400 mt-3">ยังไม่เคยรัน</p>
        ) : (
          <div className="overflow-x-auto mt-3">
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
          </div>
        )}
      </details>
    </div>
  )
}
