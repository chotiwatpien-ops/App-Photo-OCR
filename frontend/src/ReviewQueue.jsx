import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api.js'
import { IssuesPanel } from './RunsIssues.jsx'

const n = (v) => (v === null || v === undefined || v === '' ? null : Number(v))
const fmt = (v) => (v === null || v === undefined ? '—' : Number(v).toLocaleString('th-TH'))

/** The same identity the backend checks: คุณได้รับ = ค่าโดยสารพื้นฐาน + โบนัส + เทอร์โบ.
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
  if (pct > 35) return `ค่าโดยสารผู้โดยสาร ${fmt(p)} สูงกว่าพื้นฐาน ${fmt(base)} ถึง ${pct}% — ปกติไม่เกิน 35%`
  if (pct < -2) return `ค่าโดยสารผู้โดยสาร ${fmt(p)} ต่ำกว่าพื้นฐาน ${fmt(base)} ${-pct}% — ผู้โดยสารจ่ายน้อยกว่าที่คนขับได้`
  return null
}

/** Why this row is sitting here, said with its own numbers. */
function why(t) {
  if (t.duplicate_of) {
    return { tone: 'red', chip: 'ซ้ำใน job', head: 'รูปนี้ซ้ำกับอีกแถวใน job เดียวกัน',
             body: t.note || 'booking code ตรงกันเป๊ะ — ถ้าใช่ให้ลบทิ้ง', act: 'ลบ' }
  }
  if (t.seen_in_job) {
    return { tone: 'red', chip: 'เคยอนุมัติแล้ว', head: `booking code นี้อนุมัติไปแล้วใน job #${t.seen_in_job}`,
             body: 'อนุมัติซ้ำจะทำให้เงินถูกนับสองรอบ — ตรวจรูปแล้วลบถ้าซ้ำจริง', act: 'ลบ' }
  }
  if (t.check_status === 'fail') {
    const m = money(t)
    // the backend re-checks on every edit, but never call a row broken while its own numbers
    // are sitting there adding up — that reads as the page arguing with itself
    if (m.known && m.diff === 0) {
      return { tone: 'slate', chip: 'แก้แล้ว', head: `แก้แล้วลงตัว — ${fmt(m.base)} + ${fmt(m.bonus)} + ${fmt(m.turbo)} = ${fmt(m.net)}`,
               body: 'ตรวจกับรูปอีกรอบแล้วกด A ได้เลย', act: 'อนุมัติ' }
    }
    return { tone: 'red', chip: 'เลขขัดกัน',
             head: m.known
               ? `รายได้ ${fmt(m.net)} ≠ พื้นฐาน ${fmt(m.base)} + โบนัส ${fmt(m.bonus)} + เทอร์โบ ${fmt(m.turbo)} = ${fmt(m.sum)}`
               : 'เลขในรูปไม่สอดคล้องกัน',
             body: m.known ? `ต่างกัน ${fmt(Math.abs(m.diff))} บาท — เทียบกับรูปแล้วแก้ช่องที่ผิด` : 'เทียบกับรูปแล้วกรอกให้ครบ',
             act: 'แก้' }
  }
  if (t.check_status === 'no_data') {
    const miss = ['base_fare', 'net_earnings'].filter((k) => n(t[k]) === null)
    const th = { base_fare: 'ค่าโดยสารพื้นฐาน', net_earnings: 'รายได้' }
    return { tone: 'amber', chip: 'ข้อมูลไม่พอ', head: 'รูปไม่มีเลขพอให้ตรวจทานกันเอง',
             body: miss.length ? `ยังขาด: ${miss.map((k) => th[k]).join(' · ')} — อ่านจากรูปแล้วกรอก` : 'อ่านจากรูปแล้วยืนยัน',
             act: 'กรอก' }
  }
  if (!t.trip_date) {
    return { tone: 'amber', chip: 'ไม่มีวันที่', head: 'ยังไม่ได้ระบุวันที่ของเที่ยวนี้',
             body: 'ใส่วันที่ก่อนถึงจะอนุมัติได้', act: 'ใส่วันที่' }
  }
  return { tone: 'slate', chip: 'รอคน', head: 'ตัวเลขผ่านการตรวจแล้ว รอแค่คนกดอนุมัติ',
           body: 'ดูรูปคร่าวๆ แล้วกด A ได้เลย', act: 'อนุมัติ' }
}

const TONE = {
  red: 'bg-red-100 text-red-700',
  amber: 'bg-amber-100 text-amber-700',
  slate: 'bg-slate-100 text-slate-600',
}
const BANNER = {
  red: 'bg-red-50 border-red-200 text-red-900',
  amber: 'bg-amber-50 border-amber-200 text-amber-900',
  slate: 'bg-slate-50 border-slate-200 text-slate-700',
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

const NEED_BOX = {
  block: 'border-red-400 bg-red-50 focus:border-red-500 focus:ring-red-100',
  want: 'border-amber-400 bg-amber-50 focus:border-amber-500 focus:ring-amber-100',
}
const NEED_TAG = { block: 'text-red-600', want: 'text-amber-700' }
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
    <label className="block">
      <span className="text-xs text-slate-500">
        {label}
        {asking && <span className={`ml-1 font-medium ${NEED_TAG[need]}`}>· {NEED_WORD[need]}</span>}
      </span>
      <input type={type} value={v} disabled={saving} ref={box} data-need={asking ? need : undefined}
        onChange={(e) => setV(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); commit(); box.current?.blur() } }}
        className={`mt-0.5 w-full rounded-lg border px-2 py-1.5 text-sm tabular-nums outline-none
          focus:ring-2 disabled:opacity-50
          ${dirty ? 'border-blue-400 bg-blue-50 focus:border-blue-500 focus:ring-blue-100'
            : asking ? NEED_BOX[need]
              : 'border-slate-200 bg-white focus:border-blue-500 focus:ring-blue-100'}`} />
      {hint && <span className="text-[11px] text-slate-400">{hint}</span>}
    </label>
  )
}

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
    if (!confirm(`เอา ${t.file_name} กลับเข้าคิวตรวจ?`)) return
    try {
      await api.restoreTrip(t.id)
      setRows(rows.filter((r) => r.id !== t.id))
      setMsg(`กู้ ${t.file_name} กลับเข้าคิวแล้ว — รีเฟรชหน้านี้เพื่อดู`)
    } catch (e) { setMsg(e.message) }
  }

  // hides, never deletes: the rows keep their note, their picture and their restore button
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
    <section className="bg-white rounded-xl border border-slate-200">
      <div className="flex items-center justify-between gap-3 px-5 py-3">
        <button onClick={() => setOpen(!open)} aria-expanded={open}
          className="min-h-11 text-left text-sm flex-1 min-w-0">
          <span className="text-slate-400">{open ? '▾' : '▸'}</span>
          <span className="ml-2 text-slate-600">รูปซ้ำที่ระบบทิ้งเอง</span>
          <span className="ml-2 font-semibold">{rows.length}</span>
          <span className="ml-2 text-slate-400 text-xs">
            {rows.length === 0
              ? '— ยังไม่มีของใหม่'
              : '— งานเดิมถูกนับไปแล้ว ไม่ต้องทำอะไร กดดูได้ถ้าอยากตรวจ'}
          </span>
        </button>
        <div className="flex items-center gap-3 text-xs shrink-0">
          {hidden > 0 && !everything && (
            <button onClick={() => { load(true); setOpen(true) }}
              className="min-h-11 px-1 text-blue-600 hover:underline">
              ดูของเก่าอีก {hidden}
            </button>
          )}
          {everything && (
            <button onClick={() => load(false)} className="min-h-11 px-1 text-blue-600 hover:underline">
              ดูเฉพาะของใหม่
            </button>
          )}
          {rows.length > 0 && !everything && (
            <button onClick={clear} className="min-h-11 px-1 text-slate-400 hover:text-slate-700">
              เคลียร์ เริ่มนับใหม่
            </button>
          )}
        </div>
      </div>
      {open && (
        <div className="px-5 pb-4">
          {msg && <p className="text-sm text-slate-600 mb-2">{msg}</p>}
          <table className="w-full text-sm">
            <thead><tr className="text-left text-slate-500 border-b border-slate-200 text-xs">
              <th className="py-1 pr-3">ไรเดอร์</th><th className="py-1 pr-3">ไฟล์</th>
              <th className="py-1 pr-3 text-right">รายได้</th><th className="py-1 pr-3">ทิ้งเพราะ</th><th></th>
            </tr></thead>
            <tbody>
              {rows.map((t) => (
                <tr key={t.id} className="border-b border-slate-100">
                  <td className="py-1.5 pr-3">{t.driver_name} <span className="text-slate-400 text-xs">job #{t.job_id}</span></td>
                  <td className="py-1.5 pr-3 text-slate-500">{t.file_name}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">฿{(t.net_earnings ?? 0).toLocaleString()}</td>
                  <td className="py-1.5 pr-3 text-slate-500 text-xs">{(t.note || '').split(' | ')[0]}</td>
                  <td className="py-1.5 text-right">
                    <button onClick={() => restore(t)} className="px-1 py-2 text-blue-600 hover:underline text-xs">กู้กลับเข้าคิว</button>
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

export default function ReviewQueue({ onOpenJob }) {
  const [rows, setRows] = useState(null)
  const [issues, setIssues] = useState([])
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [at, setAt] = useState(0)          // which row is open in the pane
  const [zoom, setZoom] = useState(false)
  const [queueOpen, setQueueOpen] = useState(false)   // the list is a panel on small screens
  const listRef = useRef(null)

  const load = useCallback(() => {
    api.reviewQueue()
      .then((r) => {
        setRows(r.rows); setIssues(r.issues || [])
        const back = r.rows.findIndex((x) => x.id === recall())
        setAt(back < 0 ? 0 : back)
      })
      .catch((e) => setMsg(e.message))
  }, [])
  useEffect(() => { load() }, [load])

  const cur = rows && rows[Math.min(at, rows.length - 1)]

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
    if (!t || !confirm(`ลบ ${t.file_name} ออกจากระบบ?`)) return
    try { await api.deleteTrip(t.id); setMsg(''); drop(t.id) } catch (e) { setMsg(e.message) }
  }, [])

  const edit = async (t, field, value) => {
    try {
      const updated = await api.patchTrip(t.id, { [field]: value })
      setRows((rs) => rs.map((r) => (r.id === t.id ? { ...r, ...updated } : r)))
      setMsg('')
    } catch (e) { setMsg(e.message) }
  }

  const approveAllPassing = async () => {
    const ok = rows.filter((t) => t.check_status === 'pass' && !t.duplicate_of && t.trip_date && !t.seen_in_job)
    if (!ok.length) return setMsg('ไม่มีแถวที่ผ่านเช็คให้อนุมัติ')
    if (!confirm(`อนุมัติ ${ok.length} แถวที่ผ่านการตรวจเลขทั้งหมด?\n(แถวที่ระบบไม่ชัวร์ เช่น เลขขัดกัน/ซ้ำ/ไม่มีวันที่ จะยังคงอยู่)`)) return
    setBusy(true)
    try {
      const res = await api.approvePassing()
      setMsg(`อนุมัติ ${res.approved} แถวแล้ว ✅ เหลือรอตรวจ ${res.skipped} แถว`)
      load()
    } catch (e) { setMsg(e.message) } finally { setBusy(false) }
  }

  const approveRest = async (jobId, name, force = false) => {
    try {
      const r = await api.commit(jobId, force)
      setMsg(`อนุมัติ ${r.written} รายการของ ${name} แล้ว ✅`)
      setRows((rs) => rs.filter((x) => x.job_id !== jobId))
    } catch (e) {
      if (!force && e.message.includes('บันทึกซ้ำ') && confirm(`⚠️ ${e.message}\n\nยืนยันอนุมัติทั้งหมดหรือไม่?`)) {
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
      if (k === 'j' || e.key === 'ArrowDown') { e.preventDefault(); setAt((i) => Math.min(i + 1, rows.length - 1)) }
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

  if (!rows) return <p className="text-slate-400">กำลังโหลด...</p>

  const groups = []
  for (const [i, t] of rows.entries()) {
    let g = groups.at(-1)
    if (!g || g.job_id !== t.job_id) {
      g = { job_id: t.job_id, driver_name: t.driver_name, rows: [] }
      groups.push(g)
    }
    g.rows.push({ ...t, _i: i })
  }

  return (
    <div className="space-y-4">
      <IssuesPanel issues={issues} />
      <DiscardedLog />

      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-baseline gap-3 flex-wrap">
          <p className="text-sm text-slate-600">
            รอตรวจ <strong className="text-base">{rows.length}</strong> รายการ
          </p>
          <div className="flex gap-1.5 text-xs">
            {counts.fail > 0 && <span className="rounded-full bg-red-100 text-red-700 px-2 py-0.5">เลขขัดกัน {counts.fail}</span>}
            {counts.dup > 0 && <span className="rounded-full bg-red-100 text-red-700 px-2 py-0.5">น่าจะซ้ำ {counts.dup}</span>}
            {counts.no_data > 0 && <span className="rounded-full bg-amber-100 text-amber-700 px-2 py-0.5">ข้อมูลไม่พอ {counts.no_data}</span>}
            {counts.nodate > 0 && <span className="rounded-full bg-amber-100 text-amber-700 px-2 py-0.5">ไม่มีวันที่ {counts.nodate}</span>}
            {counts.ready > 0 && <span className="rounded-full bg-emerald-100 text-emerald-700 px-2 py-0.5">พร้อมอนุมัติ {counts.ready}</span>}
          </div>
        </div>
        <div className="flex items-center gap-2 w-full lg:w-auto lg:gap-3">
          <span className="text-xs text-slate-400 hidden lg:inline">
            <kbd className="border rounded px-1">J</kbd>/<kbd className="border rounded px-1">K</kbd> เลื่อน ·
            <kbd className="border rounded px-1 ml-1">A</kbd> อนุมัติ ·
            <kbd className="border rounded px-1 ml-1">X</kbd> ลบ ·
            <kbd className="border rounded px-1 ml-1">Z</kbd> ขยายรูป ·
            <kbd className="border rounded px-1 ml-1">E</kbd> ช่องที่ต้องกรอก
          </span>
          <button onClick={approveAllPassing} disabled={busy || !counts.ready}
            className="flex-1 lg:flex-none min-h-11 bg-emerald-600 hover:bg-emerald-700 disabled:bg-slate-300 text-white rounded-lg px-4 py-2 text-sm font-medium">
            {busy ? 'กำลังอนุมัติ…' : `✓ อนุมัติ ${counts.ready} แถวที่ผ่านเช็ค`}
          </button>
          <button onClick={load}
            className="min-h-11 shrink-0 rounded-lg border border-slate-300 bg-white px-3 text-sm text-blue-600 hover:border-blue-400">
            รีเฟรช
          </button>
        </div>
      </div>
      {msg && <p className="text-sm text-red-600">⚠️ {msg}</p>}

      {rows.length === 0 ? (
        <div className="bg-white rounded-xl border border-slate-200 p-10 text-center text-slate-400">
          🎉 ไม่มีอะไรรอตรวจ
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[20rem_1fr] items-start">
          {/* the queue — reason first, because that is what decides the next move.
              On a phone it is navigation, not the work: it folds away so the row under review
              owns the screen, and reopens on demand. */}
          <div className="min-w-0">
            <button onClick={() => setQueueOpen((o) => !o)} aria-expanded={queueOpen}
              className="lg:hidden w-full min-h-11 flex items-center justify-between gap-2 rounded-xl border border-slate-200 bg-white px-4 text-sm">
              <span className="text-slate-600">เลือกแถวจากรายการ</span>
              <span className="text-slate-400">{queueOpen ? 'ปิดรายการ ▴' : 'ดูรายการ ▾'}</span>
            </button>
          <div ref={listRef}
            className={`${queueOpen ? 'block' : 'hidden'} lg:block mt-2 lg:mt-0 bg-white rounded-xl border border-slate-200 overflow-y-auto max-h-[60vh] lg:max-h-[78vh]`}>
            {groups.map((g) => (
              <div key={g.job_id}>
                <div className="sticky top-0 bg-slate-50 border-y border-slate-200 px-3 py-1.5 z-10">
                  <p className="text-sm font-medium truncate">{g.driver_name}</p>
                  <p className="text-xs text-slate-400">
                    job #{g.job_id} · รอ {g.rows.length}
                    <button onClick={() => onOpenJob(g.job_id)}
                      className="ml-2 inline-block -my-1 px-1 py-1.5 text-blue-600 hover:underline">เปิดทั้ง job</button>
                  </p>
                </div>
                {g.rows.map((t) => {
                  const w = why(t)
                  const sel = t._i === at
                  return (
                    <button key={t.id} data-sel={sel ? '1' : '0'}
                      onClick={() => { setAt(t._i); setQueueOpen(false) }}
                      className={`w-full text-left px-3 py-2.5 border-b border-slate-100 flex items-center gap-2
                        ${sel ? 'bg-blue-50 ring-1 ring-inset ring-blue-300' : 'hover:bg-slate-50'}`}>
                      <img src={`/api/trips/${t.id}/image`} alt="" loading="lazy"
                        className="h-10 w-10 shrink-0 object-cover rounded border border-slate-200"
                        onError={(e) => { e.currentTarget.style.visibility = 'hidden' }} />
                      <span className="min-w-0 flex-1">
                        <span className={`text-[11px] rounded-full px-1.5 py-0.5 ${TONE[w.tone]}`}>{w.chip}</span>
                        <span className="block text-xs text-slate-400 truncate mt-0.5">{t.file_name}</span>
                      </span>
                      <span className="text-sm tabular-nums text-slate-600 shrink-0">฿{fmt(t.net_earnings)}</span>
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
              <div className="bg-white rounded-xl border border-slate-200 p-4 space-y-3">
                <div className="flex items-start justify-between gap-3 flex-wrap">
                  <div className="min-w-0 flex-1">
                    <p className="font-medium">
                      {cur.driver_name}
                      <span className="block truncate lg:inline lg:ml-2 text-slate-400 font-normal text-sm">{cur.file_name}</span>
                    </p>
                    <p className="text-xs text-slate-400">
                      job #{cur.job_id} · {cur.booking_code || 'ไม่มี booking code'} ·
                      <button onClick={() => onOpenJob(cur.job_id)}
                        className="ml-1 inline-block -my-1 px-1 py-1.5 text-blue-600 hover:underline">เปิดทั้ง job</button>
                    </p>
                  </div>
                  <p className="hidden lg:block text-xs text-slate-400 tabular-nums">{at + 1} / {rows.length}</p>
                </div>

                <div className={`rounded-lg border px-3 py-2 ${BANNER[w.tone]}`}>
                  <p className="text-sm font-medium">{w.head}</p>
                  <p className="text-xs mt-0.5 opacity-80">{w.body}</p>
                </div>
                {warn && (
                  <p className="text-xs rounded-lg border border-amber-200 bg-amber-50 text-amber-900 px-3 py-2">
                    ⚠️ {warn}
                  </p>
                )}

                <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_16rem]">
                  {/* the picture, at a size you can actually read */}
                  <button onClick={() => setZoom(true)} className="block w-full" title="กดเพื่อขยาย (Z)">
                    {/* two halves side by side is unreadable under ~640px: stack them there */}
                    <div className="relative flex flex-col sm:flex-row gap-2 justify-center bg-slate-50 rounded-lg border border-slate-200 p-2">
                      <img src={`/api/trips/${cur.id}/image`} alt=""
                        className="mx-auto max-h-[46vh] sm:max-h-[52vh] w-auto object-contain rounded"
                        onError={(e) => { e.currentTarget.style.visibility = 'hidden' }} />
                      {two && (
                        <img src={`/api/trips/${cur.id}/image?part=2`} alt=""
                          className="mx-auto max-h-[46vh] sm:max-h-[52vh] w-auto object-contain rounded"
                          onError={(e) => { e.currentTarget.style.display = 'none' }} />
                      )}
                      <span className="lg:hidden absolute bottom-3 right-3 rounded-md bg-slate-900/70 px-2 py-1 text-[11px] font-medium text-white">
                        แตะเพื่อขยาย
                      </span>
                    </div>
                  </button>

                  <div className="space-y-2.5">
                    {asks > 0 && (
                      <p className={`text-xs rounded-lg px-2 py-1.5 ${need.trip_date
                        ? 'bg-red-50 text-red-800' : 'bg-amber-50 text-amber-900'}`}>
                        ต้องกรอก {asks} ช่องที่ไฮไลต์ไว้ — กด <kbd className="border rounded px-1">E</kbd> ไปช่องแรกได้เลย
                      </p>
                    )}
                    <Field label="วันที่" type="date" value={cur.trip_date} need={need.trip_date}
                      onSave={(v) => edit(cur, 'trip_date', v)} />
                    <Field label="รายได้ (คุณได้รับ)" value={cur.net_earnings} need={need.net_earnings}
                      onSave={(v) => edit(cur, 'net_earnings', v)} />
                    <Field label="ค่าโดยสารพื้นฐาน" value={cur.base_fare} need={need.base_fare}
                      onSave={(v) => edit(cur, 'base_fare', v)} />
                    <div className="grid grid-cols-2 gap-2">
                      <Field label="โบนัส" value={cur.bonus} onSave={(v) => edit(cur, 'bonus', v)} />
                      <Field label="เทอร์โบ" value={cur.turbo} onSave={(v) => edit(cur, 'turbo', v)} />
                    </div>
                    {m.known && (
                      <p className={`text-xs rounded-lg px-2 py-1.5 ${m.diff === 0
                        ? 'bg-emerald-50 text-emerald-800' : 'bg-red-50 text-red-800'}`}>
                        {m.diff === 0
                          ? `✓ ลงตัว — ${fmt(m.base)} + ${fmt(m.bonus)} + ${fmt(m.turbo)} = ${fmt(m.net)}`
                          : `ยังต่างอยู่ ${fmt(Math.abs(m.diff))} (รวมได้ ${fmt(m.sum)} แต่รายได้ ${fmt(m.net)})`}
                      </p>
                    )}
                    <Field label="ค่าโดยสารของผู้โดยสาร" value={cur.passenger_total}
                      onSave={(v) => edit(cur, 'passenger_total', v)}
                      hint="ยอดที่แกร็บคิดค่าบริการ ไม่ใช่ยอดรวมที่ผู้โดยสารจ่าย" />

                    {/* on a touch screen these two live in the bar pinned at the bottom instead,
                        where a thumb can reach them without scrolling past the picture */}
                    <div className="hidden lg:flex gap-2 pt-1">
                      <button onClick={() => approve(cur)} disabled={!cur.trip_date}
                        title={cur.trip_date ? 'อนุมัติ (A)' : 'ต้องใส่วันที่ก่อน'}
                        className="flex-1 bg-emerald-600 hover:bg-emerald-700 disabled:bg-slate-300 text-white rounded-lg px-3 py-2 text-sm font-medium">
                        อนุมัติ <span className="opacity-60 text-xs">A</span>
                      </button>
                      <button onClick={() => remove(cur)} title="ลบ (X)"
                        className="rounded-lg border border-red-200 text-red-700 hover:border-red-400 hover:bg-red-50 px-3 py-2 text-sm">
                        ลบ <span className="opacity-50 text-xs">X</span>
                      </button>
                    </div>
                    <button onClick={() => confirm(`อนุมัติทุกแถวที่เหลือของ ${cur.driver_name}?`) && approveRest(cur.job_id, cur.driver_name)}
                      className="w-full min-h-11 lg:min-h-0 text-xs text-emerald-700 hover:underline pt-0.5">
                      อนุมัติที่เหลือทั้งหมดของ {cur.driver_name}
                    </button>
                  </div>
                </div>

                <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate-500 border-t border-slate-100 pt-2">
                  <span>จ่าย: {cur.payment_method || '—'}</span>
                  <span>กม.: {fmt(cur.distance_km)}</span>
                  <span>เวลา: {cur.trip_time || '—'}</span>
                  <span>ประเภท: {cur.service_type || '—'}</span>
                  {cur.pickup_text && <span className="truncate max-w-xs">{cur.pickup_text} → {cur.dropoff_text}</span>}
                </div>
                {cur.note && <p className="text-xs text-amber-700 bg-amber-50 rounded p-2">⚠️ {cur.note}</p>}
              </div>
            )
          })()}
        </div>
      )}

      {/* Touch has no J/K/A/X. Everything the keyboard does for a reviewer at a desk is pinned
          here instead, inside thumb reach, and clear of the home indicator. */}
      {cur && (
        <>
          <div className="h-32 lg:hidden" aria-hidden="true" />
          <div className="lg:hidden fixed inset-x-0 bottom-0 z-40 border-t border-slate-200 bg-white/95 backdrop-blur
                          px-3 pt-2 pb-[max(0.5rem,env(safe-area-inset-bottom))] space-y-2">
            <div className="flex items-center gap-2">
              <button onClick={() => setAt((i) => Math.max(i - 1, 0))} disabled={at === 0}
                className="min-h-11 flex-1 rounded-lg border border-slate-300 bg-white text-sm disabled:opacity-40">
                ก่อนหน้า
              </button>
              <span className="min-w-20 text-center text-sm tabular-nums text-slate-500">
                {at + 1} / {rows.length}
              </span>
              <button onClick={() => setAt((i) => Math.min(i + 1, rows.length - 1))} disabled={at >= rows.length - 1}
                className="min-h-11 flex-1 rounded-lg border border-slate-300 bg-white text-sm disabled:opacity-40">
                ถัดไป
              </button>
            </div>
            <div className="flex gap-2">
              <button onClick={() => approve(cur)} disabled={!cur.trip_date}
                className="min-h-12 flex-1 rounded-lg bg-emerald-600 text-white text-sm font-medium disabled:bg-slate-300">
                {cur.trip_date ? 'อนุมัติ' : 'ต้องใส่วันที่ก่อน'}
              </button>
              <button onClick={() => remove(cur)}
                className="min-h-12 rounded-lg border border-red-200 bg-white px-5 text-sm font-medium text-red-700">
                ลบ
              </button>
            </div>
          </div>
        </>
      )}

      {zoom && cur && (
        <div className="fixed inset-0 bg-black/80 flex items-center justify-center z-50 p-2 sm:p-6"
          onClick={() => setZoom(false)}>
          {/* zooming is what a small screen needs MOST, so here the picture takes the whole of it */}
          <div className="bg-white rounded-xl p-2 sm:p-3 w-full sm:w-auto max-h-full overflow-auto"
            onClick={(e) => e.stopPropagation()}>
            <div className="flex justify-between items-center mb-2 px-1 gap-3">
              <span className="text-sm text-slate-600 truncate">
                {cur.driver_name} · {cur.file_name}{cur.booking_code ? ` · ${cur.booking_code}` : ''}
              </span>
              <button onClick={() => setZoom(false)} aria-label="ปิด"
                className="min-h-11 min-w-11 shrink-0 text-slate-400 hover:text-slate-700 text-xl">✕</button>
            </div>
            <div className="flex flex-col sm:flex-row gap-3">
              <img src={`/api/trips/${cur.id}/image`} alt=""
                className="w-full sm:w-auto sm:max-w-[44vw] max-h-[70vh] sm:max-h-[82vh] object-contain rounded-lg" />
              {(cur.note || '').startsWith('รวม 2 รูป') && (
                <img src={`/api/trips/${cur.id}/image?part=2`} alt=""
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
