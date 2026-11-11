import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api.js'
import Icon from './Icon.jsx'

// คิวตรวจ — the rows the system was not sure of, one at a time, with the picture beside the
// numbers it read. Redesigned 2026-10 for the customer: every reason is said in plain words with
// the row's own numbers, no job ids or file names, and on a phone the three decisions sit in a bar
// above the tab bar. Every behaviour of the earlier screen is kept: keyboard, zoom, the running
// sum, 'fill this first' boxes, approve-the-rest-of-this-rider, and the place kept across reloads.

const n = (v) => (v === null || v === undefined || v === '' ? null : Number(v))
const fmt = (v) => (v === null || v === undefined ? '—' : Number(v).toLocaleString('th-TH'))
const baht = (v) => (v === null || v === undefined ? '—' : `฿${fmt(v)}`)
const TH_MONTHS = ['ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.', 'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.']
const day = (iso) => { if (!iso) return 'ไม่มีวันที่'; const d = new Date(`${iso}T00:00:00`); return `${d.getDate()} ${TH_MONTHS[d.getMonth()]}` }

/** The same identity the backend checks: คุณได้รับ = ค่ารอบ + โบนัส + เทอร์โบ.
 *  Recomputed here so the reviewer sees the sum settle while they are still typing. */
function money(t) {
  const net = n(t.net_earnings), base = n(t.base_fare)
  const bonus = n(t.bonus) || 0, turbo = n(t.turbo) || 0
  if (net === null || base === null) return { known: false }
  const sum = base + bonus + turbo
  const diff = Math.round((net - sum) * 100) / 100
  // within ฿1 passes, the same tolerance as the server's check (extractor.arithmetic_check)
  return { known: true, net, base, bonus, turbo, sum, diff, ok: Math.abs(diff) <= 1 }
}

/** Grab's commission never reaches 35% of the fare — more than that means the passenger figure
 *  picked up something that is not fare (the old screen's receipt total adds app fee and tolls). */
function fareWarning(t) {
  const p = n(t.passenger_total), base = n(t.base_fare)
  if (p === null || !base) return null
  const pct = Math.round(((p - base) / base) * 100)
  if (pct > 35) return `Passenger Fare ${baht(p)} สูงกว่าค่ารอบ ${baht(base)} ถึง ${pct}% — ปกติไม่เกิน 35% ลองดูในรูปอีกครั้ง`
  if (pct < -2) return `Passenger Fare ${baht(p)} ต่ำกว่าค่ารอบ ${baht(base)} ${-pct}% — ผู้โดยสารจ่ายน้อยกว่าที่คนขับได้ ลองดูในรูปอีกครั้ง`
  return null
}

/** Why this row is sitting here, said with its own numbers. */
function why(t) {
  if (t.duplicate_of) {
    return { tone: 'danger', chip: 'สงสัยว่าซ้ำ', head: 'รูปนี้ซ้ำกับอีกแถวของไรเดอร์คนเดียวกัน',
             body: 'เลขจองตรงกัน — ถ้าเป็นเที่ยวเดียวกันจริง ให้กดลบ' }
  }
  if (t.seen_in_job) {
    return { tone: 'danger', chip: 'อนุมัติไปแล้ว', head: 'เลขจองนี้อนุมัติไปแล้วในสัปดาห์นี้',
             body: 'ถ้าอนุมัติอีก เงินจะถูกนับสองรอบ — ดูรูปแล้วลบถ้าซ้ำจริง' }
  }
  if (t.check_status === 'fail') {
    const m = money(t)
    // the backend re-checks on every edit, but never call a row broken while its own numbers
    // are sitting there adding up — that reads as the page arguing with itself
    if (m.known && m.ok) {
      return { tone: 'ok', chip: 'แก้แล้ว', head: `แก้แล้ว ลงตัว — ${baht(m.base)} + ${baht(m.bonus)} + ${baht(m.turbo)} = ${baht(m.net)}`,
               body: 'เทียบกับรูปอีกครั้งแล้วกดอนุมัติได้เลย' }
    }
    return { tone: 'warn', chip: 'ตัวเลขไม่ลงตัว',
             head: m.known ? `ตัวเลขไม่ลงตัว ${m.diff > 0 ? 'ขาดไป' : 'เกินมา'} ${baht(Math.abs(m.diff))}` : 'ตัวเลขในรูปไม่สอดคล้องกัน',
             body: m.known
               ? `คุณได้รับ ${baht(m.net)} แต่ ค่ารอบ ${baht(m.base)} + โบนัส ${baht(m.bonus)} + เทอร์โบ ${baht(m.turbo)} = ${baht(m.sum)} — เทียบกับรูปแล้วแก้ช่องที่ผิด`
               : 'เทียบกับรูปแล้วกรอกให้ครบ' }
  }
  if (t.check_status === 'no_data') {
    const miss = ['base_fare', 'net_earnings'].filter((k) => n(t[k]) === null)
    const th = { base_fare: 'ค่ารอบ', net_earnings: 'คุณได้รับ' }
    return { tone: 'warn', chip: 'ข้อมูลไม่ครบ', head: 'AI อ่านตัวเลขจากรูปได้ไม่ครบ',
             body: miss.length ? `ยังขาด ${miss.map((k) => th[k]).join(' · ')} — อ่านจากรูปแล้วกรอก` : 'อ่านจากรูปแล้วยืนยัน' }
  }
  if (!t.trip_date) {
    return { tone: 'wait', chip: 'ไม่มีวันที่', head: 'ยังไม่รู้วันที่ของเที่ยวนี้', body: 'ใส่วันที่ก่อน ถึงจะอนุมัติได้' }
  }
  return { tone: 'ok', chip: 'ผ่าน รอกด', head: 'ตัวเลขผ่านการตรวจแล้ว รอแค่คนกดอนุมัติ', body: 'ดูรูปคร่าวๆ แล้วกดอนุมัติได้เลย' }
}

/** The bucket a row is counted and filtered under — the same order the chips show. */
function kind(t) {
  if (t.duplicate_of || t.seen_in_job) return 'dup'
  if (t.check_status === 'fail') return 'fail'
  if (t.check_status === 'no_data') return 'no_data'
  if (!t.trip_date) return 'nodate'
  return 'ready'
}

const PILL = {
  danger: 'bg-danger-bg text-danger-ink', warn: 'bg-warn-bg text-warn-ink',
  wait: 'bg-wait-bg text-wait-ink', ok: 'bg-ok-bg text-ok-ink',
}

/** What still has to be typed before this row can move, and how badly.
 *  'block' — approval is refused without it. 'want' — the check cannot run without it, so the
 *  row would sit here forever. Anything already filled asks for nothing. */
function needed(t) {
  const need = {}
  if (!t.trip_date) need.trip_date = 'block'
  if (n(t.net_earnings) === null) need.net_earnings = 'want'
  if (n(t.base_fare) === null) need.base_fare = 'want'
  return need
}

const NEED_BOX = { block: 'border-danger bg-danger-bg', want: 'border-warn bg-warn-bg' }
const NEED_TAG = { block: 'text-danger-ink', want: 'text-warn-ink' }
const NEED_WORD = { block: 'ต้องกรอกก่อนอนุมัติ', want: 'ยังขาด' }

/** One number the reviewer can correct without leaving the queue.
 *  Enter saves and moves to the next box; Ctrl+Enter saves, approves the row and moves on,
 *  so a row of corrections never needs the mouse. */
function Field({ label, value, onSave, onApprove, type = 'number', hint, need, order }) {
  const [v, setV] = useState(value ?? '')
  const [saving, setSaving] = useState(false)
  const box = useRef(null)
  const sent = useRef(null)               // the value last saved, until the row comes back with it
  useEffect(() => { setV(value ?? ''); sent.current = null }, [value])
  const dirty = String(v) !== String(value ?? '')
  const commit = async () => {
    if (!dirty || sent.current === String(v)) return true
    setSaving(true)
    try {
      const ok = await onSave(v === '' ? null : (type === 'number' ? Number(v) : v))
      if (ok !== false) sent.current = String(v)
      return ok
    } finally { setSaving(false) }
  }
  const next = () => {
    const all = [...document.querySelectorAll('[data-qfield]')]
    const i = all.indexOf(box.current)
    if (all[i + 1]) { all[i + 1].focus(); all[i + 1].select?.() } else box.current?.blur()
  }
  // a field only asks while it is still empty; typing into it settles it immediately
  const asking = need && String(v) === ''
  return (
    <label className="flex flex-col gap-1">
      <span className="text-sm text-ink-soft">
        {label}
        {asking && <span className={`ml-1 font-medium ${NEED_TAG[need]}`}>· {NEED_WORD[need]}</span>}
      </span>
      <input type={type} value={v} disabled={saving} ref={box} data-need={asking ? need : undefined}
        data-qfield={order}
        inputMode={type === 'number' ? 'decimal' : undefined}
        onChange={(e) => setV(e.target.value)}
        onBlur={commit}
        onKeyDown={async (e) => {
          if (e.key !== 'Enter') return
          e.preventDefault()
          if (e.ctrlKey || e.metaKey) {
            const ok = await commit()
            box.current?.blur()
            if (ok !== false) onApprove?.()
          } else {
            await commit()
            next()
          }
        }}
        className={`min-h-11 w-full rounded-lg border px-3 text-[15px] outline-none disabled:opacity-50
          ${dirty ? 'border-accent bg-accent-bg' : asking ? NEED_BOX[need] : 'border-line bg-white focus:border-accent'}`} />
      {hint && <span className="text-xs text-muted">{hint}</span>}
    </label>
  )
}

/** One picture that says when it is loading or missing, instead of going blank. */
function Pic({ src, alt, scale }) {
  const [state, setState] = useState('loading')
  return (
    <span className="relative block min-w-0" style={{ width: `${scale * 100}%`, flex: '0 0 auto' }}>
      <img src={src} alt={alt} onLoad={() => setState('ok')} onError={() => setState('bad')}
        className={`block w-full h-auto rounded-md bg-white ${state === 'bad' ? 'hidden' : ''}`} />
      {state === 'loading' && (
        <span className="absolute inset-0 min-h-40 flex items-center justify-center text-sm text-muted bg-ground/70 rounded-md">กำลังโหลดรูป…</span>
      )}
      {state === 'bad' && (
        <span className="min-h-40 flex items-center justify-center text-sm text-danger-ink bg-danger-bg rounded-md px-3 text-center">
          โหลดรูปไม่ได้ ลองกดโหลดคิวใหม่
        </span>
      )}
    </span>
  )
}

const SCALES = [1, 1.6, 2.4]

/** The slip at a width you can read, scrolled inside its own box, with real zoom. A suspected
 *  repeat shows the picture it repeats beside it, so the decision is made by looking. */
function Slip({ t, scale, onScale, onFull }) {
  const two = (t.note || '').startsWith('รวม 2 รูป')
  const twin = t.duplicate_of || t.seen_trip
  const parts = [[`/api/trips/${t.id}/image`, 'รูปสลิปของเที่ยวนี้']]
  if (two) parts.push([`/api/trips/${t.id}/image?part=2`, 'รูปครึ่งที่สองของเที่ยวนี้'])
  const each = 1 / parts.length
  return (
    <div className="flex flex-col gap-2 w-full">
      <div className="flex items-center gap-1.5 text-sm">
        <span className="text-muted mr-auto">ขนาดรูป</span>
        <button onClick={() => onScale(-1)} disabled={scale === SCALES[0]} aria-label="ย่อรูป"
          className="min-h-9 min-w-9 rounded-lg border border-line bg-white disabled:opacity-40">−</button>
        <span className="w-12 text-center tabular-nums text-ink-soft">{Math.round(scale * 100)}%</span>
        <button onClick={() => onScale(1)} disabled={scale === SCALES.at(-1)} aria-label="ขยายรูป (Z)"
          className="min-h-9 min-w-9 rounded-lg border border-line bg-white disabled:opacity-40">+</button>
        <button onClick={onFull} className="min-h-9 px-3 rounded-lg border border-line bg-white">เต็มจอ</button>
      </div>
      <div className={`grid gap-2 ${twin ? 'sm:grid-cols-2' : ''}`}>
        <div className="min-w-0">
          {twin && <p className="text-xs font-medium text-ink-soft mb-1">แถวนี้</p>}
          {/* key: a fresh element per row, so the last row's slip never sits beside this
              row's numbers while the new one loads */}
          <div key={t.id} className="max-h-[72vh] overflow-auto rounded-lg border border-line bg-white">
            <div className="flex gap-1">
              {parts.map(([src, alt]) => <Pic key={src} src={src} alt={alt} scale={scale * each} />)}
            </div>
          </div>
        </div>
        {twin && (
          <div className="min-w-0">
            <p className="text-xs font-medium text-danger-ink mb-1">
              {t.seen_trip ? 'เที่ยวที่อนุมัติไปแล้ว' : 'อีกแถวที่เลขจองตรงกัน'}
            </p>
            <div key={`t${twin}`} className="max-h-[72vh] overflow-auto rounded-lg border border-danger-bg bg-white">
              <div className="flex">
                <Pic src={`/api/trips/${twin}/image`} alt="รูปที่ซ้ำกัน" scale={scale} />
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

const DAYS_TH = ['จ.', 'อ.', 'พ.', 'พฤ.', 'ศ.', 'ส.', 'อา.']

/** A row with no date: one tap on a day of its week, instead of typing a date. */
function DayPick({ from, onPick }) {
  if (!from) return null
  const days = Array.from({ length: 7 }, (_, i) => {
    const d = new Date(`${from}T00:00:00`)
    d.setDate(d.getDate() + i)
    const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    return [iso, `${DAYS_TH[i]} ${d.getDate()}`]
  })
  return (
    <div className="flex flex-wrap gap-1.5" role="group" aria-label="เลือกวันที่ของเที่ยวนี้">
      {days.map(([iso, label]) => (
        <button key={iso} onClick={() => onPick(iso)}
          className="min-h-10 px-3 rounded-lg border border-danger bg-white hover:bg-danger-bg text-sm">{label}</button>
      ))}
    </div>
  )
}

/** Repeats the system parked by itself. Hides, never deletes: each keeps its restore button. */
function DiscardedLog() {
  const [rows, setRows] = useState(null)
  const [hidden, setHidden] = useState(0)
  const [everything, setEverything] = useState(false)
  const [open, setOpen] = useState(false)
  const [msg, setMsg] = useState('')

  const load = useCallback((all = false) => {
    api.discarded(all)
      .then((r) => { setRows(r.rows); setHidden(r.hidden); setEverything(all) })
      .catch((e) => setMsg(e.message))
  }, [])
  useEffect(() => { load(false) }, [load])

  const restore = async (t) => {
    if (!confirm('เอาเที่ยวนี้กลับเข้าคิวตรวจ?')) return
    try {
      await api.restoreTrip(t.id)
      setRows(rows.filter((r) => r.id !== t.id))
      setMsg('กลับเข้าคิวแล้ว — รีเฟรชหน้านี้เพื่อดู')
    } catch (e) { setMsg(e.message) }
  }
  const clear = async () => {
    if (!confirm(`ซ่อนรายการเก่า ${rows.length} รายการ แล้วเริ่มนับใหม่?\nไม่ได้ลบ — กด "ดูของเก่า" กลับมาดูได้ทุกเมื่อ`)) return
    try {
      const r = await api.clearDiscarded()
      setMsg(`ซ่อนไว้ ${r.hidden} รายการ — จากนี้จะนับเฉพาะของใหม่`)
      load(false)
    } catch (e) { setMsg(e.message) }
  }

  if (!rows || (rows.length === 0 && !hidden)) return null
  return (
    <section className="bg-white rounded-xl border border-line">
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 sm:px-5 py-2">
        <button onClick={() => setOpen(!open)} aria-expanded={open} className="min-h-11 text-left flex items-center gap-2 flex-1 min-w-0">
          <Icon name="chevron" size={16} className={`text-muted transition-transform ${open ? 'rotate-90' : ''}`} />
          <span className="font-medium">งานซ้ำที่ระบบตัดเอง</span>
          <span className="text-sm text-muted">{rows.length === 0 ? 'ยังไม่มีของใหม่' : `${fmt(rows.length)} เที่ยว · ไม่ต้องทำอะไร ดูได้ถ้าอยากตรวจ`}</span>
        </button>
        <div className="flex items-center gap-3 text-sm shrink-0">
          {hidden > 0 && !everything && (
            <button onClick={() => { load(true); setOpen(true) }} className="min-h-11 text-accent hover:underline">ดูของเก่าอีก {fmt(hidden)}</button>
          )}
          {everything && <button onClick={() => load(false)} className="min-h-11 text-accent hover:underline">ดูเฉพาะของใหม่</button>}
          {rows.length > 0 && !everything && (
            <button onClick={clear} className="min-h-11 text-muted hover:text-ink">ซ่อนแล้วเริ่มนับใหม่</button>
          )}
        </div>
      </div>
      {open && (
        <div className="px-4 sm:px-5 pb-4 overflow-x-auto">
          {msg && <p className="text-sm text-ink-soft mb-2">{msg}</p>}
          <table className="w-full text-sm">
            <thead><tr className="text-left text-muted border-b border-line-soft">
              <th className="py-2 pr-3 font-normal">ไรเดอร์</th><th className="py-2 pr-3 font-normal">วันที่</th>
              <th className="py-2 pr-3 font-normal text-right">คุณได้รับ</th><th className="py-2 pr-3 font-normal">ตัดเพราะ</th><th></th>
            </tr></thead>
            <tbody>
              {rows.map((t) => (
                <tr key={t.id} className="border-b border-line-soft">
                  <td className="py-2 pr-3">{t.driver_name}</td>
                  <td className="py-2 pr-3 text-ink-soft">{day(t.trip_date)}</td>
                  <td className="py-2 pr-3 text-right">{baht(t.net_earnings)}</td>
                  <td className="py-2 pr-3 text-ink-soft">{(t.note || '').split(' | ')[0]}</td>
                  <td className="py-2 text-right">
                    <button onClick={() => restore(t)} className="min-h-10 px-1 text-accent hover:underline">กลับเข้าคิว</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

// Reviewing happens in the gaps between other work, on a phone as often as at a desk, so the
// queue has to remember where it was put down. The row id survives a reload; the index does not.
const PLACE = 'reviewQueue.at'
const remember = (id) => { try { sessionStorage.setItem(PLACE, String(id)) } catch { /* private mode */ } }
const recall = () => { try { return Number(sessionStorage.getItem(PLACE)) } catch { return 0 } }

const CHIPS = [
  ['fail', 'ตัวเลขไม่ลงตัว', PILL.warn], ['dup', 'สงสัยว่าซ้ำ', PILL.danger], ['no_data', 'ข้อมูลไม่ครบ', PILL.warn],
  ['nodate', 'ไม่มีวันที่', PILL.wait], ['ready', 'ผ่าน รอกด', PILL.ok],
]
const isPart2 = (t) => (t.note || '').startsWith('รวม 2 รูป')
const passing = (t) => t.check_status === 'pass' && !t.duplicate_of && t.trip_date && !t.seen_in_job

export default function ReviewQueue({ onOpenJob, onCount }) {
  const [rows, setRows] = useState(null)
  const [msg, setMsg] = useState('')
  const [info, setInfo] = useState('')
  const [busy, setBusy] = useState(false)
  const [at, setAt] = useState(0)          // which row of the shown list is open in the pane
  const [zoom, setZoom] = useState(false)  // the full-screen picture
  const [scale, setScale] = useState(SCALES[0])
  const [only, setOnly] = useState('')     // one reason bucket, or '' for every row
  const [week, setWeek] = useState('')     // one week's Monday, or '' for every week
  const [queueOpen, setQueueOpen] = useState(false)   // the list is a panel on small screens
  const listRef = useRef(null)
  const inflight = useRef(new Set())       // rows whose approve or delete is on its way
  const saving = useRef(Promise.resolve()) // the last field save, which an approve waits for

  const load = useCallback(() => {
    api.reviewQueue()
      .then((r) => {
        setRows(r.rows)
        const back = r.rows.findIndex((x) => x.id === recall())
        setAt(back < 0 ? 0 : back)
        // the งานซ้ำ tab opens the queue on its repeats
        let want = ''
        try { want = sessionStorage.getItem('queue.only') || ''; sessionStorage.removeItem('queue.only') } catch { /* private window */ }
        setOnly(want); setWeek('')
      })
      .catch((e) => setMsg(e.message))
  }, [])
  useEffect(() => { load() }, [load])

  const shown = useMemo(() => (rows || []).filter((t) => (!only || kind(t) === only) && (!week || t.wk_from === week)), [rows, only, week])
  const cur = shown.length ? shown[Math.min(at, shown.length - 1)] : null
  // the tab's badge follows the queue as rows are decided, not only when the tab is opened
  useEffect(() => { if (rows) onCount?.(rows.length) }, [rows, onCount])
  // the list shrinks as rows are decided or filtered; the open row stays in range
  useEffect(() => { if (at > Math.max(0, shown.length - 1)) setAt(Math.max(0, shown.length - 1)) }, [shown, at])

  const drop = (ids) => setRows((rs) => rs.filter((r) => !ids.has(r.id)))

  const approve = useCallback(async (t) => {
    if (!t || inflight.current.has(t.id)) return
    inflight.current.add(t.id)
    try {
      await saving.current            // a number typed a moment ago is saved before the approve
      await api.approveTrip(t.id); setMsg(''); drop(new Set([t.id]))
    } catch (e) { setMsg(e.message) } finally { inflight.current.delete(t.id) }
  }, [])

  const remove = useCallback(async (t) => {
    if (!t || inflight.current.has(t.id)) return
    if (!confirm(`ลบเที่ยวนี้ของ ${t.driver_name} ออก?\n\nใช้เมื่อรูปซ้ำ หรือไม่ใช่งาน — แถวจะไม่อยู่ในไฟล์ และรูปจะถูกย้ายไปโฟลเดอร์ "_ทิ้ง-กดลบ" (ไม่ได้ลบรูปทิ้ง)`)) return
    inflight.current.add(t.id)
    try { await api.deleteTrip(t.id); setMsg(''); drop(new Set([t.id])) } catch (e) { setMsg(e.message) } finally { inflight.current.delete(t.id) }
  }, [])

  const skip = useCallback(() => setAt((i) => Math.min(i + 1, Math.max(0, shown.length - 1))), [shown])

  // returns whether it saved, so Ctrl+Enter only approves what was actually stored
  const edit = (t, field, value) => {
    const p = api.patchTrip(t.id, { [field]: value })
      .then((updated) => {
        setRows((rs) => rs.map((r) => (r.id === t.id ? { ...r, ...updated } : r)))
        setMsg('')
        return true
      })
      .catch((e) => { setMsg(e.message); return false })
    saving.current = p
    return p
  }

  const approveAllPassing = async () => {
    const ok = rows.filter(passing)
    if (!ok.length) return setMsg('ไม่มีแถวที่ตัวเลขผ่านให้อนุมัติ')
    if (!confirm(`อนุมัติ ${ok.length} แถวที่ตัวเลขผ่านการตรวจทั้งหมด?\n\nแถวที่ระบบไม่แน่ใจ (ตัวเลขไม่ลงตัว / สงสัยว่าซ้ำ / ไม่มีวันที่) จะยังอยู่ในคิว`)) return
    setBusy(true)
    try {
      const res = await api.approvePassing()
      setInfo(`อนุมัติ ${fmt(res.approved)} แถวแล้ว เหลือรอตรวจ ${fmt(res.skipped)} แถว`)
      load()
    } catch (e) { setMsg(e.message) } finally { setBusy(false) }
  }

  // only the rider's rows whose numbers pass; the rest stay in the queue and the note says so
  const approveRest = async (jobId, name) => {
    const mine = rows.filter((t) => t.job_id === jobId)
    const ok = mine.filter(passing)
    if (!ok.length) return setMsg(`${name} ไม่มีแถวที่ตัวเลขผ่านให้อนุมัติ — ต้องตรวจทีละแถว`)
    const left = mine.length - ok.length
    if (!confirm(`อนุมัติ ${ok.length} แถวของ ${name} ที่ตัวเลขผ่าน?` + (left ? `\n\nอีก ${left} แถวที่ระบบไม่แน่ใจจะยังอยู่ในคิว` : ''))) return
    setBusy(true)
    try {
      const r = await api.approvePassing(jobId)
      drop(new Set(r.ids || []))
      setInfo(`อนุมัติ ${fmt(r.approved)} แถวของ ${name} แล้ว` + (r.skipped ? ` · เหลือรอตรวจ ${fmt(r.skipped)} แถว` : ''))
      setMsg(r.failed?.length ? `อนุมัติไม่ได้ ${r.failed.length} แถว: ${r.failed[0].error}` : '')
    } catch (e) { setMsg(e.message) } finally { setBusy(false) }
  }

  const zoomBy = (d) => setScale((s) => SCALES[Math.min(SCALES.length - 1, Math.max(0, SCALES.indexOf(s) + d))])

  // hands stay on the keyboard: the queue is hundreds of rows on a busy week
  useEffect(() => {
    const onKey = (e) => {
      if (e.target.matches('input, textarea, select')) return
      // a bare letter is the shortcut; Ctrl+A is 'select all' and must never approve a row,
      // which is exactly what it did before this line existed
      if (e.ctrlKey || e.metaKey || e.altKey) return
      if (e.key === 'Escape') { setZoom(false); return }
      if (!shown.length) return
      const k = e.key.toLowerCase()
      // a held key repeats: holding A must not approve the next rows unseen
      if (e.repeat && (k === 'a' || k === 'x')) { e.preventDefault(); return }
      if (k === 'j' || k === 's' || e.key === 'ArrowDown') { e.preventDefault(); setAt((i) => Math.min(i + 1, shown.length - 1)) }
      else if (k === 'k' || e.key === 'ArrowUp') { e.preventDefault(); setAt((i) => Math.max(i - 1, 0)) }
      else if (k === 'a') { e.preventDefault(); approve(cur) }
      else if (k === 'x') { e.preventDefault(); remove(cur) }
      else if (k === 'z') { e.preventDefault(); setScale((s) => SCALES[(SCALES.indexOf(s) + 1) % SCALES.length]) }
      else if (k === 'f') { e.preventDefault(); setZoom((z) => !z) }
      else if (k === 'e') {
        // the first box that still wants something, else the first number: the next keystroke
        const box = document.querySelector('[data-need="block"], [data-need="want"]') || document.querySelector('[data-qfield="2"]')
        if (box) { e.preventDefault(); box.focus(); box.select?.() }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [shown, cur, approve, remove])

  useEffect(() => {
    listRef.current?.querySelector('[data-sel="1"]')?.scrollIntoView({ block: 'nearest' })
    if (cur) remember(cur.id)
  }, [at, cur])

  // the next rows' pictures load while this one is being read, so moving on is instant
  useEffect(() => {
    for (const t of shown.slice(at + 1, at + 4)) {
      new Image().src = `/api/trips/${t.id}/image`
      if (isPart2(t)) new Image().src = `/api/trips/${t.id}/image?part=2`
    }
  }, [shown, at])

  const counts = useMemo(() => {
    const c = { fail: 0, no_data: 0, dup: 0, nodate: 0, ready: 0 }
    for (const t of rows || []) if (!week || t.wk_from === week) c[kind(t)]++
    return c
  }, [rows, week])
  const weeks = useMemo(() => {
    const w = {}
    for (const t of rows || []) if (t.wk_from) w[t.wk_from] = (w[t.wk_from] || 0) + 1
    return Object.entries(w).sort()
  }, [rows])

  if (!rows) return <p className="text-sm text-muted">กำลังโหลด…</p>

  const groups = []
  for (const [i, t] of shown.entries()) {
    let g = groups.at(-1)
    if (!g || g.job_id !== t.job_id) {
      g = { job_id: t.job_id, driver_name: t.driver_name, rows: [] }
      groups.push(g)
    }
    g.rows.push({ ...t, _i: i })
  }
  const chips = CHIPS.filter(([k]) => counts[k] > 0)
  const ready = rows.filter(passing).length

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl sm:text-[28px] font-semibold tracking-tight">รอตรวจ {fmt(rows.length)} แถว</h1>
          {weeks.length > 1 && (
            <div role="group" aria-label="กรองตามสัปดาห์" className="flex flex-wrap gap-1.5 mt-1.5">
              {[['', rows.length], ...weeks].map(([w, nn]) => (
                <button key={w || 'all'} onClick={() => { setWeek(w); setAt(0) }} aria-pressed={week === w}
                  className={`min-h-8 text-sm rounded-full px-3 border ${week === w ? 'bg-ink text-white border-ink' : 'bg-white text-ink-soft border-line'}`}>
                  {w ? `สัปดาห์ ${day(w)}` : 'ทุกสัปดาห์'} {fmt(nn)}
                </button>
              ))}
            </div>
          )}
          {chips.length > 0 && (
            // a chip is a filter: clear one kind of row in a run, the same motion each time
            <div role="group" aria-label="กรองตามเหตุผล" className="flex flex-wrap gap-1.5 mt-1.5">
              {chips.map(([k, label, cls]) => (
                <button key={k} onClick={() => { setOnly(only === k ? '' : k); setAt(0) }} aria-pressed={only === k}
                  className={`min-h-8 text-sm rounded-full px-2.5 ${cls} ${only === k ? 'ring-2 ring-ink' : only ? 'opacity-50' : ''}`}>
                  {label} {fmt(counts[k])}
                </button>
              ))}
              {only && <button onClick={() => setOnly('')} className="min-h-8 text-sm text-accent hover:underline px-1">ดูทุกเหตุผล</button>}
            </div>
          )}
        </div>
        <div className="flex items-center gap-2 w-full sm:w-auto">
          <button onClick={approveAllPassing} disabled={busy || !ready}
            className="flex-1 sm:flex-none min-h-11 rounded-lg border border-line bg-white hover:bg-ground px-4 text-sm font-medium disabled:opacity-40">
            {busy ? 'กำลังอนุมัติ…' : `อนุมัติทุกแถวที่ตัวเลขผ่าน (${fmt(ready)})`}
          </button>
          <button onClick={load} aria-label="โหลดคิวใหม่"
            className="min-h-11 min-w-11 shrink-0 rounded-lg border border-line bg-white hover:bg-ground flex items-center justify-center text-ink-soft">
            <Icon name="refresh" size={18} />
          </button>
        </div>
      </div>
      {msg && <p role="alert" className="text-sm text-danger-ink bg-danger-bg rounded-lg px-3 py-2">{msg}</p>}
      {info && !msg && <p role="status" className="text-sm text-ok-ink bg-ok-bg rounded-lg px-3 py-2">{info}</p>}

      {rows.length === 0 ? (
        <div className="bg-white rounded-xl border border-line p-10 text-center">
          <p className="font-medium">ไม่มีอะไรรอตรวจ</p>
          <p className="text-sm text-muted mt-1">แถวใหม่ที่ระบบไม่แน่ใจจะมาอยู่ที่นี่หลังรอบอ่านรูปถัดไป</p>
        </div>
      ) : !cur ? (
        <div className="bg-white rounded-xl border border-line p-10 text-center">
          <p className="font-medium">ไม่มีแถวตามตัวกรองนี้แล้ว</p>
          <button onClick={() => { setOnly(''); setWeek('') }} className="mt-2 min-h-10 text-sm text-accent hover:underline">ดูทุกแถว</button>
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[19rem_minmax(0,1fr)] items-start">
          {/* the queue — reason first, because that is what decides the next move.
              On a phone it is navigation, not the work: it folds away so the row under review
              owns the screen, and reopens on demand. */}
          <div className="min-w-0">
            <button onClick={() => setQueueOpen((o) => !o)} aria-expanded={queueOpen}
              className="lg:hidden w-full min-h-11 flex items-center justify-between gap-2 rounded-xl border border-line bg-white px-4 text-sm">
              <span className="text-ink-soft">แถวที่ {Math.min(at, shown.length - 1) + 1} จาก {shown.length} · เลือกแถวอื่น</span>
              <Icon name="chevron" size={16} className={`text-muted transition-transform ${queueOpen ? '-rotate-90' : 'rotate-90'}`} />
            </button>
            <div ref={listRef}
              className={`${queueOpen ? 'block' : 'hidden'} lg:block mt-2 lg:mt-0 bg-white rounded-xl border border-line overflow-y-auto max-h-[60vh] lg:max-h-[78vh]`}>
              {groups.map((g) => (
                <div key={`${g.job_id}-${g.rows[0].id}`}>
                  <div className="sticky top-0 bg-ground border-y border-line px-3 py-1.5 z-10 flex items-center justify-between gap-2">
                    <p className="text-sm font-medium truncate">{g.driver_name} <span className="font-normal text-muted">· {g.rows.length}</span></p>
                    <button onClick={() => onOpenJob(g.job_id)} className="shrink-0 min-h-8 text-sm text-accent hover:underline">ดูทั้งหมด</button>
                  </div>
                  {g.rows.map((t) => {
                    const w = why(t)
                    const sel = t.id === cur.id
                    return (
                      <button key={t.id} data-sel={sel ? '1' : '0'} aria-current={sel ? 'true' : undefined}
                        onClick={() => { setAt(t._i); setQueueOpen(false) }}
                        className={`w-full text-left px-3 py-2.5 border-b border-line-soft border-l-[3px] flex items-center gap-2.5
                          ${sel ? 'bg-accent-bg border-l-accent' : 'border-l-transparent hover:bg-ground'}`}>
                        <span className="min-w-0 flex-1">
                          <span className={`text-xs font-medium rounded-full px-2 py-0.5 ${PILL[w.tone]}`}>{w.chip}</span>
                          <span className="block text-sm text-muted mt-0.5">{day(t.trip_date)}{t.trip_time ? ` · ${t.trip_time}` : ''}</span>
                        </span>
                        <span className="text-sm text-ink-soft shrink-0 tabular-nums">{baht(t.net_earnings)}</span>
                      </button>
                    )
                  })}
                </div>
              ))}
            </div>
          </div>

          {/* the one being reviewed */}
          {(() => {
            const w = why(cur)
            const m = money(cur)
            const need = needed(cur)
            const asks = Object.keys(need).length
            const warn = fareWarning(cur)
            const n0 = shown.indexOf(cur)
            return (
              <section aria-labelledby="row-h" className="bg-white rounded-xl border border-line overflow-hidden">
                <div className="grid xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
                  <div className="bg-ground p-3 sm:p-4">
                    <Slip t={cur} scale={scale} onScale={zoomBy} onFull={() => setZoom(true)} />
                  </div>

                  <div className="p-4 sm:p-5 flex flex-col gap-3.5">
                    <div>
                      <p className="text-sm text-muted">แถว {n0 + 1} จาก {shown.length}{shown.length !== rows.length ? ` (ทั้งหมด ${rows.length})` : ''}</p>
                      <h2 id="row-h" className="text-xl font-semibold">{cur.driver_name}{cur.service_type ? ` · ${cur.service_type}` : ''}</h2>
                      <p className="text-sm text-ink-soft">
                        {day(cur.trip_date)}{cur.trip_time ? ` · ${cur.trip_time}` : ''} · {cur.booking_code ? `Booking ${cur.booking_code}` : 'ไม่มีเลขจอง'}
                      </p>
                    </div>

                    <div role="note" className={`rounded-xl px-3.5 py-3 flex gap-2.5 ${PILL[w.tone]}`}>
                      <Icon name={w.tone === 'ok' ? 'check' : 'alert'} size={20} className="shrink-0 mt-0.5" />
                      <div>
                        <p className="text-sm font-semibold">{w.head}</p>
                        <p className="text-sm">{w.body}</p>
                      </div>
                    </div>
                    {warn && <p className="text-sm rounded-xl bg-warn-bg text-warn-ink px-3.5 py-2.5">{warn}</p>}
                    {asks > 0 && (
                      <p className={`text-sm rounded-lg px-3 py-2 ${need.trip_date ? 'bg-danger-bg text-danger-ink' : 'bg-warn-bg text-warn-ink'}`}>
                        ต้องกรอก {asks} ช่องที่ไฮไลต์ไว้<span className="hidden lg:inline"> — กด E ไปช่องแรกได้เลย</span>
                      </p>
                    )}

                    <div className="grid grid-cols-2 gap-3">
                      <div className="col-span-2 flex flex-col gap-2">
                        {need.trip_date && <DayPick from={cur.wk_from} onPick={(iso) => edit(cur, 'trip_date', iso)} />}
                        <Field label="วันที่" type="date" value={cur.trip_date} need={need.trip_date} order="1"
                          onSave={(v) => edit(cur, 'trip_date', v)} onApprove={() => approve(cur)} />
                      </div>
                      <Field label="คุณได้รับ (Net)" value={cur.net_earnings} need={need.net_earnings} order="2"
                        onSave={(v) => edit(cur, 'net_earnings', v)} onApprove={() => approve(cur)} />
                      <Field label="ค่ารอบ (Base fare)" value={cur.base_fare} need={need.base_fare} order="3"
                        onSave={(v) => edit(cur, 'base_fare', v)} onApprove={() => approve(cur)} />
                      <Field label="โบนัส" value={cur.bonus} order="4"
                        onSave={(v) => edit(cur, 'bonus', v)} onApprove={() => approve(cur)} />
                      <Field label="เทอร์โบ" value={cur.turbo} order="5"
                        onSave={(v) => edit(cur, 'turbo', v)} onApprove={() => approve(cur)} />
                    </div>
                    {m.known && (
                      <p className={`text-sm rounded-lg px-3 py-2 ${m.ok ? 'bg-ok-bg text-ok-ink' : 'bg-warn-bg text-warn-ink'}`}>
                        {m.ok
                          ? `ลงตัว — ${baht(m.base)} + ${baht(m.bonus)} + ${baht(m.turbo)} = ${baht(m.net)}`
                          : `ยังต่างอยู่ ${baht(Math.abs(m.diff))} (รวมได้ ${baht(m.sum)} แต่คุณได้รับ ${baht(m.net)})`}
                      </p>
                    )}
                    <Field label="Passenger Fare" value={cur.passenger_total} order="6"
                      onSave={(v) => edit(cur, 'passenger_total', v)} onApprove={() => approve(cur)}
                      hint="ยอดที่ Grab คิดค่าบริการ ไม่ใช่ยอดรวมที่ผู้โดยสารจ่าย" />

                    {/* on a phone these live in the bar above the tab bar instead, inside thumb reach */}
                    <div className="hidden lg:flex items-center gap-2.5 pt-3 border-t border-line-soft">
                      <button onClick={() => approve(cur)} disabled={!cur.trip_date} title={cur.trip_date ? 'อนุมัติ (A)' : 'ต้องใส่วันที่ก่อน'}
                        className="min-h-11 px-6 rounded-lg bg-accent hover:bg-accent-hover text-white text-[15px] font-semibold disabled:opacity-40">
                        อนุมัติ
                      </button>
                      <button onClick={skip} disabled={n0 >= shown.length - 1} title="ข้ามไปแถวถัดไป (S)"
                        className="min-h-11 px-4 rounded-lg border border-line bg-white hover:bg-ground text-[15px] disabled:opacity-40">
                        ข้ามไปก่อน
                      </button>
                      <button onClick={() => remove(cur)} title="ลบ (X)"
                        className="ml-auto min-h-11 px-4 rounded-lg border border-danger-bg bg-white hover:bg-danger-bg text-danger-ink text-[15px]">
                        ไม่ใช่งาน / ลบ
                      </button>
                    </div>
                    <p className="hidden lg:block text-xs text-muted">
                      ปุ่มลัด: A อนุมัติ · S ข้าม · X ลบ · J/K แถวก่อน/ถัดไป · Z ขยายรูป · F เต็มจอ · E ไปช่องตัวเลข
                      · ในช่อง: Enter บันทึกแล้วไปช่องถัดไป · Ctrl+Enter บันทึกและอนุมัติ
                    </p>
                    <button onClick={() => approveRest(cur.job_id, cur.driver_name)} disabled={busy}
                      className="self-start min-h-10 text-sm text-accent hover:underline">
                      อนุมัติแถวที่ตัวเลขผ่านของ {cur.driver_name}
                    </button>

                    <details className="text-sm">
                      <summary className="cursor-pointer text-ink-soft min-h-9 flex items-center">ข้อมูลอื่นของเที่ยวนี้</summary>
                      <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-ink-soft">
                        <dt className="text-muted">การจ่ายเงิน</dt><dd>{cur.payment_method || '—'}</dd>
                        <dt className="text-muted">ระยะทาง</dt><dd>{cur.distance_km != null ? `${fmt(cur.distance_km)} กม.` : '—'}</dd>
                        {cur.pickup_text && <><dt className="text-muted">รับ → ส่ง</dt><dd className="break-words">{cur.pickup_text} → {cur.dropoff_text}</dd></>}
                        {cur.note && <><dt className="text-muted">หมายเหตุ</dt><dd className="break-words">{cur.note}</dd></>}
                      </dl>
                    </details>
                  </div>
                </div>
              </section>
            )
          })()}
        </div>
      )}

      <DiscardedLog />

      {/* Touch has no keyboard. The three decisions sit in a bar just above the tab bar,
          inside thumb reach, with the counter between previous and next. */}
      {cur && (
        <>
          <div className="h-28 lg:hidden" aria-hidden="true" />
          <div className="lg:hidden fixed inset-x-0 z-30 border-t border-line bg-white px-3 pt-2 pb-2 flex flex-col gap-2"
            style={{ bottom: 'calc(3.5rem + env(safe-area-inset-bottom))' }}>
            <div className="flex items-center gap-2 text-sm">
              <button onClick={() => setAt((i) => Math.max(i - 1, 0))} disabled={shown.indexOf(cur) === 0} aria-label="แถวก่อนหน้า"
                className="min-h-10 min-w-10 rounded-lg border border-line flex items-center justify-center disabled:opacity-40">
                <Icon name="back" size={18} />
              </button>
              <span className="flex-1 text-center text-ink-soft">แถว {shown.indexOf(cur) + 1} จาก {shown.length}</span>
              <button onClick={() => setAt((i) => Math.min(i + 1, shown.length - 1))} disabled={shown.indexOf(cur) >= shown.length - 1} aria-label="แถวถัดไป"
                className="min-h-10 min-w-10 rounded-lg border border-line flex items-center justify-center disabled:opacity-40">
                <Icon name="chevron" size={18} />
              </button>
            </div>
            <div className="grid grid-cols-[1fr_1fr_2fr] gap-2">
              <button onClick={() => remove(cur)} className="min-h-12 rounded-xl border border-danger-bg text-danger-ink text-[15px]">ลบ</button>
              <button onClick={skip} disabled={shown.indexOf(cur) >= shown.length - 1} className="min-h-12 rounded-xl border border-line text-[15px] disabled:opacity-40">ข้าม</button>
              <button onClick={() => approve(cur)} disabled={!cur.trip_date}
                className="min-h-12 rounded-xl bg-accent text-white text-base font-semibold disabled:opacity-40">
                {cur.trip_date ? 'อนุมัติ' : 'ใส่วันที่ก่อน'}
              </button>
            </div>
          </div>
        </>
      )}

      {zoom && cur && (
        <div className="fixed inset-0 bg-ink/80 flex items-center justify-center z-50 p-2 sm:p-6" onClick={() => setZoom(false)}>
          {/* zooming is what a small screen needs MOST, so here the picture takes the whole of it */}
          <div role="dialog" aria-modal="true" aria-label="รูปขยาย" className="bg-white rounded-xl p-2 sm:p-3 w-full sm:w-auto max-h-full overflow-auto"
            onClick={(e) => e.stopPropagation()}>
            <div className="flex justify-between items-center mb-2 px-1 gap-3">
              <span className="text-sm text-ink-soft truncate">
                {cur.driver_name} · {day(cur.trip_date)}{cur.booking_code ? ` · ${cur.booking_code}` : ''}
              </span>
              <button onClick={() => setZoom(false)} aria-label="ปิดรูปขยาย" autoFocus
                className="min-h-11 min-w-11 shrink-0 rounded-lg hover:bg-ground flex items-center justify-center text-ink-soft text-xl">✕</button>
            </div>
            <div className="flex flex-col sm:flex-row gap-3">
              <img src={`/api/trips/${cur.id}/image`} alt="รูปสลิปขยาย"
                className="w-full sm:w-auto sm:max-w-[44vw] max-h-[70vh] sm:max-h-[82vh] object-contain rounded-lg" />
              {isPart2(cur) && (
                <img src={`/api/trips/${cur.id}/image?part=2`} alt="รูปครึ่งที่สองขยาย"
                  className="w-full sm:w-auto sm:max-w-[44vw] max-h-[70vh] sm:max-h-[82vh] object-contain rounded-lg"
                  onError={(e) => { e.currentTarget.style.display = 'none' }} />
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
