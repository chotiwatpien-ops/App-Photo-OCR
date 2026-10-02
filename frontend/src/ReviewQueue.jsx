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
  return { known: true, net, base, bonus, turbo, sum, diff: Math.round((net - sum) * 100) / 100 }
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
    if (m.known && m.diff === 0) {
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

/** One number the reviewer can correct without leaving the queue. */
function Field({ label, value, onSave, type = 'number', hint, need }) {
  // Enter saves without waiting for the field to lose focus — a reviewer correcting a column
  // of numbers types, presses Enter, and expects the sum below to settle
  const [v, setV] = useState(value ?? '')
  const [saving, setSaving] = useState(false)
  const box = useRef(null)
  useEffect(() => { setV(value ?? '') }, [value])
  const dirty = String(v) !== String(value ?? '')
  const commit = async () => {
    if (!dirty) return
    setSaving(true)
    try { await onSave(v === '' ? null : (type === 'number' ? Number(v) : v)) } finally { setSaving(false) }
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
        inputMode={type === 'number' ? 'decimal' : undefined}
        onChange={(e) => setV(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); commit(); box.current?.blur() } }}
        className={`min-h-11 w-full rounded-lg border px-3 text-[15px] outline-none disabled:opacity-50
          ${dirty ? 'border-accent bg-accent-bg' : asking ? NEED_BOX[need] : 'border-line bg-white focus:border-accent'}`} />
      {hint && <span className="text-xs text-muted">{hint}</span>}
    </label>
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

export default function ReviewQueue({ onOpenJob, onCount }) {
  const [rows, setRows] = useState(null)
  const [msg, setMsg] = useState('')
  const [info, setInfo] = useState('')
  const [busy, setBusy] = useState(false)
  const [at, setAt] = useState(0)          // which row is open in the pane
  const [zoom, setZoom] = useState(false)
  const [queueOpen, setQueueOpen] = useState(false)   // the list is a panel on small screens
  const listRef = useRef(null)

  const load = useCallback(() => {
    api.reviewQueue()
      .then((r) => {
        setRows(r.rows)
        const back = r.rows.findIndex((x) => x.id === recall())
        setAt(back < 0 ? 0 : back)
      })
      .catch((e) => setMsg(e.message))
  }, [])
  useEffect(() => { load() }, [load])

  const cur = rows && rows[Math.min(at, rows.length - 1)]
  // the tab's badge follows the queue as rows are decided, not only when the tab is opened
  useEffect(() => { if (rows) onCount?.(rows.length) }, [rows, onCount])

  // drop a row from the queue and stay on the same spot, which is now the next row
  const drop = (id) => setRows((rs) => {
    const left = rs.filter((r) => r.id !== id)
    setAt((i) => Math.min(i, Math.max(0, left.length - 1)))
    return left
  })

  const approve = useCallback(async (t) => {
    if (!t) return
    try { await api.approveTrip(t.id); setMsg(''); drop(t.id) } catch (e) { setMsg(e.message) }
  }, [])

  const remove = useCallback(async (t) => {
    if (!t || !confirm(`ลบเที่ยวนี้ของ ${t.driver_name} ออก?\n\nใช้เมื่อรูปซ้ำ หรือไม่ใช่งาน — แถวจะไม่อยู่ในไฟล์ และรูปจะถูกย้ายไปโฟลเดอร์ "_ทิ้ง-กดลบ" (ไม่ได้ลบรูปทิ้ง)`)) return
    try { await api.deleteTrip(t.id); setMsg(''); drop(t.id) } catch (e) { setMsg(e.message) }
  }, [])

  const skip = useCallback(() => setAt((i) => Math.min(i + 1, (rows?.length || 1) - 1)), [rows])

  const edit = async (t, field, value) => {
    try {
      const updated = await api.patchTrip(t.id, { [field]: value })
      setRows((rs) => rs.map((r) => (r.id === t.id ? { ...r, ...updated } : r)))
      setMsg('')
    } catch (e) { setMsg(e.message) }
  }

  const approveAllPassing = async () => {
    const ok = rows.filter((t) => t.check_status === 'pass' && !t.duplicate_of && t.trip_date && !t.seen_in_job)
    if (!ok.length) return setMsg('ไม่มีแถวที่ตัวเลขผ่านให้อนุมัติ')
    if (!confirm(`อนุมัติ ${ok.length} แถวที่ตัวเลขผ่านการตรวจทั้งหมด?\n\nแถวที่ระบบไม่แน่ใจ (ตัวเลขไม่ลงตัว / สงสัยว่าซ้ำ / ไม่มีวันที่) จะยังอยู่ในคิว`)) return
    setBusy(true)
    try {
      const res = await api.approvePassing()
      setInfo(`อนุมัติ ${fmt(res.approved)} แถวแล้ว เหลือรอตรวจ ${fmt(res.skipped)} แถว`)
      load()
    } catch (e) { setMsg(e.message) } finally { setBusy(false) }
  }

  const approveRest = async (jobId, name, force = false) => {
    try {
      const r = await api.commit(jobId, force)
      setInfo(`อนุมัติ ${fmt(r.written)} แถวของ ${name} แล้ว`)
      setRows((rs) => rs.filter((x) => x.job_id !== jobId))
    } catch (e) {
      if (!force && e.message.includes('บันทึกซ้ำ') && confirm(`${e.message}\n\nยืนยันอนุมัติทั้งหมดหรือไม่?`)) {
        return approveRest(jobId, name, true)
      }
      setMsg(e.message)
    }
  }

  // hands stay on the keyboard: the queue is hundreds of rows on a busy week
  useEffect(() => {
    const onKey = (e) => {
      if (e.target.matches('input, textarea, select')) return
      // a bare letter is the shortcut; Ctrl+A is 'select all' and must never approve a row,
      // which is exactly what it did before this line existed
      if (e.ctrlKey || e.metaKey || e.altKey) return
      if (e.key === 'Escape') return setZoom(false)
      if (!rows || !rows.length) return
      const k = e.key.toLowerCase()
      if (k === 'j' || k === 's' || e.key === 'ArrowDown') { e.preventDefault(); setAt((i) => Math.min(i + 1, rows.length - 1)) }
      else if (k === 'k' || e.key === 'ArrowUp') { e.preventDefault(); setAt((i) => Math.max(i - 1, 0)) }
      else if (k === 'a') { e.preventDefault(); approve(rows[at]) }
      else if (k === 'x') { e.preventDefault(); remove(rows[at]) }
      else if (k === 'z') { e.preventDefault(); setZoom((z) => !z) }
      else if (k === 'e') {
        // straight to the first box that still wants something — the reviewer's next keystroke
        const box = document.querySelector('[data-need="block"], [data-need="want"]')
        if (box) { e.preventDefault(); box.focus(); box.select?.() }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [rows, at, approve, remove])

  useEffect(() => {
    listRef.current?.querySelector('[data-sel="1"]')?.scrollIntoView({ block: 'nearest' })
    if (cur) remember(cur.id)
  }, [at, cur])

  const counts = useMemo(() => {
    const c = { fail: 0, no_data: 0, dup: 0, nodate: 0, ready: 0 }
    for (const t of rows || []) {
      if (t.duplicate_of || t.seen_in_job) c.dup++
      else if (t.check_status === 'fail') c.fail++
      else if (t.check_status === 'no_data') c.no_data++
      else if (!t.trip_date) c.nodate++
      else c.ready++
    }
    return c
  }, [rows])

  if (!rows) return <p className="text-sm text-muted">กำลังโหลด…</p>

  const groups = []
  for (const [i, t] of rows.entries()) {
    let g = groups.at(-1)
    if (!g || g.job_id !== t.job_id) {
      g = { job_id: t.job_id, driver_name: t.driver_name, rows: [] }
      groups.push(g)
    }
    g.rows.push({ ...t, _i: i })
  }
  const chips = [
    ['fail', 'ตัวเลขไม่ลงตัว', PILL.warn], ['dup', 'สงสัยว่าซ้ำ', PILL.danger], ['no_data', 'ข้อมูลไม่ครบ', PILL.warn],
    ['nodate', 'ไม่มีวันที่', PILL.wait], ['ready', 'ผ่าน รอกด', PILL.ok],
  ].filter(([k]) => counts[k] > 0)

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl sm:text-[28px] font-semibold tracking-tight">รอตรวจ {fmt(rows.length)} แถว</h1>
          {chips.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-1.5">
              {chips.map(([k, label, cls]) => (
                <span key={k} className={`text-sm rounded-full px-2.5 py-0.5 ${cls}`}>{label} {fmt(counts[k])}</span>
              ))}
            </div>
          )}
        </div>
        <div className="flex items-center gap-2 w-full sm:w-auto">
          <button onClick={approveAllPassing} disabled={busy || !counts.ready}
            className="flex-1 sm:flex-none min-h-11 rounded-lg border border-line bg-white hover:bg-ground px-4 text-sm font-medium disabled:opacity-40">
            {busy ? 'กำลังอนุมัติ…' : `อนุมัติทุกแถวที่ตัวเลขผ่าน (${fmt(counts.ready)})`}
          </button>
          <button onClick={load} aria-label="โหลดคิวใหม่"
            className="min-h-11 min-w-11 shrink-0 rounded-lg border border-line bg-white hover:bg-ground flex items-center justify-center text-ink-soft">
            <Icon name="refresh" size={18} />
          </button>
        </div>
      </div>
      {msg && <p role="alert" className="text-sm text-danger-ink bg-danger-bg rounded-lg px-3 py-2">{msg}</p>}
      {info && !msg && <p className="text-sm text-ok-ink bg-ok-bg rounded-lg px-3 py-2">{info}</p>}

      {rows.length === 0 ? (
        <div className="bg-white rounded-xl border border-line p-10 text-center">
          <p className="font-medium">ไม่มีอะไรรอตรวจ</p>
          <p className="text-sm text-muted mt-1">แถวใหม่ที่ระบบไม่แน่ใจจะมาอยู่ที่นี่หลังรอบอ่านรูปถัดไป</p>
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[19rem_minmax(0,1fr)] items-start">
          {/* the queue — reason first, because that is what decides the next move.
              On a phone it is navigation, not the work: it folds away so the row under review
              owns the screen, and reopens on demand. */}
          <div className="min-w-0">
            <button onClick={() => setQueueOpen((o) => !o)} aria-expanded={queueOpen}
              className="lg:hidden w-full min-h-11 flex items-center justify-between gap-2 rounded-xl border border-line bg-white px-4 text-sm">
              <span className="text-ink-soft">แถวที่ {at + 1} จาก {rows.length} · เลือกแถวอื่น</span>
              <Icon name="chevron" size={16} className={`text-muted transition-transform ${queueOpen ? '-rotate-90' : 'rotate-90'}`} />
            </button>
            <div ref={listRef}
              className={`${queueOpen ? 'block' : 'hidden'} lg:block mt-2 lg:mt-0 bg-white rounded-xl border border-line overflow-y-auto max-h-[60vh] lg:max-h-[78vh]`}>
              {groups.map((g) => (
                <div key={g.job_id}>
                  <div className="sticky top-0 bg-ground border-y border-line px-3 py-1.5 z-10 flex items-center justify-between gap-2">
                    <p className="text-sm font-medium truncate">{g.driver_name} <span className="font-normal text-muted">· {g.rows.length}</span></p>
                    <button onClick={() => onOpenJob(g.job_id)} className="shrink-0 min-h-8 text-sm text-accent hover:underline">ดูทั้งหมด</button>
                  </div>
                  {g.rows.map((t) => {
                    const w = why(t)
                    const sel = t._i === at
                    return (
                      <button key={t.id} data-sel={sel ? '1' : '0'} aria-current={sel ? 'true' : undefined}
                        onClick={() => { setAt(t._i); setQueueOpen(false) }}
                        className={`w-full text-left px-3 py-2.5 border-b border-line-soft border-l-[3px] flex items-center gap-2.5
                          ${sel ? 'bg-accent-bg border-l-accent' : 'border-l-transparent hover:bg-ground'}`}>
                        <img src={`/api/trips/${t.id}/image`} alt="" loading="lazy"
                          className="h-11 w-11 shrink-0 object-cover object-top rounded-md border border-line bg-ground"
                          onError={(e) => { e.currentTarget.style.visibility = 'hidden' }} />
                        <span className="min-w-0 flex-1">
                          <span className={`text-xs font-medium rounded-full px-2 py-0.5 ${PILL[w.tone]}`}>{w.chip}</span>
                          <span className="block text-sm text-muted mt-0.5">{day(t.trip_date)}{t.trip_time ? ` · ${t.trip_time}` : ''}</span>
                        </span>
                        <span className="text-sm text-ink-soft shrink-0">{baht(t.net_earnings)}</span>
                      </button>
                    )
                  })}
                </div>
              ))}
            </div>
          </div>

          {/* the one being reviewed */}
          {cur && (() => {
            const w = why(cur)
            const m = money(cur)
            const need = needed(cur)
            const asks = Object.keys(need).length
            const warn = fareWarning(cur)
            const two = (cur.note || '').startsWith('รวม 2 รูป')
            return (
              <section aria-labelledby="row-h" className="bg-white rounded-xl border border-line overflow-hidden">
                <div className="grid md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                  {/* the picture, at a size you can actually read */}
                  <div className="bg-ground p-3 sm:p-5 flex flex-col items-center gap-3">
                    <button onClick={() => setZoom(true)} className="relative w-full" title="กดเพื่อขยาย (Z)">
                      {/* two halves side by side is unreadable under ~640px: stack them there */}
                      <span className="flex flex-col sm:flex-row gap-2 justify-center">
                        <img src={`/api/trips/${cur.id}/image`} alt="รูปสลิปของเที่ยวนี้"
                          className="mx-auto max-h-[46vh] sm:max-h-[60vh] w-auto object-contain rounded-lg border border-line bg-white"
                          onError={(e) => { e.currentTarget.style.visibility = 'hidden' }} />
                        {two && (
                          <img src={`/api/trips/${cur.id}/image?part=2`} alt="รูปครึ่งที่สองของเที่ยวนี้"
                            className="mx-auto max-h-[46vh] sm:max-h-[60vh] w-auto object-contain rounded-lg border border-line bg-white"
                            onError={(e) => { e.currentTarget.style.display = 'none' }} />
                        )}
                      </span>
                      <span className="absolute bottom-2 right-2 rounded-md bg-ink/75 px-2 py-1 text-xs text-white">แตะเพื่อขยาย</span>
                    </button>
                  </div>

                  <div className="p-4 sm:p-5 flex flex-col gap-3.5">
                    <div>
                      <p className="text-sm text-muted">แถว {at + 1} จาก {rows.length}</p>
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
                      <div className="col-span-2">
                        <Field label="วันที่" type="date" value={cur.trip_date} need={need.trip_date}
                          onSave={(v) => edit(cur, 'trip_date', v)} />
                      </div>
                      <Field label="คุณได้รับ (Net)" value={cur.net_earnings} need={need.net_earnings}
                        onSave={(v) => edit(cur, 'net_earnings', v)} />
                      <Field label="ค่ารอบ (Base fare)" value={cur.base_fare} need={need.base_fare}
                        onSave={(v) => edit(cur, 'base_fare', v)} />
                      <Field label="โบนัส" value={cur.bonus} onSave={(v) => edit(cur, 'bonus', v)} />
                      <Field label="เทอร์โบ" value={cur.turbo} onSave={(v) => edit(cur, 'turbo', v)} />
                    </div>
                    {m.known && (
                      <p className={`text-sm rounded-lg px-3 py-2 ${m.diff === 0 ? 'bg-ok-bg text-ok-ink' : 'bg-warn-bg text-warn-ink'}`}>
                        {m.diff === 0
                          ? `ลงตัว — ${baht(m.base)} + ${baht(m.bonus)} + ${baht(m.turbo)} = ${baht(m.net)}`
                          : `ยังต่างอยู่ ${baht(Math.abs(m.diff))} (รวมได้ ${baht(m.sum)} แต่คุณได้รับ ${baht(m.net)})`}
                      </p>
                    )}
                    <Field label="Passenger Fare" value={cur.passenger_total}
                      onSave={(v) => edit(cur, 'passenger_total', v)}
                      hint="ยอดที่ Grab คิดค่าบริการ ไม่ใช่ยอดรวมที่ผู้โดยสารจ่าย" />

                    {/* on a phone these live in the bar above the tab bar instead, inside thumb reach */}
                    <div className="hidden lg:flex items-center gap-2.5 pt-3 border-t border-line-soft">
                      <button onClick={() => approve(cur)} disabled={!cur.trip_date} title={cur.trip_date ? 'อนุมัติ (A)' : 'ต้องใส่วันที่ก่อน'}
                        className="min-h-11 px-6 rounded-lg bg-accent hover:bg-accent-hover text-white text-[15px] font-semibold disabled:opacity-40">
                        อนุมัติ
                      </button>
                      <button onClick={skip} disabled={at >= rows.length - 1} title="ข้ามไปแถวถัดไป (S)"
                        className="min-h-11 px-4 rounded-lg border border-line bg-white hover:bg-ground text-[15px] disabled:opacity-40">
                        ข้ามไปก่อน
                      </button>
                      <button onClick={() => remove(cur)} title="ลบ (X)"
                        className="ml-auto min-h-11 px-4 rounded-lg border border-danger-bg bg-white hover:bg-danger-bg text-danger-ink text-[15px]">
                        ไม่ใช่งาน / ลบ
                      </button>
                    </div>
                    <p className="hidden lg:block text-xs text-muted">ปุ่มลัด: A อนุมัติ · S ข้าม · X ลบ · J/K แถวก่อน/ถัดไป · Z ขยายรูป · E ช่องที่ต้องกรอก</p>
                    <button onClick={() => confirm(`อนุมัติทุกแถวที่เหลือของ ${cur.driver_name}?`) && approveRest(cur.job_id, cur.driver_name)}
                      className="self-start min-h-10 text-sm text-accent hover:underline">
                      อนุมัติที่เหลือทั้งหมดของ {cur.driver_name}
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
              <button onClick={() => setAt((i) => Math.max(i - 1, 0))} disabled={at === 0} aria-label="แถวก่อนหน้า"
                className="min-h-10 min-w-10 rounded-lg border border-line flex items-center justify-center disabled:opacity-40">
                <Icon name="back" size={18} />
              </button>
              <span className="flex-1 text-center text-ink-soft">แถว {at + 1} จาก {rows.length}</span>
              <button onClick={() => setAt((i) => Math.min(i + 1, rows.length - 1))} disabled={at >= rows.length - 1} aria-label="แถวถัดไป"
                className="min-h-10 min-w-10 rounded-lg border border-line flex items-center justify-center disabled:opacity-40">
                <Icon name="chevron" size={18} />
              </button>
            </div>
            <div className="grid grid-cols-[1fr_1fr_2fr] gap-2">
              <button onClick={() => remove(cur)} className="min-h-12 rounded-xl border border-danger-bg text-danger-ink text-[15px]">ลบ</button>
              <button onClick={skip} disabled={at >= rows.length - 1} className="min-h-12 rounded-xl border border-line text-[15px] disabled:opacity-40">ข้าม</button>
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
          <div role="dialog" aria-label="รูปขยาย" className="bg-white rounded-xl p-2 sm:p-3 w-full sm:w-auto max-h-full overflow-auto"
            onClick={(e) => e.stopPropagation()}>
            <div className="flex justify-between items-center mb-2 px-1 gap-3">
              <span className="text-sm text-ink-soft truncate">
                {cur.driver_name} · {day(cur.trip_date)}{cur.booking_code ? ` · ${cur.booking_code}` : ''}
              </span>
              <button onClick={() => setZoom(false)} aria-label="ปิดรูปขยาย"
                className="min-h-11 min-w-11 shrink-0 rounded-lg hover:bg-ground flex items-center justify-center text-ink-soft text-xl">✕</button>
            </div>
            <div className="flex flex-col sm:flex-row gap-3">
              <img src={`/api/trips/${cur.id}/image`} alt="รูปสลิปขยาย"
                className="w-full sm:w-auto sm:max-w-[44vw] max-h-[70vh] sm:max-h-[82vh] object-contain rounded-lg" />
              {(cur.note || '').startsWith('รวม 2 รูป') && (
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
