import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api.js'
import Icon from './Icon.jsx'

// ชุดเฉลย: almost every row is approved with nobody looking, so nothing said how often the AI
// reads a slip right (Fiat 2026-11-25). Here a person checks auto-approved slips against the
// picture, one slip per screen, and the page shows the accuracy of each field.
//   - Checking never changes a trip: the answers are stored beside it, so a closed week can be checked.
//   - The server picks the slips, in a fixed random order. There is no skip and no choosing,
//     because skipping the hard slips is how a sample turns into a flattering one.
//   - This file holds no list of fields. Labels, kinds, options and hints come with the report.

const fmt = (n) => (n ?? 0).toLocaleString('th-TH')
const wk = (label) => (label || '').replace(/^\d{4}-W/, 'WK')
const p1 = (x) => (x >= 0.9995 ? '100' : (x * 100).toFixed(1))
const pct = (x) => (x == null ? '—' : `${(x * 100).toFixed(1)}%`)
const groups4 = (code) => code.replace(/(.{4})/g, '$1 ').trim()
const say = (field, value) => (field.kind === 'code' ? groups4(value.replace(/\s+/g, '').toUpperCase()) : value)

let sessionChecker = ''
// the app has no user identity; this only tells two phones apart so they get different slips
function checkerId() {
  const make = () => Math.random().toString(36).slice(2, 10).padEnd(8, '0')
  try {
    let id = window.localStorage.getItem('pocr-key-checker')
    if (!id) { id = make(); window.localStorage.setItem('pocr-key-checker', id) }
    return id
  } catch {
    sessionChecker = sessionChecker || make()
    return sessionChecker
  }
}

function Card({ children, className = '', ...rest }) {
  return <section className={`bg-white border border-line rounded-xl ${className}`} {...rest}>{children}</section>
}

// Coloured by the low end of the range, not the point value: 100% of twenty slips is not yet good
// news. It is not bad news either, so a rate with nothing wrong in sight stays amber until more
// slips are checked, and red is kept for a field that was seen to fall short.
const tone = ({ rate, low }) => (low >= 0.97 ? 'bg-ok-bg text-ok-ink'
  : low >= 0.9 || rate >= 0.97 ? 'bg-warn-bg text-warn-ink' : 'bg-danger-bg text-danger-ink')

function Rate({ count, big = false }) {
  if (count.rate == null) return <span className="text-muted">—</span>
  return (
    <span className="inline-flex flex-col items-end gap-0.5">
      <span className={`rounded-md px-2 py-0.5 font-semibold tabular-nums ${big ? 'text-xl' : ''} ${tone(count)}`}>{pct(count.rate)}</span>
      <span className="text-xs text-muted tabular-nums whitespace-nowrap">ช่วง {p1(count.low)}–{p1(count.high)}</span>
    </span>
  )
}

function FieldTable({ fields, counts }) {
  return (
    <>
      <ul className="sm:hidden flex flex-col">
        {fields.map((f) => {
          const c = counts[f.key]
          return (
            <li key={f.key} className="py-3 border-t border-line-soft flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="font-medium">{f.label}</p>
                <p className="text-sm text-ink-soft">
                  ถูก {fmt(c.right)} · ผิด {fmt(c.wrong)}{c.missed > 0 && ` (ในนี้ AI เว้นว่าง ${fmt(c.missed)})`}
                </p>
                <p className="text-sm text-muted">
                  ไม่มีในรูป {fmt(c.absent_blank + c.absent_filled)}{c.absent_filled > 0 && ` (แถวมีค่า ${fmt(c.absent_filled)})`}
                </p>
              </div>
              <Rate count={c} big />
            </li>
          )
        })}
      </ul>
      <table className="hidden sm:table w-full text-sm tabular-nums">
        <thead>
          <tr className="text-muted border-b border-line">
            <th rowSpan={2} className="font-normal text-left py-2 pr-2 align-bottom">ช่อง</th>
            <th colSpan={3} className="font-normal text-center pt-2 px-2">AI อ่าน</th>
            <th colSpan={2} className="font-normal text-center pt-2 px-2 border-l border-line-soft">ไม่มีในรูป</th>
          </tr>
          <tr className="text-muted border-b border-line">
            <th className="font-normal text-right py-2 px-2">ถูก</th>
            <th className="font-normal text-right py-2 px-2">ผิด</th>
            <th className="font-normal text-right py-2 px-2">ความแม่นยำ (ช่วงที่น่าจะเป็น)</th>
            <th className="font-normal text-right py-2 px-2 border-l border-line-soft">แถวว่าง</th>
            <th className="font-normal text-right py-2 pl-2">แถวมีค่า</th>
          </tr>
        </thead>
        <tbody>
          {fields.map((f) => {
            const c = counts[f.key]
            return (
              <tr key={f.key} className="border-b border-line-soft align-top">
                <td className="py-2.5 pr-2 font-medium">{f.label}</td>
                <td className="py-2.5 px-2 text-right">{fmt(c.right)}</td>
                <td className="py-2.5 px-2 text-right">
                  {fmt(c.wrong)}
                  {c.missed > 0 && <span className="block text-xs text-muted">ในนี้ AI เว้นว่าง {fmt(c.missed)}</span>}
                </td>
                <td className="py-2.5 px-2 text-right"><Rate count={c} /></td>
                <td className="py-2.5 px-2 text-right border-l border-line-soft">{fmt(c.absent_blank)}</td>
                <td className="py-2.5 pl-2 text-right">{fmt(c.absent_filled)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </>
  )
}

const reader = (g) => `${g.model || 'ไม่ทราบโมเดล'} · ${g.prompt_version ? `prompt ${g.prompt_version}` : 'ไม่ได้บันทึกรุ่น prompt'}`

function ReaderTable({ fields, groups }) {
  return (
    <ul className="flex flex-col">
      {groups.map((g) => (
        <li key={`${g.model}|${g.prompt_version}`} className="py-3 border-t border-line-soft flex flex-col gap-1.5">
          <p className="font-medium break-words">{reader(g)} <span className="font-normal text-muted">· {fmt(g.slips)} ใบ</span></p>
          <ul className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
            {fields.map((f) => (
              <li key={f.key} className="whitespace-nowrap">
                <span className="text-muted">{f.label}</span> <span className="tabular-nums font-medium">{pct(g.fields[f.key].rate)}</span>
              </li>
            ))}
          </ul>
        </li>
      ))}
    </ul>
  )
}

function MissList({ fields, misses }) {
  const byKey = Object.fromEntries(fields.map((f) => [f.key, f]))
  return (
    <ul className="flex flex-col">
      {misses.map((m) => {
        const f = byKey[m.field] || { label: m.field, kind: 'text' }
        return (
          <li key={`${m.trip_id}:${m.field}`} className="py-2.5 border-t border-line-soft text-sm flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
            <span className="text-muted tabular-nums">#{m.trip_id}</span>
            <span className="font-medium">{f.label}</span>
            <span className="break-all"><span className="text-muted">แถว</span> {m.row == null ? 'ว่าง' : say(f, m.row)}</span>
            <span className="break-all"><span className="text-muted">รูป</span> {say(f, m.truth)}</span>
            {m.open && <a href={m.open} target="_blank" rel="noreferrer" className="text-accent hover:underline whitespace-nowrap">เปิดรูป</a>}
          </li>
        )
      })}
    </ul>
  )
}

function KeyReport({ data }) {
  const { total, fields } = data
  if (!total.slips) {
    return (
      <Card className="p-4 sm:px-6 sm:py-5">
        <p className="font-medium">ยังไม่ได้ตรวจ{data.week === 'all' ? '' : 'สัปดาห์นี้'}</p>
        <p className="text-sm text-muted">
          {data.week === 'all' ? 'เลือกสัปดาห์ แล้วกด ตรวจต่อ เพื่อเริ่ม' : 'กด ตรวจต่อ เพื่อเริ่ม'} ตรวจ 100 ใบใช้ราว 20 นาที
        </p>
      </Card>
    )
  }
  return (
    <>
      <Card aria-labelledby="key-fields-h" className="p-4 sm:px-6 sm:py-5">
        <h2 id="key-fields-h" className="text-[17px] font-semibold">ความแม่นยำแต่ละช่อง</h2>
        <p className="text-sm text-muted mb-2">
          ถูกทุกช่อง {fmt(total.all_right)} จาก {fmt(total.slips)} ใบ ({pct(total.all_right / total.slips)})
          {total.seconds_per_slip != null && ` · ใช้เวลาตรวจราว ${fmt(Math.round(total.seconds_per_slip))} วินาทีต่อใบ`}
        </p>
        <FieldTable fields={fields} counts={total.fields} />
        <ul className="mt-3 text-sm text-muted flex flex-col gap-1">
          <li>ความแม่นยำ = ถูก ÷ (ถูก + ผิด) ช่องที่ไม่มีในรูปไม่ถูกนับรวม</li>
          <li>ช่วงที่น่าจะเป็น คือค่าจริงของทั้งสัปดาห์น่าจะอยู่ในช่วงนี้ ยิ่งตรวจมากใบ ช่วงยิ่งแคบ</li>
          <li>ไม่มีในรูป แถวมีค่า คือรูปไม่มีข้อมูลนี้ แต่แถวมีค่าอยู่ เช่น รหัสที่จอตัด หรือค่าที่ระบบเติมให้</li>
        </ul>
      </Card>
      {data.by_reader.length > 1 && (
        <Card aria-labelledby="key-readers-h" className="p-4 sm:px-6 sm:py-5">
          <h2 id="key-readers-h" className="text-[17px] font-semibold">แยกตามตัวอ่าน</h2>
          <p className="text-sm text-muted mb-2">โมเดลและรุ่นของ prompt ที่อ่านใบนั้น ณ ตอนที่ตรวจ</p>
          <ReaderTable fields={fields} groups={data.by_reader} />
        </Card>
      )}
      <Card aria-labelledby="key-misses-h" className="p-4 sm:px-6 sm:py-5">
        <h2 id="key-misses-h" className="text-[17px] font-semibold">ช่องที่ AI อ่านผิด {fmt(data.misses.length)} ช่อง</h2>
        <p className="text-sm text-muted mb-2">ใช้ดูว่าควรปรับ AI ตรงไหน หน้านี้ไม่แก้แถวและไม่แก้ไฟล์ที่ส่งลูกค้าแล้ว</p>
        {data.misses.length === 0 ? <p className="text-sm text-muted">ไม่มี</p> : <MissList fields={fields} misses={data.misses} />}
      </Card>
    </>
  )
}

/** One picture of the slip. Drive first (the viewer's own Google session, no load on our server
 *  or database), then the copy our server fetches. It always says whether it loaded. */
function OnePicture({ picture, label, shown, onState }) {
  const sources = [picture.drive_id && `https://drive.google.com/thumbnail?id=${picture.drive_id}&sz=w1600`, picture.fallback].filter(Boolean)
  const [at, setAt] = useState(0)
  const [state, setState] = useState('loading')
  const settle = (s) => { setState(s); onState(s) }
  return (
    <div className={`min-w-0 shrink-0 w-[var(--one)] lg:w-[var(--each)] ${shown ? '' : 'hidden lg:block'}`}>
      {state !== 'bad' && (
        <img key={sources[at]} src={sources[at]} alt={label} referrerPolicy="no-referrer" onLoad={() => settle('ok')}
          onError={() => (at + 1 < sources.length ? setAt(at + 1) : settle('bad'))}
          className="block w-full h-auto bg-white" />
      )}
      {state === 'loading' && <p className="min-h-32 flex items-center justify-center text-sm text-muted">กำลังโหลดรูป…</p>}
      {state === 'bad' && (
        <p role="alert" className="m-3 min-h-32 rounded-lg bg-danger-bg text-danger-ink text-sm px-3 flex flex-col items-center justify-center gap-1 text-center">
          โหลดรูปไม่ได้
          {picture.open && <a href={picture.open} target="_blank" rel="noreferrer" className="underline">เปิดรูปใน Drive</a>}
        </p>
      )}
    </div>
  )
}

const PART_NAMES = ['รูปบน', 'รูปล่าง']

function SlipPicture({ pictures, onState }) {
  const [part, setPart] = useState(0)
  const [zoom, setZoom] = useState(1)
  const [states, setStates] = useState(() => pictures.map(() => 'loading'))
  // a trip built from two pictures counts as seen only when both halves could be looked at
  const all = states.includes('bad') ? 'bad' : states.every((s) => s === 'ok') ? 'ok' : 'loading'
  useEffect(() => { onState(all) }, [all, onState])
  return (
    <div className="relative h-full min-h-0 bg-line-soft">
      <div className="h-full overflow-auto overscroll-contain" onClick={() => setZoom(zoom === 1 ? 2 : 1)}
        style={{ '--one': `${zoom * 100}%`, '--each': `${(zoom * 100) / pictures.length}%` }}>
        <div className="flex items-start">
          {pictures.map((p, i) => (
            <OnePicture key={p.fallback} picture={p} label={pictures.length > 1 ? PART_NAMES[i] : 'รูปสลิป'} shown={i === part}
              onState={(s) => setStates((was) => was.map((x, j) => (j === i ? s : x)))} />
          ))}
        </div>
      </div>
      <div className="absolute right-2 bottom-2 flex gap-2">
        {pictures.length > 1 && (
          <div role="group" aria-label="เลือกรูป" className="lg:hidden flex rounded-lg overflow-hidden border border-line bg-white">
            {pictures.map((p, i) => (
              <button key={p.fallback} type="button" onClick={() => setPart(i)} aria-pressed={i === part}
                className={`min-h-10 px-3 text-sm ${i === part ? 'bg-ink text-white' : 'text-ink-soft'}`}>{PART_NAMES[i]}</button>
            ))}
          </div>
        )}
        <button type="button" onClick={() => setZoom(zoom === 1 ? 2 : 1)}
          className="min-h-10 px-3 rounded-lg border border-line bg-white text-sm text-ink-soft">
          {zoom === 1 ? 'ขยาย 2 เท่า' : 'ย่อกลับ'}
        </button>
      </div>
    </div>
  )
}

// an empty value, or a choice the list does not have, cannot be confirmed as "matches the picture"
const mustChoose = (field, shown) => shown == null || (field.kind === 'choice' && !field.options.includes(shown))

function sameAs(field, typed, shown) {
  if (mustChoose(field, shown)) return false
  const text = typed.trim()
  if (field.kind === 'number') return text !== '' && Number(text.replace(/,/g, '')) === Number(shown)
  if (field.kind === 'code') return text.replace(/\s+/g, '').toUpperCase() === shown
  return text === shown
}

const SAME = { mode: 'same', value: '' }
const INPUT = 'min-h-12 w-full rounded-lg border border-line bg-white px-3 text-[17px] outline-none focus:border-accent'

function FactRow({ field, shown, draft, onChange }) {
  const [open, setOpen] = useState(false)
  const stuck = draft.mode === 'same' && mustChoose(field, shown)
  const typed = draft.mode === 'edit' ? draft.value : (shown ?? '')
  const type = (value) => onChange(sameAs(field, value, shown) ? SAME : { mode: 'edit', value })
  const [text, cls] = draft.mode === 'absent' ? ['ไม่มีในรูป', 'text-warn-ink font-medium']
    : draft.mode === 'edit' ? (draft.value.trim() ? [`แก้เป็น ${say(field, draft.value.trim())}`, 'text-accent font-medium'] : ['ยังไม่ได้พิมพ์ค่า', 'text-warn-ink font-medium'])
      : stuck ? [shown == null ? 'ว่าง · ต้องเลือก' : `${shown} · ต้องเลือก`, 'text-warn-ink font-medium']
        : [say(field, shown), 'text-ink']
  const onEnter = (e) => { if (e.key === 'Enter') { e.preventDefault(); setOpen(false) } }
  return (
    <li className={`border-b border-line-soft ${stuck ? 'bg-warn-bg' : ''}`}>
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
        className="w-full min-h-12 px-4 py-1.5 flex items-center justify-between gap-3 text-left">
        <span className="text-sm text-ink-soft shrink-0">{field.label}</span>
        <span className="flex items-center gap-1 min-w-0">
          <span className={`text-[17px] tabular-nums text-right break-words min-w-0 ${field.kind === 'code' ? 'font-mono' : ''} ${cls}`}>{text}</span>
          <Icon name="chevron" size={16} className={`shrink-0 text-muted transition-transform ${open ? 'rotate-90' : ''}`} />
        </span>
      </button>
      {open && (
        <div className="px-4 pb-3 flex flex-col gap-2.5">
          <p className="text-xs text-muted">{field.hint}</p>
          {field.kind === 'choice' ? (
            <div role="group" aria-label={field.label} className="flex flex-wrap gap-2">
              {field.options.map((o) => {
                const on = draft.mode === 'edit' ? draft.value === o : draft.mode === 'same' && shown === o
                return (
                  <button key={o} type="button" aria-pressed={on}
                    onClick={() => { onChange(o === shown ? SAME : { mode: 'edit', value: o }); setOpen(false) }}
                    className={`min-h-11 px-4 rounded-full border text-[15px] ${on ? 'bg-ink text-white border-ink' : 'bg-white text-ink border-line'}`}>
                    {o}
                  </button>
                )
              })}
            </div>
          ) : field.kind === 'time' ? (
            <input type="time" aria-label={field.label} value={typed} onChange={(e) => type(e.target.value)} onKeyDown={onEnter} className={INPUT} />
          ) : field.kind === 'number' ? (
            <input type="text" inputMode="decimal" aria-label={field.label} value={typed} onChange={(e) => type(e.target.value)}
              onKeyDown={onEnter} className={INPUT} />
          ) : (
            <input type="text" aria-label={field.label} value={typed} onChange={(e) => type(e.target.value)} onKeyDown={onEnter}
              autoCapitalize="characters" autoCorrect="off" autoComplete="off" spellCheck={false} className={`${INPUT} font-mono uppercase`} />
          )}
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => { onChange({ mode: 'absent', value: '' }); setOpen(false) }}
              className="min-h-11 px-3 rounded-lg border border-line bg-white text-sm">ไม่มีในรูป / อ่านไม่ออก</button>
            {draft.mode !== 'same' && (
              <button type="button" onClick={() => onChange(SAME)}
                className="min-h-11 px-3 rounded-lg text-sm text-accent hover:underline">คืนค่าเดิม</button>
            )}
          </div>
        </div>
      )}
    </li>
  )
}

const freshDraft = (fields) => Object.fromEntries(fields.map((f) => [f.key, SAME]))

// every field appears once: in facts with the printed value, or in absent
function toAnswer(slip, draft, seconds) {
  const facts = {}
  const absent = []
  for (const [key, d] of Object.entries(draft)) {
    if (d.mode === 'absent') absent.push(key)
    else facts[key] = d.mode === 'same' ? slip.shown[key] : d.value.trim()
  }
  return { trip_id: slip.trip_id, facts, absent, seconds }
}

const MAX_SECONDS = 600
const SLOW_PICTURE_MS = 8000

function CheckFlow({ week, label, fields, onExit }) {
  const checker = useMemo(checkerId, [])
  const [progress, setProgress] = useState(null)
  const [slip, setSlip] = useState(undefined)       // undefined = not asked yet, null = nothing to hand out
  const [draft, setDraft] = useState({})
  const [spent, setSpent] = useState(0)             // seconds already spent on this slip in an earlier look
  const [pic, setPic] = useState('loading')
  const [slow, setSlow] = useState(false)
  const [prev, setPrev] = useState(null)            // the slip just answered, one deep, for ย้อนใบก่อน
  const [aside, setAside] = useState(null)          // the slip put down while the previous one is answered again
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const seenAt = useRef(0)
  const list = useRef(null)
  const redoing = aside !== null

  const show = useCallback((next, keep) => {
    setSlip(next)
    setDraft(keep?.draft || freshDraft(fields))
    setSpent(keep?.spent || 0)
    setPic('loading')
    setSlow(false)
    seenAt.current = 0
    list.current?.scrollTo(0, 0)
  }, [fields])

  const call = useCallback(async (answer, answered) => {
    setBusy(true)
    setErr('')
    try {
      const turn = await api.answerKeyCheck(week, checker, answer)
      setProgress(turn.progress)
      if (answered) setPrev(answered)
      // the slip put aside is still this phone's open claim, so the server hands it straight back
      const back = aside?.slip && turn.slip && aside.slip.trip_id === turn.slip.trip_id ? aside : null
      setAside(null)
      show(turn.slip, back)
    } catch (e) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }, [week, checker, aside, show])

  useEffect(() => { call() }, [])

  const onPicture = useCallback((state) => {
    setPic(state)
    if (state === 'ok' && !seenAt.current) seenAt.current = Date.now()
  }, [])

  const tripId = slip?.trip_id
  useEffect(() => {
    if (!tripId || pic !== 'loading') return undefined
    const t = setTimeout(() => setSlow(true), SLOW_PICTURE_MS)
    return () => clearTimeout(t)
  }, [tripId, pic])

  const waiting = slip ? fields.filter((f) => {
    const d = draft[f.key] || SAME
    return d.mode === 'same' ? mustChoose(f, slip.shown[f.key]) : d.mode === 'edit' && !d.value.trim()
  }).length : 0
  const changed = fields.filter((f) => (draft[f.key] || SAME).mode !== 'same').length
  const seen = pic === 'ok'
  const canSave = Boolean(slip) && seen && waiting === 0 && !busy
  const canGiveUp = Boolean(slip) && !busy && (pic === 'bad' || (pic === 'loading' && slow))

  const save = () => {
    const seconds = Math.min(MAX_SECONDS, spent + Math.round((Date.now() - seenAt.current) / 1000))
    call(toAnswer(slip, draft, seconds), { slip, draft, spent: seconds })
  }
  const giveUp = () => call({ trip_id: slip.trip_id, no_picture: true }, { slip, draft, spent })
  const goBack = () => {
    setAside({ slip, draft, spent })
    setErr('')
    show(prev.slip, prev)
    setPrev(null)
  }

  const saveRef = useRef(null)
  saveRef.current = canSave ? save : null
  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== 'Enter' || e.target.closest('input, button, a, select, textarea, [role=dialog]')) return
      saveRef.current?.()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  const left = progress ? progress.eligible - progress.checked - progress.no_picture : 0
  const title = !progress ? wk(label)
    : redoing ? `${wk(label)} · ใบก่อนหน้า`
      : slip ? `${wk(label)} · ใบที่ ${fmt(progress.checked + progress.no_picture + 1)}` : wk(label)

  return (
    <div className="fixed inset-x-0 top-0 bottom-[calc(3.5rem+env(safe-area-inset-bottom))] z-30 bg-ground flex flex-col
      md:static md:z-auto md:h-[calc(100dvh-7.5rem)] md:min-h-[32rem] md:bg-white md:border md:border-line md:rounded-xl md:overflow-hidden">
      <header className="shrink-0 min-h-12 px-1 flex items-center gap-1 bg-white border-b border-line">
        <button type="button" onClick={onExit} aria-label="กลับไปหน้ารายงาน"
          className="min-h-11 min-w-11 flex items-center justify-center rounded-lg text-ink-soft hover:bg-ground"><Icon name="back" /></button>
        <h1 className="flex-1 min-w-0 truncate font-semibold">{title}</h1>
        <button type="button" onClick={goBack} disabled={!prev || busy}
          className="min-h-11 px-3 rounded-lg text-sm text-accent disabled:text-muted disabled:opacity-60">ย้อนใบก่อน</button>
      </header>

      {slip === undefined ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-3 p-6 text-center">
          {err ? (
            <>
              <p role="alert" className="text-sm text-danger-ink">โหลดใบที่จะตรวจไม่ได้: {err}</p>
              <button type="button" onClick={() => call()} className="min-h-11 px-4 rounded-lg border border-line bg-white text-sm">ลองใหม่</button>
            </>
          ) : <p className="text-sm text-muted">กำลังโหลด…</p>}
        </div>
      ) : slip === null ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-3 p-6 text-center">
          <p className="text-lg font-semibold">{left > 0 ? 'ใบที่เหลือมีคนกำลังตรวจอยู่' : 'ตรวจครบทุกใบที่มีในสัปดาห์นี้แล้ว'}</p>
          <p className="text-sm text-muted">
            {left > 0 ? `เหลือ ${fmt(left)} ใบที่เครื่องอื่นถืออยู่ ถ้าไม่มีใครตรวจต่อ ใบจะกลับมาให้ตรวจใน 20 นาที`
              : `ตรวจแล้ว ${fmt(progress.checked)} ใบ · ดูรูปไม่ได้ ${fmt(progress.no_picture)} ใบ`}
          </p>
          <button type="button" onClick={onExit} className="min-h-12 px-5 rounded-xl bg-accent hover:bg-accent-hover text-white font-semibold">ดูรายงาน</button>
        </div>
      ) : (
        <div className="flex-1 min-h-0 flex flex-col lg:flex-row">
          {/* key: a fresh element per slip, so the last slip's picture never sits above this slip's values */}
          <div className="basis-[52%] grow-0 shrink-0 min-h-0 lg:basis-0 lg:grow lg:shrink">
            <SlipPicture key={slip.trip_id} pictures={slip.pictures} onState={onPicture} />
          </div>
          <div className="flex-1 min-h-0 flex flex-col bg-white border-t border-line lg:flex-none lg:w-[27rem] lg:border-t-0 lg:border-l">
            <ul ref={list} aria-label="ค่าที่ AI อ่านได้" className="flex-1 min-h-0 overflow-auto overscroll-contain">
              {fields.map((f) => (
                <FactRow key={`${slip.trip_id}:${f.key}`} field={f} shown={slip.shown[f.key]} draft={draft[f.key] || SAME}
                  onChange={(next) => setDraft((d) => ({ ...d, [f.key]: next }))} />
              ))}
            </ul>
            <div className="shrink-0 border-t border-line p-3 flex flex-col gap-2">
              {err ? <p role="alert" className="text-sm rounded-lg bg-danger-bg text-danger-ink px-3 py-2">{err}</p>
                : pic === 'bad' ? <p className="text-sm text-danger-ink">โหลดรูปไม่ได้ กด ดูรูปไม่ได้ เพื่อข้ามใบนี้ ระบบจะนับไว้ในรายงาน</p>
                  : !seen ? <p className="text-sm text-muted">{slow ? 'รูปโหลดช้า รอต่อได้ หรือกด ดูรูปไม่ได้ เพื่อข้ามใบนี้' : 'รอรูปโหลดก่อน จึงจะกดยืนยันได้'}</p>
                    : waiting > 0 ? <p className="text-sm text-warn-ink">ยังมี {fmt(waiting)} ช่องที่ต้องใส่ค่าที่เห็นในรูป หรือกด ไม่มีในรูป</p>
                      : null}
              <div className="flex gap-2">
                <button type="button" onClick={giveUp} disabled={!canGiveUp}
                  className="min-h-12 px-3 rounded-xl border border-line bg-white text-sm disabled:opacity-40">ดูรูปไม่ได้</button>
                <button type="button" onClick={save} disabled={!canSave}
                  className="flex-1 min-h-12 px-3 rounded-xl bg-accent hover:bg-accent-hover text-white text-base font-semibold disabled:opacity-40">
                  {changed === 0 ? 'ตรงทุกช่อง · ถัดไป' : `บันทึก (แก้ ${fmt(changed)} ช่อง) · ถัดไป`}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default function AnswerKey() {
  const [week, setWeek] = useState('')
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [checking, setChecking] = useState(false)

  const load = useCallback((w) => {
    setErr('')
    api.answerKeyReport(w).then(setData).catch((e) => setErr(e.message))
  }, [])
  useEffect(() => { load(week) }, [week, load])

  if (err && !data) return <p role="alert" className="text-sm text-danger-ink">โหลดไม่ได้: {err}</p>
  if (!data) return <p className="text-sm text-muted">กำลังโหลด…</p>
  if (checking) {
    return <CheckFlow week={data.week} label={data.label} fields={data.fields} onExit={() => { setChecking(false); load(data.week) }} />
  }

  const p = data.progress
  const left = p.eligible - p.checked - p.no_picture
  const oneWeek = data.week !== 'all'
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <p className="text-sm text-muted">ชุดเฉลย · วัดว่า AI อ่านสลิปถูกแค่ไหน จากใบที่คนเทียบกับรูปจริง</p>
          <h1 className="text-2xl sm:text-[28px] font-semibold tracking-tight">
            {oneWeek ? wk(data.label) : data.label}{data.closed && <span className="text-base font-normal text-muted"> · ปิดแล้ว</span>}
          </h1>
        </div>
        <label className="flex flex-col gap-1 text-sm text-ink-soft">สัปดาห์
          <select value={data.week} onChange={(e) => setWeek(e.target.value)}
            className="min-h-11 rounded-lg border border-line bg-white px-3 text-[15px] text-ink">
            {data.weeks.map((w) => <option key={w.date_from} value={w.date_from}>{wk(w.label)}{w.closed ? ' · ปิดแล้ว' : ''}</option>)}
            <option value="all">ทุกสัปดาห์</option>
          </select>
        </label>
      </div>

      <Card aria-label="ความคืบหน้า" className="p-4 sm:px-6 sm:py-5 flex flex-wrap items-center gap-x-6 gap-y-3">
        <div className="flex-1 min-w-[14rem]">
          <p className="text-lg font-semibold">ตรวจแล้ว {fmt(p.checked)} ใบ จากงานอนุมัติอัตโนมัติ {fmt(p.eligible)} ใบ</p>
          <p className="text-sm text-muted">
            ดูรูปไม่ได้ {fmt(p.no_picture)} ใบ
            {oneWeek && (left > 0 ? ` · เหลือ ${fmt(left)} ใบ หยุดตรวจเมื่อไรก็ได้ ระบบสุ่มลำดับใบให้เอง` : p.eligible > 0 ? ' · ตรวจครบแล้ว' : ' · ยังไม่มีงานที่อนุมัติอัตโนมัติ')}
          </p>
          {err && <p role="alert" className="text-sm text-danger-ink mt-1">โหลดไม่ได้: {err}</p>}
        </div>
        {oneWeek && left > 0 && (
          <button type="button" onClick={() => setChecking(true)}
            className="min-h-12 px-6 rounded-xl bg-accent hover:bg-accent-hover text-white text-base font-semibold">ตรวจต่อ</button>
        )}
      </Card>

      <KeyReport data={data} />
    </div>
  )
}
