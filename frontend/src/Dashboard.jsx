import { useEffect, useMemo, useState } from 'react'
import { api } from './api.js'

const fmt = (n) => (n ?? 0).toLocaleString('th-TH', { maximumFractionDigits: 0 })
const pct = (a, b) => (b ? Math.min(100, Math.round((a / b) * 100)) : 0)

function Bar({ done, target, tone = 'bg-emerald-500', h = 'h-2', pending = 0 }) {
  // Slips already in hand but still inside a Gemini batch are drawn in a paler shade on the end
  // of the same bar: they are work Ops has already sent, and the whole point of the screen is
  // that nobody uploads a second copy of it while it waits.
  const read = pct(done - pending, target)
  return (
    <div className={`${h} w-full rounded-full bg-slate-100 overflow-hidden flex`}>
      <div className={`h-full ${tone}`} style={{ width: `${read}%` }} />
      {pending > 0 && (
        <div className="h-full bg-amber-300" style={{ width: `${pct(done, target) - read}%` }} />
      )}
    </div>
  )
}

/** One vehicle group. Each one owes the customer its own weekly target, so a group that runs
 *  over never covers one that runs short — the number the Agent acts on is this group's own gap. */
function GroupCard({ g, active, onPick }) {
  const done = g.missing === 0
  return (
    <button onClick={() => onPick(active ? null : g.category)}
      className={`text-left w-full rounded-xl border p-4 transition ${active
        ? 'border-slate-900 bg-white shadow-sm'
        : 'border-slate-200 bg-white hover:border-slate-400'}`}>
      <div className="flex items-baseline justify-between gap-2">
        <p className="font-medium">{g.category}</p>
        <p className="text-xs text-slate-400">{g.riders + g.absent.length} คน</p>
      </div>
      <p className={`text-3xl font-semibold tabular-nums mt-1 ${done ? 'text-emerald-600' : 'text-red-600'}`}>
        {done ? 'ครบ' : fmt(g.missing)}
      </p>
      <p className="text-xs text-slate-500 mb-2">
        {done ? `ถึงเป้า ${fmt(g.target)} แล้ว` : 'งานที่ยังขาด'}
      </p>
      <Bar done={g.done} target={g.target} pending={g.unread}
        tone={done ? 'bg-emerald-500' : 'bg-amber-500'} />
      <p className="text-xs text-slate-500 mt-1.5 tabular-nums">
        {fmt(g.done)}/{fmt(g.target)} งาน ({pct(g.done, g.target)}%)
      </p>
      {/* What Ops actually needs before deciding whether to go and collect more: everything in
          this row is already in hand, so none of it should be sent a second time. */}
      <div className="mt-2 grid grid-cols-3 gap-1 text-center">
        <div className="rounded bg-emerald-50 py-1">
          <p className="text-sm font-semibold tabular-nums text-emerald-700">{fmt(g.approved)}</p>
          <p className="text-[11px] text-emerald-600">ลงไฟล์แล้ว</p>
        </div>
        <div className={`rounded py-1 ${g.waiting ? 'bg-sky-50' : 'bg-slate-50'}`}>
          <p className={`text-sm font-semibold tabular-nums ${g.waiting ? 'text-sky-700' : 'text-slate-400'}`}>{fmt(g.waiting)}</p>
          <p className={`text-[11px] ${g.waiting ? 'text-sky-600' : 'text-slate-400'}`}>รอตรวจ</p>
        </div>
        <div className={`rounded py-1 ${g.unread ? 'bg-amber-50' : 'bg-slate-50'}`}>
          <p className={`text-sm font-semibold tabular-nums ${g.unread ? 'text-amber-700' : 'text-slate-400'}`}>{fmt(g.unread)}</p>
          <p className={`text-[11px] ${g.unread ? 'text-amber-600' : 'text-slate-400'}`}>รออ่าน</p>
        </div>
      </div>
      <p className={`text-xs mt-2 ${done ? 'text-emerald-700' : 'text-slate-600'}`}>
        {done
          ? 'ได้ครบแล้ว — ไม่ต้องส่งรูปกลุ่มนี้เพิ่ม'
          : <>ยังต้องขอเพิ่มอีก <span className="font-semibold tabular-nums">{fmt(g.missing)}</span> งาน</>}
      </p>
      <p className="text-xs text-slate-400 mt-1">
        คนที่ยังขาด {g.short.length}
        {g.absent.length > 0 && <span className="text-red-500"> · สัปดาห์ก่อนทำ แต่รอบนี้ยังไม่ส่ง {g.absent.length}</span>}
      </p>
      {g.heads_needed > 0 && (
        <p className="text-xs text-red-600 mt-1.5 rounded bg-red-50 border border-red-100 px-2 py-1">
          คนไม่พอ — ต่อให้ทุกคนส่งครบก็ยังได้แค่ {fmt(g.capacity)} ต้องหาเพิ่มอีก {g.heads_needed} คน
        </p>
      )}
    </button>
  )
}

export default function Dashboard({ onOpenJob }) {
  const [comp, setComp] = useState(null)
  const [week, setWeek] = useState('')
  const [cat, setCat] = useState(null)          // null = ทุกกลุ่มรถ
  const [showAll, setShowAll] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => { api.completeness().then(setComp).catch((e) => setErr(e.message)) }, [])
  useEffect(() => { if (comp && !week && comp.weeks.length) setWeek(comp.weeks[0].week) }, [comp, week])

  const w = useMemo(() => comp?.weeks.find((x) => x.week === week) || comp?.weeks[0], [comp, week])
  const groups = useMemo(() => (w ? (cat ? w.groups.filter((g) => g.category === cat) : w.groups) : []), [w, cat])
  const short = useMemo(
    () => groups.flatMap((g) => g.short.map((r) => ({ ...r, category: g.category })))
      .sort((a, b) => b.missing - a.missing), [groups])
  const absent = useMemo(
    () => groups.flatMap((g) => g.absent.map((n) => ({ name: n, category: g.category }))), [groups])

  if (err) return <p className="text-red-600">⚠️ {err}</p>
  if (!comp || !w) return <p className="text-slate-400">กำลังโหลด...</p>

  const shown = showAll ? short : short.slice(0, 15)
  const shortUnread = short.reduce((s, r) => s + (r.unread || 0), 0)
  const totalMissing = groups.reduce((s, g) => s + g.missing, 0)
  const totalDone = groups.reduce((s, g) => s + g.done, 0)
  const totalTarget = groups.reduce((s, g) => s + g.target, 0)
  // Summing the group cards counts anyone who works both tiers twice: each card is right about
  // its own group, and 'how many riders this week' is a different question with its own answer.
  const heads = cat ? groups.reduce((s, g) => s + g.riders + g.absent.length, 0) : w.riders
  const totalUnread = groups.reduce((s, g) => s + (g.unread || 0), 0)
  const totalApproved = groups.reduce((s, g) => s + (g.approved || 0), 0)
  const totalWaiting = groups.reduce((s, g) => s + (g.waiting || 0), 0)

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        {comp.weeks.slice(0, 6).map((x) => (
          <button key={x.week} onClick={() => { setWeek(x.week); setShowAll(false) }}
            className={`rounded-full px-3 py-1.5 border ${x.week === w.week
              ? 'bg-slate-900 text-white border-slate-900'
              : 'bg-white border-slate-300 text-slate-600 hover:border-slate-400'}`}>
            {x.week}
            {x.missing > 0 && (
              <span className={x.week === w.week ? 'text-slate-300' : 'text-red-500'}> · ขาด {fmt(x.missing)}</span>
            )}
          </button>
        ))}
      </div>

      {/* the headline: how much work this week still owes */}
      <section className="bg-white rounded-xl border border-slate-200 p-5">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-sm text-slate-500">
              สัปดาห์ {w.week} <span className="text-slate-400">({w.date_from} → {w.date_to})</span>
              {cat && (
                <button onClick={() => setCat(null)} className="ml-2 text-blue-600 hover:underline">
                  · เฉพาะ {cat} ✕
                </button>
              )}
            </p>
            <p className={`text-5xl font-semibold tabular-nums mt-1 ${totalMissing ? 'text-red-600' : 'text-emerald-600'}`}>
              {totalMissing ? fmt(totalMissing) : 'ครบแล้ว'}
            </p>
            <p className="text-sm text-slate-500">
              {totalMissing ? 'งานที่ยังต้องขอเพิ่ม (รวมส่วนที่ขาดของแต่ละกลุ่มรถ)' : 'ทุกกลุ่มรถครบตามเป้า'}
            </p>
          </div>
          <div className="text-right">
            <p className="text-sm text-slate-500">เก็บได้แล้ว</p>
            <p className="text-2xl font-semibold tabular-nums">
              {fmt(totalDone)} <span className="text-slate-400 text-lg">/ {fmt(totalTarget)}</span>
            </p>
            <p className="text-xs text-slate-400">
              ไรเดอร์ {fmt(heads)} คน · เป้า {fmt(comp.group_target)} งาน/กลุ่มรถ · คนละ {comp.expected} งาน
            </p>
            <p className="text-xs mt-0.5 tabular-nums">
              <span className="text-emerald-600">ลงไฟล์แล้ว {fmt(totalApproved)}</span>
              {totalWaiting > 0 && <span className="text-sky-600"> · รอตรวจ {fmt(totalWaiting)}</span>}
              {totalUnread > 0 && <span className="text-amber-600"> · รออ่านทั้งสัปดาห์ {fmt(totalUnread)}</span>}
            </p>
          </div>
        </div>
        <div className="mt-3">
          <Bar done={totalDone} target={totalTarget} h="h-3" pending={totalUnread}
            tone={totalMissing ? 'bg-amber-500' : 'bg-emerald-500'} />
        </div>
        {totalUnread > 0 && (
          <p className="text-xs text-slate-500 mt-2">
            แถบสีอ่อนท้ายบาร์คือรูปที่ส่งมาแล้วแต่ยังอ่านไม่เสร็จ นับรวมในยอด &quot;เก็บได้แล้ว&quot; เรียบร้อย — ไม่ต้องส่งซ้ำ
          </p>
        )}
      </section>

      {/* per vehicle group — this is what the Agent asks the admin for */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {w.groups.map((g) => (
          <GroupCard key={g.category} g={g} active={cat === g.category} onPick={setCat} />
        ))}
      </div>

      <section className="bg-white rounded-xl border border-slate-200 p-5">
        <div className="flex items-baseline justify-between gap-3 flex-wrap">
          <h2 className="font-semibold">
            คนที่ยังขาด
            <span className="text-sm font-normal text-slate-400"> {cat || 'ทุกกลุ่มรถ'} · เรียงจากขาดมากสุด · นับรวมทุกโฟลเดอร์ของคนเดียวกัน</span>
          </h2>
          {/* Not the week's unread total: only what belongs to the people listed below. Someone
              already past 21 is not on this list, and their slips still waiting in a batch are
              counted in the week's figure above but not here. Two different questions, and
              naming them both 'รออ่าน' made them look like the same one disagreeing with itself. */}
          <p className="text-sm text-slate-500">
            {short.length} คน
            {shortUnread > 0 && <span className="text-amber-600"> · ในนั้นเป็นรูปรออ่านของคนกลุ่มนี้ {fmt(shortUnread)}</span>}
          </p>
        </div>

        {short.length === 0 ? (
          <p className="text-sm text-emerald-700 mt-3">ไม่มีใครขาดในกลุ่มนี้</p>
        ) : (
          <div className="mt-3 space-y-1">
            {shown.map((r) => (
              <button key={r.job_id} onClick={() => onOpenJob?.(r.job_id)}
                className="w-full flex items-center gap-3 text-sm rounded-lg px-2 py-1.5 hover:bg-slate-50 text-left">
                <span className="w-32 truncate font-medium">
                  {r.driver_name}
                  {r.folders > 1 && <span className="text-xs text-slate-400 font-normal"> ·{r.folders} โฟลเดอร์</span>}
                </span>
                {!cat && <span className="w-28 text-xs text-slate-400 truncate">{r.category}</span>}
                <span className="flex-1 min-w-24"><Bar done={r.done} target={comp.expected} /></span>
                <span className="w-16 text-right tabular-nums text-slate-600"
                  title={`อ่านแล้ว ${r.read} · รออ่าน ${r.unread ?? 0}`}>
                  {r.done}/{comp.expected}
                </span>
                {/* slips already in hand but still inside a Gemini batch. Someone whose whole
                    week is sitting in a batch is not someone Ops should be chasing for photos. */}
                <span className="w-24 text-right tabular-nums text-xs">
                  {r.unread > 0
                    ? <span className="text-amber-600">รออ่าน {r.unread}</span>
                    : <span className="text-slate-300">อ่านครบ</span>}
                </span>
                <span className="w-20 text-right text-red-600 tabular-nums font-medium">ขาด {r.missing}</span>
              </button>
            ))}
            {short.length > shown.length && (
              <button onClick={() => setShowAll(true)} className="text-sm text-blue-600 hover:underline px-2 pt-1">
                ดูอีก {short.length - shown.length} คน
              </button>
            )}
          </div>
        )}

        {absent.length > 0 && (
          <div className="mt-4 pt-3 border-t border-slate-100">
            <p className="text-sm font-medium text-red-600">ยังไม่ส่งรูปเลย {absent.length} คน</p>
            <div className="flex flex-wrap gap-1.5 mt-2">
              {absent.map((a) => (
                <span key={a.name + a.category}
                  className="text-xs rounded-full border border-red-200 bg-red-50 text-red-700 px-2.5 py-1">
                  {a.name}{!cat && <span className="text-red-400"> · {a.category}</span>}
                </span>
              ))}
            </div>
          </div>
        )}
      </section>
    </div>
  )
}
