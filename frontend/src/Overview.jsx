import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import Icon from './Icon.jsx'

// ภาพรวม — the first screen (redesign 2026-10, approved on the design canvas). It answers, in
// order: what do I have to do now, how far is each Service Type, is the reading working, who can
// take more work, and did the latest albums repeat anything. Counted the way the customer counts:
// by Service Type, not by folder (overview.py).

const fmt = (n) => (n ?? 0).toLocaleString('th-TH')
const TH_MONTHS = ['ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.', 'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.']
const day = (iso) => { const d = new Date(`${iso}T00:00:00`); return `${d.getDate()} ${TH_MONTHS[d.getMonth()]}` }
const range = (a, b) => `${day(a)} – ${day(b)} ${new Date(`${b}T00:00:00`).getFullYear()}`
const wk = (label) => (label || '').replace(/^\d{4}-W/, 'WK')
const clock = (s) => (s ? new Date(s).toLocaleTimeString('th-TH', { hour: '2-digit', minute: '2-digit' }) : '–')
const ago = (s) => {
  if (!s) return ''
  const m = Math.round((Date.now() - new Date(s).getTime()) / 60000)
  return m < 1 ? 'เมื่อสักครู่' : m < 60 ? `${m} นาทีก่อน` : `${Math.round(m / 60)} ชม.ก่อน`
}
const when = (s) => {
  if (!s) return ''
  const d = new Date(String(s).replace(' ', 'T'))
  const today = new Date()
  const y = new Date(today); y.setDate(today.getDate() - 1)
  const t = d.toLocaleTimeString('th-TH', { hour: '2-digit', minute: '2-digit' })
  if (d.toDateString() === today.toDateString()) return `วันนี้ ${t}`
  if (d.toDateString() === y.toDateString()) return `เมื่อวาน ${t}`
  return `${d.getDate()} ${TH_MONTHS[d.getMonth()]} ${t}`
}
const TONE = {
  danger: 'bg-danger-bg text-danger-ink', warn: 'bg-warn-bg text-warn-ink',
  wait: 'bg-wait-bg text-wait-ink', ok: 'bg-ok-bg text-ok-ink',
}

function Card({ children, className = '', ...rest }) {
  return <section className={`bg-white border border-line rounded-xl ${className}`} {...rest}>{children}</section>
}

function Todos({ todos, onAct }) {
  return (
    <Card aria-labelledby="todo-h" className="p-4 sm:px-6 sm:py-5">
      <h2 id="todo-h" className="text-[17px] font-semibold">ต้องทำต่อ</h2>
      <p className="text-sm text-muted mb-2">เรียงจากเรื่องที่ควรทำก่อน</p>
      <ul>
        {todos.map((t) => (
          <li key={t.kind} className="flex items-center gap-4 py-3.5 border-t border-line-soft">
            <span className={`w-9 h-9 shrink-0 rounded-[10px] flex items-center justify-center font-semibold text-[15px] ${TONE[t.tone]}`}>{t.mark}</span>
            <div className="flex-1 min-w-0">
              <p className="font-medium">{t.title}</p>
              <p className="text-sm text-muted">{t.sub}</p>
            </div>
            {t.action && (
              <button onClick={() => onAct(t.go)}
                className="shrink-0 min-h-10 px-4 rounded-lg border border-line hover:bg-ground text-sm font-medium flex items-center gap-1">
                <span className="hidden sm:inline">{t.action}</span>
                <Icon name="chevron" size={18} className="sm:hidden" label={t.action} />
              </button>
            )}
          </li>
        ))}
      </ul>
    </Card>
  )
}

function Reading({ r, onRead, busy, note }) {
  return (
    <Card aria-labelledby="read-h" className="p-4 sm:px-6 sm:py-5 flex flex-col gap-3">
      <h2 id="read-h" className="text-[17px] font-semibold">การอ่านรูป</h2>
      <dl className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-2.5 text-sm">
        <dt className="text-muted">อ่านรอบล่าสุด</dt>
        <dd>{r.running ? 'กำลังอ่านอยู่' : r.last_finished ? `${clock(r.last_finished)} · ${ago(r.last_finished)}` : 'ยังไม่เคยอ่าน'}</dd>
        <dt className="text-muted">รอบถัดไป</dt><dd>ประมาณ {r.next}</dd>
        <dt className="text-muted">รอผลอ่าน</dt><dd>{fmt(r.total)} รูป</dd>
        <dt className="text-muted">อัลบั้มใหม่วันนี้</dt><dd>{fmt(r.albums_today)} อัลบั้ม</dd>
      </dl>
      <p className="text-sm text-muted bg-ground rounded-lg px-3 py-2.5">รูปที่วางใน Drive จะถูกอ่านเองทุก 3 ชั่วโมง ไม่ต้องกดอะไร</p>
      {note && <p className="text-sm text-ink-soft">{note}</p>}
      <button onClick={onRead} disabled={busy || r.running}
        className="mt-auto min-h-10 rounded-lg border border-line hover:bg-ground text-sm disabled:opacity-50">
        อ่านรูปที่วางใหม่เดี๋ยวนี้
      </button>
    </Card>
  )
}

function Group({ g, target }) {
  const pct = (n) => `${Math.min(n, target) / target * 100}%`
  const full = g.short === 0
  return (
    <article className="bg-white border border-line rounded-xl p-4 sm:px-6 sm:py-5 flex flex-col gap-3.5">
      <div className="flex justify-between items-start gap-2">
        <div>
          <h3 className="font-semibold">{g.service}</h3>
          <p className="text-sm text-muted">{g.service.endsWith('Car') ? 'รถยนต์ · 4W' : 'มอเตอร์ไซค์ · 2W'}</p>
        </div>
        <span className={`text-sm font-medium rounded-full px-2.5 py-0.5 ${full ? TONE.ok : TONE.warn}`}>
          {full ? 'ครบเป้า' : `ยังขาด ${fmt(g.short)}`}
        </span>
      </div>
      <p className="text-[30px] leading-none font-semibold tracking-tight">{fmt(g.have)}<span className="text-base font-normal text-muted"> / {fmt(target)}</span></p>
      <div aria-hidden="true" className="h-2.5 rounded-full bg-line-soft flex overflow-hidden">
        <span className="bg-ok" style={{ width: pct(g.filed) }} />
        <span className="bg-warn" style={{ width: pct(Math.max(0, Math.min(g.review, target - g.filed))) }} />
        <span className="bg-wait" style={{ width: pct(Math.max(0, Math.min(g.reading, target - g.filed - g.review))) }} />
      </div>
      <dl className="grid grid-cols-3 gap-2 text-sm">
        {[['ลงไฟล์แล้ว', g.filed, 'bg-ok'], ['รอตรวจ', g.review, 'bg-warn'], ['รออ่าน', g.reading, 'bg-wait']].map(([l, n, c]) => (
          <div key={l}>
            <dt className="text-muted flex items-center gap-1.5"><span className={`w-2 h-2 rounded-full ${c}`} />{l}</dt>
            <dd className="font-semibold text-[15px]">{fmt(n)}</dd>
          </div>
        ))}
      </dl>
      <p className={`pt-3 border-t border-line-soft text-sm ${full ? 'text-ink-soft' : 'text-warn-ink'}`}>
        {full
          ? (g.over ? `เกินเป้า ${fmt(g.over)} เที่ยว — ตอนปิดสัปดาห์จะยกไปสัปดาห์หน้าให้เอง` : 'ครบเป้าแล้ว')
          : `ต้องขอรูปเพิ่มอีก ${fmt(g.short)} เที่ยว`}
      </p>
    </article>
  )
}

export default function Overview({ onGo }) {
  const [week, setWeek] = useState('')
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const ridersRef = useRef(null)

  const load = useCallback((w) => api.overview(w).then((d) => { setData(d); setError('') })
    .catch((e) => setError(e.message)), [])
  useEffect(() => { load(week) }, [week, load])

  if (error && !data) {
    return (
      <div className="max-w-xl mx-auto bg-white border border-line rounded-xl p-6 text-center space-y-3">
        <p className="font-medium">โหลดภาพรวมไม่ได้</p>
        <p className="text-sm text-muted">ลองใหม่อีกครั้ง ถ้ายังไม่ได้ให้แจ้งผู้ดูแลระบบ (รายละเอียด: {error})</p>
        <button onClick={() => load(week)} className="min-h-10 px-4 rounded-lg border border-line text-sm">ลองใหม่</button>
      </div>
    )
  }
  if (!data) return <p className="text-sm text-muted">กำลังโหลด…</p>
  if (!data.week) return <p className="text-sm text-muted">ยังไม่มีงานเข้าระบบ — วางอัลบั้มรูปใน Google Drive แล้วรอรอบอ่านรูปรอบถัดไป</p>

  const act = (go) => {
    if (go === 'riders') ridersRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    else if (go) onGo(go)
  }
  const readNow = () => {
    setBusy(true); setNote('')
    api.triggerIngest().then(() => setNote('สั่งแล้ว — รูปใหม่จะขึ้นในไม่กี่นาที (ผลอ่านบางส่วนมาในรอบถัดไป)'))
      .catch((e) => setNote(`สั่งไม่สำเร็จ: ${e.message}`)).finally(() => setBusy(false))
  }
  const current = data.weeks.find((w) => w.date_from === data.week)

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm text-muted">
            {data.closed ? 'สัปดาห์ที่ปิดแล้ว' : current?.current ? 'สัปดาห์ที่กำลังเก็บงาน' : 'สัปดาห์ที่ยังไม่ปิด'}
          </p>
          <h1 className="text-2xl sm:text-[28px] font-semibold tracking-tight">
            {wk(data.label)} <span className="font-normal text-ink-soft text-base sm:text-xl">· {range(data.week, data.week_to)}</span>
          </h1>
        </div>
        <div role="group" aria-label="เลือกสัปดาห์" className="flex gap-2 overflow-x-auto">
          {[...data.weeks].reverse().map((w) => {
            const on = w.date_from === data.week
            const tag = w.closed ? 'ปิดแล้ว' : w.current ? (data.days_left ? `เหลือ ${data.days_left} วัน` : 'วันสุดท้าย') : 'ยังไม่ปิด'
            return (
              <button key={w.date_from} onClick={() => setWeek(w.date_from)} aria-pressed={on}
                className={`shrink-0 min-h-10 px-4 rounded-full text-sm border ${on ? 'bg-ink text-white border-ink' : 'bg-white text-ink-soft border-line'}`}>
                {wk(w.label)} · {tag}
              </button>
            )
          })}
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-[2fr_1fr]">
        <Todos todos={data.todos} onAct={act} />
        <Reading r={data.reading} onRead={readNow} busy={busy} note={note} />
      </div>

      <section aria-labelledby="grp-h">
        <div className="flex flex-wrap items-baseline justify-between gap-2 mb-3">
          <h2 id="grp-h" className="text-[17px] font-semibold">ความคืบหน้าตาม Service Type</h2>
          <p className="text-sm text-muted">เป้า {fmt(data.target)} เที่ยวต่อ Service Type</p>
        </div>
        <div className="grid gap-5 md:grid-cols-3">
          {data.groups.map((g) => <Group key={g.service} g={g} target={data.target} />)}
        </div>
      </section>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card aria-labelledby="riders-h" className="p-4 sm:px-6 sm:py-5">
          <div ref={ridersRef} className="scroll-mt-4" />
          <h2 id="riders-h" className="text-[17px] font-semibold">ไรเดอร์ที่ยังรับงานได้</h2>
          <p className="text-sm text-muted mb-2">ใช้ขอรูปเพิ่มจากกลุ่มที่ยังขาด · คนละไม่เกินโควตาของกลุ่ม</p>
          {data.riders.length === 0 ? (
            <p className="text-sm text-muted py-3">{data.groups.every((g) => !g.short) ? 'ทุกกลุ่มครบเป้าแล้ว' : 'ไรเดอร์ที่มีอยู่รับครบโควตาแล้ว'}</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-muted">
                    <th scope="col" className="font-normal py-2 border-b border-line-soft">ไรเดอร์</th>
                    <th scope="col" className="font-normal py-2 border-b border-line-soft">Service Type</th>
                    <th scope="col" className="font-normal py-2 border-b border-line-soft text-right">มีแล้ว</th>
                    <th scope="col" className="font-normal py-2 border-b border-line-soft text-right">รับได้อีก</th>
                  </tr>
                </thead>
                <tbody>
                  {data.riders.map((r) => (
                    <tr key={`${r.name}-${r.service}`}>
                      <td className="py-2.5 border-b border-line-soft">{r.name}</td>
                      <td className="py-2.5 border-b border-line-soft text-ink-soft">{r.service}</td>
                      <td className="py-2.5 border-b border-line-soft text-right">{r.have}/{r.cap}</td>
                      <td className="py-2.5 border-b border-line-soft text-right font-semibold">{r.room}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {data.riders_total > data.riders.length && (
                <p className="text-sm text-muted pt-2">และอีก {fmt(data.riders_total - data.riders.length)} คน</p>
              )}
            </div>
          )}
        </Card>

        <Card aria-labelledby="alb-h" className="p-4 sm:px-6 sm:py-5">
          <div className="flex items-baseline justify-between gap-2">
            <h2 id="alb-h" className="text-[17px] font-semibold">งานซ้ำ · อัลบั้มที่วางล่าสุด</h2>
            <button onClick={() => onGo('dups')} className="text-sm text-accent hover:underline">ดูงานซ้ำทั้งสัปดาห์</button>
          </div>
          <p className="text-sm text-muted mb-1">
            {data.albums_total ? `${fmt(data.albums_total)} อัลบั้มในสัปดาห์นี้ · ซ้ำ ${fmt(data.albums_dup)}` : 'ยังไม่มีอัลบั้มในสัปดาห์นี้'} · นับซ้ำเฉพาะในสัปดาห์เดียวกัน
          </p>
          <ul>
            {data.albums.map((a) => {
              const dup = a.status === 'ซ้ำ'
              return (
                <li key={a.album} className="flex items-center gap-3 py-2.5 border-b border-line-soft last:border-b-0">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium break-words">{a.album}</p>
                    <p className="text-sm text-muted">
                      {when(a.first)} · อ่านแล้ว {fmt(a.read)}{a.waiting ? ` · รออ่าน ${fmt(a.waiting)}` : ''}
                    </p>
                  </div>
                  <span className={`shrink-0 text-sm font-medium rounded-full px-2.5 py-0.5 ${dup ? TONE.danger : TONE.ok}`}>
                    {dup ? `ซ้ำ ${fmt(a.dup)}` : 'ไม่ซ้ำ'}
                  </span>
                </li>
              )
            })}
          </ul>
        </Card>
      </div>
    </div>
  )
}
