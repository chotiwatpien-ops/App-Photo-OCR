import { useCallback, useEffect, useState } from 'react'
import { api } from './api.js'
import Icon from './Icon.jsx'

// งานซ้ำ — one week answered top to bottom (Fiat 2026-11-11: "ดูง่ายๆ และตรวจสอบง่าย"):
//   1. the verdict: is any trip counted twice in the customer's file? (checked, not assumed)
//   2. what a person still has to decide
//   3. what the system already took out, by reason
//   4. albums, to know which admin to tell
// Counted within the week only: a slip delivered in an earlier week is work again (customer,
// 2026-09-14). One request per week from the server's cache, no polling, and pictures load from
// Drive in the viewer's browser first, so opening this tab adds next to nothing to the database.

const fmt = (n) => (n ?? 0).toLocaleString('th-TH')
const TH_MONTHS = ['ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.', 'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.']
const wk = (label) => (label || '').replace(/^\d{4}-W/, 'WK')
const day = (iso) => { if (!iso) return ''; const d = new Date(`${iso}T00:00:00`); return `${d.getDate()} ${TH_MONTHS[d.getMonth()]}` }
const when = (s) => {
  if (!s) return ''
  const d = new Date(String(s).replace(' ', 'T'))
  if (Number.isNaN(d.getTime())) return s
  return `${d.getDate()} ${TH_MONTHS[d.getMonth()]} ${d.toLocaleTimeString('th-TH', { hour: '2-digit', minute: '2-digit' })}`
}
const baht = (n) => (n == null ? '' : `฿${fmt(n)}`)

// every reason a repeat is taken out, said the way Ops says it, and whether anyone has to act
const REASONS = {
  'ไฟล์เดิมส่งซ้ำ': { title: 'รูปเดียวกันทุกจุด อ่านแล้ว', why: 'ไฟล์เหมือนใบที่นับไปแล้วทุกไบต์' },
  'รหัสการจองซ้ำในสัปดาห์เดียวกัน': { title: 'เลขจองซ้ำในสัปดาห์นี้', why: 'สลิปคนละรูป แต่เป็นเที่ยวเดียวกัน (เลขจองตรงกัน)' },
  'ครึ่งล่างของงานที่นับไปแล้ว': { title: 'ครึ่งล่างของเที่ยวที่นับแล้ว', why: 'ส่วนล่างของสลิปที่จับคู่ไปแล้ว' },
  'ข้อมูลตรงกัน แต่เลขจองไม่ตรงทุกตัว': { title: 'ข้อมูลตรงกัน เลขจองต่างเล็กน้อย', why: 'AI อ่านเลขจองเพี้ยนตรงที่ขึ้นบรรทัดใหม่ หรือเส้นทาง ระยะ ยอดตรงกันทุกอย่าง' },
}
const reason = (k) => REASONS[k] || { title: k, why: '' }

const driveId = (url) => (url || '').match(/\/d\/([\w-]+)|[?&]id=([\w-]+)/)?.slice(1).find(Boolean)

/** Drive first (the viewer's own Google session, no load on our server or database), then the
 *  copy our server keeps, then a link. */
function Thumb({ tripId, drive, label }) {
  const id = driveId(drive)
  const steps = [id && `https://drive.google.com/thumbnail?id=${id}&sz=w600`, tripId && `/api/trips/${tripId}/image`].filter(Boolean)
  const [i, setI] = useState(0)
  const open = id ? `https://drive.google.com/file/d/${id}/view` : steps[steps.length - 1]
  return (
    <figure className="m-0 flex flex-col gap-1 min-w-0">
      {i < steps.length ? (
        <a href={open} target="_blank" rel="noreferrer">
          <img src={steps[i]} alt={label} loading="lazy" referrerPolicy="no-referrer" onError={() => setI((x) => x + 1)}
            className="w-full h-40 object-cover object-top rounded-lg border border-line bg-ground" />
        </a>
      ) : (
        <span className="w-full h-40 rounded-lg border border-line bg-ground flex flex-col items-center justify-center gap-1 text-xs text-muted text-center px-2">
          แสดงรูปไม่ได้
          {id && <a href={open} target="_blank" rel="noreferrer" className="text-accent hover:underline">เปิดใน Drive</a>}
        </span>
      )}
      <figcaption className="text-xs text-muted text-center">{label}</figcaption>
    </figure>
  )
}

function PairCard({ p, children }) {
  const same = p.net != null && p.net === p.twin_net
  return (
    <li className="border border-line rounded-xl p-3 flex flex-col gap-2.5">
      <div className="grid grid-cols-2 gap-2">
        <Thumb label="ใบนี้" tripId={p.trip_id} drive={p.url} />
        <Thumb label="ใบที่นับไปแล้ว" tripId={p.twin_id} drive={p.twin_url} />
      </div>
      <dl className="text-sm grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
        <dt className="text-muted">เหตุผล</dt><dd>{reason(p.kind).title}</dd>
        <dt className="text-muted">เลขจอง</dt><dd className="font-mono break-all">{p.code || '—'}</dd>
        <dt className="text-muted">ยอด</dt>
        <dd>{baht(p.net)} · ใบที่นับแล้ว {baht(p.twin_net)} {same && <span className="text-ok-ink">· ตรงกัน</span>}</dd>
        <dt className="text-muted">ไรเดอร์</dt><dd>{[p.rider, day(p.date)].filter(Boolean).join(' · ')}</dd>
        <dt className="text-muted">อัลบั้ม</dt><dd className="break-words">{p.album}{p.twin_album && p.twin_album !== p.album ? ` (ใบที่นับอยู่ใน ${p.twin_album})` : ''}</dd>
      </dl>
      {children}
    </li>
  )
}

function Verdict({ d, onQueue }) {
  const twice = d.twice.length, decide = d.decide.length, suspect = (d.suspect || []).length
  const waiting = d.albums.reduce((s, a) => s + (a.waiting || 0), 0)
  const [tone, head, body] = twice
    ? ['danger', `ไฟล์ลูกค้ามีเที่ยวที่นับสองครั้ง ${fmt(twice)} เที่ยว`, 'แจ้งผู้ดูแลระบบ ห้ามส่งไฟล์สัปดาห์นี้จนกว่าจะแก้']
    : decide
      ? ['warn', `รอคนตัดสิน ${fmt(decide)} เที่ยว`, 'เที่ยวเหล่านี้ยังไม่อยู่ในไฟล์ลูกค้า ดูรูปคู่กันแล้วตัดสินในคิวตรวจ']
      : ['ok', 'เรียบร้อย ไม่มีเที่ยวไหนนับซ้ำ', 'ไม่มีอะไรต้องทำในหน้านี้']
  const box = { ok: 'bg-ok-bg text-ok-ink', warn: 'bg-warn-bg text-warn-ink', danger: 'bg-danger-bg text-danger-ink' }[tone]
  return (
    <section aria-label="ผลตรวจ" className={`rounded-xl px-4 py-4 sm:px-5 flex flex-wrap items-center gap-x-6 gap-y-3 ${box}`}>
      <div className="flex-1 min-w-[16rem]">
        <p className="text-xl font-semibold">{head}</p>
        <p className="text-sm">{body}</p>
        <p className="text-sm mt-1.5 opacity-90">
          ตรวจแล้ว: เที่ยวที่อนุมัติ {fmt(d.approved)} เที่ยว {twice ? `นับซ้ำ ${fmt(twice)} ชุด` : 'ไม่มีเที่ยวไหนนับสองครั้ง'}
          {suspect ? ` · เส้นทาง ระยะ ยอดตรงกัน ${fmt(suspect)} ชุด ควรเปิดรูปดู (อาจเป็นคนนั่งเส้นทางประจำ)` : ''}
          {waiting ? ` · ยังรออ่านอีก ${fmt(waiting)} รูป ตัวเลขอาจเปลี่ยน` : ''}
        </p>
      </div>
      {decide > 0 && (
        <button onClick={onQueue} className="min-h-11 px-4 rounded-lg bg-ink text-white text-sm font-semibold">
          ไปตัดสินในคิวตรวจ ({fmt(decide)})
        </button>
      )}
    </section>
  )
}

function Section({ title, sub, children }) {
  return (
    <section className="bg-white border border-line rounded-xl p-4 sm:p-5 flex flex-col gap-3">
      <div>
        <h2 className="text-[17px] font-semibold">{title}</h2>
        {sub && <p className="text-sm text-muted">{sub}</p>}
      </div>
      {children}
    </section>
  )
}

function Copies({ copies }) {
  const [open, setOpen] = useState(false)
  const [n, setN] = useState(20)
  if (!copies.length) return null
  const albums = new Set(copies.map((c) => c.album)).size
  return (
    <li className="border border-line rounded-xl p-3 flex flex-col gap-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="font-medium">ไฟล์รูปเดียวกันเป๊ะ ส่งมาซ้ำ <span className="text-danger-ink">{fmt(copies.length)} ใบ</span></p>
        <button onClick={() => setOpen((o) => !o)} aria-expanded={open} className="min-h-9 text-sm text-accent hover:underline">
          {open ? 'ซ่อนรายชื่อไฟล์' : 'ดูรายชื่อไฟล์'}
        </button>
      </div>
      <p className="text-sm text-ink-soft">
        ระบบตัดออกก่อนส่งให้ AI อ่าน จึงไม่เสียค่าอ่าน และไม่ได้นับเป็นงาน ส่วนใหญ่เกิดจาก LINE บันทึกรูปเดิมซ้ำ (ชื่อไฟล์ลงท้าย _1, _2)
        {albums > 1 ? ` · จาก ${fmt(albums)} อัลบั้ม` : ''} ไม่ต้องทำอะไร
      </p>
      {open && (
        <>
          <ul className="text-sm divide-y divide-line-soft border-t border-line-soft">
            {copies.slice(0, n).map((c, i) => (
              <li key={`${c.file}-${i}`} className="py-1.5 flex flex-wrap gap-x-2">
                {c.link ? <a href={c.link} target="_blank" rel="noreferrer" className="text-accent hover:underline">{c.file}</a> : <span>{c.file}</span>}
                <span className="text-muted break-all">= {c.same_as}</span>
              </li>
            ))}
          </ul>
          {n < copies.length && (
            <button onClick={() => setN((x) => x + 50)} className="self-start min-h-9 text-sm text-accent hover:underline">
              ดูเพิ่มอีก {fmt(Math.min(50, copies.length - n))} ใบ (จากทั้งหมด {fmt(copies.length)})
            </button>
          )}
        </>
      )}
    </li>
  )
}

export default function DupAlbums({ onGo }) {
  const [week, setWeek] = useState('')
  const [d, setD] = useState(null)
  const [error, setError] = useState('')
  const [album, setAlbum] = useState('')
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')

  const load = useCallback((w) => api.duplicateWeek(w).then((r) => { setD(r); setError('') })
    .catch((e) => setError(e.message)), [])
  useEffect(() => { setAlbum(''); setNote(''); load(week) }, [week, load])

  const toQueue = () => {
    try { sessionStorage.setItem('queue.only', 'dup') } catch { /* private window: the queue opens on every row */ }
    onGo?.('queue')
  }
  const keep = (p) => {
    if (!window.confirm('ไม่ใช่งานซ้ำ เก็บเที่ยวนี้ไว้?\n\nแถวจะกลับเข้าคิวตรวจ ให้คนกดอนุมัติอีกครั้ง')) return
    setBusy(true)
    api.restoreTrip(p.trip_id)
      .then(() => { setNote('เก็บไว้แล้ว แถวกลับเข้าคิวตรวจ'); load(d.week) })
      .catch((e) => setNote(`เก็บไม่สำเร็จ: ${e.message}`)).finally(() => setBusy(false))
  }

  if (error && !d) return <p className="text-sm text-danger-ink">โหลดไม่ได้: {error}</p>
  if (!d) return <p className="text-sm text-muted">กำลังโหลด…</p>
  if (!d.week) return <p className="text-sm text-muted">ยังไม่มีสัปดาห์ให้ดู</p>

  const mine = (x) => !album || x.album === album
  const decide = d.decide.filter(mine)
  const removed = d.removed.filter(mine)
  const copies = d.copies.filter(mine)
  const groups = Object.entries(removed.reduce((g, p) => ({ ...g, [p.kind]: [...(g[p.kind] || []), p] }), {}))
  const out = d.removed.length + d.copies.length
  const albums = [...d.albums].reverse()                 // newest first
  const pending = d.decide.reduce((m, p) => ({ ...m, [p.album]: (m[p.album] || 0) + 1 }), {})

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm text-muted">งานซ้ำ · นับเฉพาะในสัปดาห์เดียวกัน · ข้อมูล ณ {d.as_of.slice(11)} น.</p>
          <h1 className="text-2xl sm:text-[28px] font-semibold tracking-tight">{wk(d.label)}</h1>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div role="group" aria-label="เลือกสัปดาห์" className="flex gap-2 overflow-x-auto">
            {d.weeks.slice(0, 4).reverse().map((w) => {
              const on = w.date_from === d.week
              return (
                <button key={w.date_from} onClick={() => setWeek(w.date_from)} aria-pressed={on}
                  className={`shrink-0 min-h-10 px-4 rounded-full text-sm border ${on ? 'bg-ink text-white border-ink' : 'bg-white text-ink-soft border-line'}`}>
                  {wk(w.label)}{w.closed ? ' · ปิดแล้ว' : ''}
                </button>
              )
            })}
          </div>
          <a href={api.duplicateReportUrl(d.week)}
            className="min-h-10 px-4 rounded-lg border border-line bg-white hover:bg-ground text-sm flex items-center gap-2">
            <Icon name="download" size={18} />รายงาน Excel
          </a>
        </div>
      </div>

      <Verdict d={d} onQueue={toQueue} />

      <div className="grid grid-cols-3 gap-3 text-center">
        {[['นับในไฟล์ลูกค้า', d.approved, 'text-ink'], ['รอคนตัดสิน', d.decide.length, d.decide.length ? 'text-warn-ink' : 'text-ink'],
          ['ระบบตัดออกให้แล้ว', out, 'text-ink']].map(([label, v, tone]) => (
          <div key={label} className="bg-white border border-line rounded-xl px-2 py-3">
            <p className={`text-[22px] sm:text-[26px] leading-tight font-semibold tabular-nums ${tone}`}>{fmt(v)}</p>
            <p className="text-sm text-muted">{label}</p>
          </div>
        ))}
      </div>

      {album && (
        <p className="text-sm flex flex-wrap items-center gap-2">
          <span className="bg-accent-bg rounded-full px-3 py-1">เฉพาะอัลบั้ม {album}</span>
          <button onClick={() => setAlbum('')} className="min-h-9 text-accent hover:underline">ดูทุกอัลบั้ม</button>
        </p>
      )}
      {note && <p className="text-sm text-ok-ink">{note}</p>}

      {decide.length > 0 && (
        <Section title={`รอคนตัดสิน ${fmt(decide.length)} เที่ยว`}
          sub="ตรงกับเที่ยวที่นับไปแล้ว (เลขจอง หรือเส้นทาง ระยะ ยอด) แต่ระบบไม่ตัดเอง ถ้าเป็นเที่ยวเดียวกันให้ลบในคิวตรวจ ถ้าไม่ใช่ให้อนุมัติ">
          <ul className="grid gap-3 md:grid-cols-2">
            {decide.map((p) => (
              <PairCard key={p.trip_id} p={p}>
                <button onClick={toQueue} className="self-start min-h-10 px-3 rounded-lg border border-line hover:bg-ground text-sm">ตัดสินในคิวตรวจ</button>
              </PairCard>
            ))}
          </ul>
        </Section>
      )}

      <Section title={`ระบบตัดออกให้แล้ว ${fmt(removed.length + copies.length)} รายการ`}
        sub="ไม่ได้นับในไฟล์ลูกค้า ดูเพื่อยืนยันหรือแจ้งแอดมินเจ้าของอัลบั้ม ถ้าระบบตัดผิด กด “ไม่ใช่งานซ้ำ”">
        {removed.length + copies.length === 0 ? <p className="text-sm text-muted">ไม่มี</p> : (
          <ul className="flex flex-col gap-3">
            <Copies copies={copies} />
            {groups.map(([kind, ps]) => (
              <li key={kind} className="flex flex-col gap-2">
                <p className="font-medium">{reason(kind).title} <span className="text-danger-ink">{fmt(ps.length)} เที่ยว</span>
                  <span className="block text-sm font-normal text-ink-soft">{reason(kind).why}</span></p>
                <ul className="grid gap-3 md:grid-cols-2">
                  {ps.map((p) => (
                    <PairCard key={p.trip_id} p={p}>
                      <button onClick={() => keep(p)} disabled={busy}
                        className="self-start min-h-10 px-3 rounded-lg border border-line hover:bg-ground text-sm disabled:opacity-50">
                        ไม่ใช่งานซ้ำ · เก็บไว้
                      </button>
                    </PairCard>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title={`อัลบั้มสัปดาห์นี้ ${fmt(albums.length)} อัลบั้ม`} sub="ใช้แจ้งแอดมินว่าอัลบั้มไหนส่งงานซ้ำ กดชื่ออัลบั้มเพื่อดูเฉพาะอัลบั้มนั้น">
        <div className="overflow-x-auto -mx-4 sm:mx-0">
          <table className="w-full text-sm tabular-nums">
            <thead>
              <tr className="text-left text-muted border-b border-line">
                <th className="font-normal py-2 px-4 sm:px-2">อัลบั้ม</th>
                <th className="font-normal py-2 px-2 text-right">อ่านแล้ว</th>
                <th className="font-normal py-2 px-2 text-right">ซ้ำ</th>
                <th className="font-normal py-2 px-2 text-right">% ซ้ำ</th>
                <th className="font-normal py-2 px-2 text-right">รออ่าน</th>
              </tr>
            </thead>
            <tbody>
              {albums.map((a) => (
                <tr key={a.album} className={`border-b border-line-soft ${a.album === album ? 'bg-accent-bg' : ''}`}>
                  <td className="py-2 px-4 sm:px-2">
                    <button onClick={() => setAlbum(a.album === album ? '' : a.album)} className="text-left hover:underline break-words">{a.album}</button>
                    <span className="block text-xs text-muted">{when(a.first)}{a.with ? ` · ซ้ำกับ ${a.with}` : ''}</span>
                  </td>
                  <td className="py-2 px-2 text-right">{fmt(a.read)}</td>
                  <td className={`py-2 px-2 text-right font-semibold ${a.dup ? 'text-danger-ink' : pending[a.album] ? 'text-warn-ink' : 'text-ok-ink'}`}>
                    {a.dup ? fmt(a.dup) : pending[a.album] ? 'รอตัดสิน' : 'ไม่ซ้ำ'}
                    {a.dup && pending[a.album] ? <span className="block text-xs font-normal text-warn-ink">+ รอตัดสิน {fmt(pending[a.album])}</span> : null}
                  </td>
                  <td className="py-2 px-2 text-right">{a.pct != null ? `${(a.pct * 100).toFixed(1)}%` : ''}</td>
                  <td className="py-2 px-2 text-right">{a.waiting ? fmt(a.waiting) : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
    </div>
  )
}
