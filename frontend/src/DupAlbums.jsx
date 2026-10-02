import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import Icon from './Icon.jsx'

// งานซ้ำ — every album of the week and whether it repeats (Fiat 2026-09-29: "เช็คงานซ้ำแบบไม่เปิดคอม
// ง่ายๆ ที่สุด"), redesigned 2026-10 for the customer: four totals, the albums that repeat first,
// and each repeat beside the picture it repeats, with a way to keep one the system got wrong.
// Same numbers as the report's first sheet (duplicate_report.album_overview). Counted within the
// week only: a slip delivered in an earlier week is work again (customer, 2026-09-14).

const fmt = (n) => (n ?? 0).toLocaleString('th-TH')
const TH_MONTHS = ['ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.', 'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.']
const wk = (label) => (label || '').replace(/^\d{4}-W/, 'WK')
const when = (s) => {
  if (!s) return ''
  const d = new Date(String(s).replace(' ', 'T'))
  if (Number.isNaN(d.getTime())) return s
  const today = new Date()
  const y = new Date(today); y.setDate(today.getDate() - 1)
  const t = d.toLocaleTimeString('th-TH', { hour: '2-digit', minute: '2-digit' })
  if (d.toDateString() === today.toDateString()) return `วันนี้ ${t}`
  if (d.toDateString() === y.toDateString()) return `เมื่อวาน ${t}`
  return `${d.getDate()} ${TH_MONTHS[d.getMonth()]} ${t}`
}
const day = (iso) => { if (!iso) return ''; const d = new Date(`${iso}T00:00:00`); return `${d.getDate()} ${TH_MONTHS[d.getMonth()]}` }
const WHY = {
  'ไฟล์เดิมส่งซ้ำ': 'ไฟล์รูปเดียวกันทุกจุด',
  'รหัสการจองซ้ำในสัปดาห์เดียวกัน': 'เลขจองเดียวกันในสัปดาห์นี้',
  'ครึ่งล่างของงานที่นับไปแล้ว': 'เป็นครึ่งล่างของเที่ยวที่นับไปแล้ว',
}

function Tile({ label, value, sub, tone = 'text-ink' }) {
  return (
    <div className="bg-white border border-line rounded-xl px-4 py-3.5 sm:px-5 sm:py-4">
      <p className="text-sm text-muted">{label}</p>
      <p className={`text-[26px] leading-tight font-semibold ${tone}`}>{value}</p>
      {sub && <p className="text-sm text-muted">{sub}</p>}
    </div>
  )
}

function Thumb({ src, href, label, empty = 'ไม่ได้อ่าน (ตัดก่อนส่งให้ AI)' }) {
  const [broken, setBroken] = useState(false)
  const body = src && !broken
    ? <img src={src} alt={label} loading="lazy" onError={() => setBroken(true)}
        className="w-full h-28 object-cover object-top rounded-lg border border-line bg-ground" />
    : <span className="w-full h-28 rounded-lg border border-line bg-ground flex items-center justify-center text-xs text-muted text-center px-2">{src ? 'เปิดรูปไม่ได้' : empty}</span>
  return (
    <figure className="m-0 flex flex-col gap-1">
      {href ? <a href={href} target="_blank" rel="noreferrer">{body}</a> : body}
      <figcaption className="text-xs text-muted text-center">{label}</figcaption>
    </figure>
  )
}

function Pair({ p, onKeep, busy }) {
  const why = WHY[p.kind] || p.kind
  return (
    <li className="border border-line rounded-xl p-3 flex flex-col gap-2.5">
      <div className="grid grid-cols-[1fr_auto_1fr] gap-2 items-center">
        <Thumb label="ใบใหม่" src={p.pre ? null : `/api/trips/${p.trip_id}/image`} href={p.pre ? p.link : `/api/trips/${p.trip_id}/image`} />
        <span className="text-sm text-muted" aria-hidden="true">=</span>
        <Thumb label="ใบเดิม" src={p.twin_id ? `/api/trips/${p.twin_id}/image` : null} href={p.twin_id ? `/api/trips/${p.twin_id}/image` : null} />
      </div>
      <div className="text-sm">
        {!p.pre && <p className="font-medium">{[p.rider, day(p.date), p.net != null ? `฿${fmt(p.net)}` : ''].filter(Boolean).join(' · ')}</p>}
        <p className="text-ink-soft">{why}{p.code ? ` · ${p.code}` : ''}</p>
        <p className="text-muted break-words">ใบเดิมอยู่ใน {p.twin_album || 'รูปที่เคยส่งและอ่านไปแล้ว'}</p>
      </div>
      {p.restorable && (
        <button onClick={() => onKeep(p)} disabled={busy}
          className="self-start min-h-10 px-3 rounded-lg border border-line hover:bg-ground text-sm disabled:opacity-50">
          ไม่ใช่งานซ้ำ · เก็บไว้
        </button>
      )}
    </li>
  )
}

function Detail({ week, album, onBack, onChanged }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const top = useRef(null)
  // on a phone the panel replaces the list below the totals: bring it into view
  useEffect(() => {
    if (window.innerWidth < 1024) top.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [album.album])
  const load = useCallback(() => api.duplicateAlbum(week, album.album).then(setData).catch((e) => setError(e.message)),
    [week, album.album])
  useEffect(() => { setData(null); setNote(''); load() }, [load])

  const keep = (p) => {
    if (!window.confirm('เก็บเที่ยวนี้ไว้ ไม่นับเป็นงานซ้ำ?\n\nแถวจะกลับเข้าคิวตรวจ ให้คนกดอนุมัติอีกครั้ง')) return
    setBusy(true)
    api.restoreTrip(p.trip_id)
      .then(() => { setNote('เก็บไว้แล้ว — แถวกลับเข้าคิวตรวจ'); load(); onChanged() })
      .catch((e) => setNote(`เก็บไม่สำเร็จ: ${e.message}`)).finally(() => setBusy(false))
  }

  return (
    <section ref={top} aria-labelledby="det-h" className="scroll-mt-4 bg-white border border-line rounded-xl p-4 sm:p-5 flex flex-col gap-3.5">
      <button onClick={onBack} className="lg:hidden self-start flex items-center gap-1 min-h-10 -ml-1 text-sm text-ink-soft">
        <Icon name="back" size={18} />กลับไปรายการอัลบั้ม
      </button>
      <div>
        <p className="text-sm text-muted">อัลบั้มที่เลือก</p>
        <h2 id="det-h" className="text-[17px] font-semibold break-words">{album.album}</h2>
        <p className="text-sm text-ink-soft">
          วางเมื่อ {when(album.first)} · {album.dup ? `ซ้ำ ${fmt(album.dup)} เที่ยว` : 'ไม่ซ้ำ'}
        </p>
      </div>
      <p className="text-sm text-ink-soft bg-ground rounded-lg px-3 py-2.5">
        เที่ยวที่ซ้ำไม่ถูกนับในไฟล์ส่งลูกค้า ถ้าคิดว่าไม่ใช่งานซ้ำ กด "เก็บไว้" แถวจะกลับเข้าคิวตรวจ
      </p>
      {note && <p className="text-sm text-ok-ink">{note}</p>}
      {error ? <p className="text-sm text-danger-ink">โหลดไม่ได้: {error}</p>
        : !data ? <p className="text-sm text-muted">กำลังโหลด…</p>
          : data.pairs.length === 0 ? <p className="text-sm text-muted">อัลบั้มนี้ไม่มีงานซ้ำ</p>
            : <ul className="flex flex-col gap-3">{data.pairs.map((p, i) => <Pair key={p.trip_id || `pre-${i}`} p={p} onKeep={keep} busy={busy} />)}</ul>}
    </section>
  )
}

export default function DupAlbums() {
  const [week, setWeek] = useState('')
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [onlyDup, setOnlyDup] = useState(true)
  const [picked, setPicked] = useState(null)

  const load = useCallback((w) => api.duplicateAlbums(w).then((d) => { setData(d); setError('') })
    .catch((e) => setError(e.message)), [])
  useEffect(() => { setPicked(null); load(week) }, [week, load])

  if (error && !data) return <p className="text-sm text-danger-ink">โหลดไม่ได้: {error}</p>
  if (!data) return <p className="text-sm text-muted">กำลังโหลด…</p>
  if (!data.week) return <p className="text-sm text-muted">ยังไม่มีสัปดาห์ให้ดู</p>

  const albums = [...data.albums].reverse()            // newest first
  const dups = albums.filter((a) => a.status === 'ซ้ำ')
  const shown = onlyDup ? dups : albums
  const pre = albums.reduce((s, a) => s + (a.pre || 0), 0)
  const post = albums.reduce((s, a) => s + (a.post || 0), 0)
  const waiting = albums.filter((a) => a.waiting).length
  const current = picked && albums.find((a) => a.album === picked)

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm text-muted">งานซ้ำรายอัลบั้ม · นับเฉพาะในสัปดาห์เดียวกัน</p>
          <h1 className="text-2xl sm:text-[28px] font-semibold tracking-tight">{wk(data.label)}</h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div role="group" aria-label="เลือกสัปดาห์" className="flex gap-2 overflow-x-auto">
            {[...data.weeks].slice(0, 4).reverse().map((w) => {
              const on = w.date_from === data.week
              return (
                <button key={w.date_from} onClick={() => setWeek(w.date_from)} aria-pressed={on}
                  className={`shrink-0 min-h-10 px-4 rounded-full text-sm border ${on ? 'bg-ink text-white border-ink' : 'bg-white text-ink-soft border-line'}`}>
                  {wk(w.label)}{w.closed ? ' · ปิดแล้ว' : ''}
                </button>
              )
            })}
          </div>
          <a href={api.duplicateReportUrl(data.week)}
            className="min-h-10 px-4 rounded-lg border border-line bg-white hover:bg-ground text-sm flex items-center gap-2">
            <Icon name="download" size={18} />ดาวน์โหลดรายงาน (Excel)
          </a>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
        <Tile label="อัลบั้มสัปดาห์นี้" value={fmt(albums.length)} sub={albums[0] ? `วางล่าสุด ${when(albums[0].first)}` : ''} />
        <Tile label="อัลบั้มที่มีงานซ้ำ" value={fmt(dups.length)} sub="ควรแจ้งแอดมินเจ้าของอัลบั้ม" tone={dups.length ? 'text-danger-ink' : 'text-ok-ink'} />
        <Tile label="เที่ยวซ้ำทั้งหมด" value={fmt(pre + post)} sub={`ส่งไฟล์เดิมซ้ำ ${fmt(pre)} · เลขจองซ้ำ ${fmt(post)}`} tone={pre + post ? 'text-danger-ink' : 'text-ok-ink'} />
        <Tile label="ยังอ่านไม่ครบ" value={fmt(waiting)} sub="อัลบั้ม · ตัวเลขซ้ำอาจเพิ่ม" tone={waiting ? 'text-warn-ink' : 'text-ink'} />
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_420px] items-start">
        <section aria-labelledby="alb-h" className={`bg-white border border-line rounded-xl overflow-hidden ${current ? 'hidden lg:block' : ''}`}>
          <div className="px-4 sm:px-5 py-3.5 border-b border-line-soft flex flex-wrap items-center justify-between gap-3">
            <h2 id="alb-h" className="text-[17px] font-semibold">อัลบั้มทั้งสัปดาห์ <span className="font-normal text-sm text-muted">· ล่าสุดอยู่บน</span></h2>
            <div role="group" aria-label="กรอง" className="flex gap-1 bg-ground rounded-lg p-0.5">
              {[[false, `ทั้งหมด ${fmt(albums.length)}`], [true, `เฉพาะที่ซ้ำ ${fmt(dups.length)}`]].map(([v, label]) => (
                <button key={label} onClick={() => setOnlyDup(v)} aria-pressed={onlyDup === v}
                  className={`min-h-9 px-3 rounded-md text-sm ${onlyDup === v ? 'bg-white text-ink font-semibold shadow-sm' : 'text-ink-soft'}`}>{label}</button>
              ))}
            </div>
          </div>
          {shown.length === 0 ? (
            <p className="px-5 py-6 text-sm text-muted">{onlyDup ? 'ไม่มีอัลบั้มที่ซ้ำในสัปดาห์นี้' : 'ยังไม่มีอัลบั้ม'}</p>
          ) : (
            <ul>
              {shown.map((a) => {
                const dup = a.status === 'ซ้ำ'
                const on = a.album === picked
                return (
                  <li key={a.album}>
                    <button onClick={() => setPicked(a.album)} aria-current={on ? 'true' : undefined}
                      className={`w-full text-left px-4 sm:px-5 py-3 border-b border-line-soft flex items-start gap-3 border-l-[3px] ${on ? 'bg-accent-bg border-l-accent' : 'border-l-transparent hover:bg-ground'}`}>
                      <span className="flex-1 min-w-0">
                        <span className="block font-medium break-words">{a.album}</span>
                        <span className="block text-sm text-muted">{when(a.first)} · อ่านแล้ว {fmt(a.read)} · ลงงาน {fmt(a.filed)}</span>
                        {dup && a.with && <span className="block text-sm text-danger-ink break-words">ซ้ำกับ {a.with}</span>}
                        {a.waiting ? <span className="inline-block mt-1 text-xs text-warn-ink bg-warn-bg rounded px-1.5 py-0.5">รออ่าน {fmt(a.waiting)} · ตัวเลขซ้ำอาจเพิ่ม</span> : null}
                      </span>
                      <span className={`shrink-0 text-sm font-semibold rounded-full px-3 py-1 ${dup ? 'bg-danger-bg text-danger-ink' : 'bg-ok-bg text-ok-ink'}`}>
                        {dup ? `ซ้ำ ${fmt(a.dup)}` : 'ไม่ซ้ำ'}
                      </span>
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
          <p className="px-5 py-3 text-xs text-muted">ข้อมูล ณ {data.as_of} · อัปเดตทุก 2 นาที</p>
        </section>

        {current ? (
          <Detail week={data.week} album={current} onBack={() => setPicked(null)} onChanged={() => load(data.week)} />
        ) : (
          <aside className="hidden lg:block bg-white border border-line rounded-xl p-5 text-sm text-muted">
            เลือกอัลบั้มทางซ้ายเพื่อดูว่าแต่ละเที่ยวซ้ำกับใบไหน
          </aside>
        )}
      </div>
    </div>
  )
}
