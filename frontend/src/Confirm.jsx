import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'

// The app's own "are you sure?" in place of the browser's confirm, alert and prompt. A browser
// dialog cannot be answered from an automation pane: it is dismissed before anyone sees it, so
// the button behind it silently did nothing there (closing a week needed window.confirm replaced
// by hand on the live page). This one is ordinary markup: buttons with names, a role, and keys.
//
//   const ask = useConfirm()
//   if (!(await ask({ text: 'ปิด WK47 จริง?\n\nรายละเอียด', confirm: 'ปิดจริง', danger: true }))) return
//   const name = await ask({ text: 'ชื่อไรเดอร์', input: { label: 'ชื่อ', value: old } })   // string, or null
//   await ask({ text: 'เปลี่ยนชื่อแล้ว', notice: true })                                    // one button
//
// The first line of `text` is the heading and the rest is the body. `danger` puts the focus on
// ยกเลิก, so a stray Enter cannot do what is hard to undo; otherwise Enter confirms, as it did.

const Ask = createContext(() => Promise.resolve(false))

export const useConfirm = () => useContext(Ask)

export function ConfirmProvider({ children }) {
  const [open, setOpen] = useState(null)
  const ask = useCallback((opts) => new Promise((resolve) => {
    setOpen((was) => {
      was?.resolve(was.input ? null : false)      // a second question cancels the first
      return { ...opts, resolve }
    })
  }), [])
  const answer = (value) => { open.resolve(value); setOpen(null) }
  return (
    <Ask.Provider value={ask}>
      {children}
      {open && <ConfirmDialog q={open} onAnswer={answer} />}
    </Ask.Provider>
  )
}

function ConfirmDialog({ q, onAnswer }) {
  const [value, setValue] = useState(q.input?.value ?? '')
  const form = useRef(null)
  const field = useRef(null)
  const yes = useRef(null)
  const no = useRef(null)
  const pressed = useRef(false)
  const cancel = useRef(null)
  cancel.current = () => onAnswer(q.input ? null : false)
  const cut = q.text.indexOf('\n')
  const head = cut < 0 ? q.text : q.text.slice(0, cut)
  const body = cut < 0 ? '' : q.text.slice(cut).trim()

  useEffect(() => {
    const opener = document.activeElement
    const first = q.input ? field.current : q.danger && !q.notice ? no.current : yes.current
    first?.focus()
    if (q.input) field.current?.select()
    // Capture on window, and nothing travels further: the page behind has single-letter
    // shortcuts on window (A approves a row in the review queue) that must not fire through
    // an open question. Typing and Space on a button are default actions and still happen.
    const onKey = (e) => {
      e.stopPropagation()
      if (e.key === 'Escape') { e.preventDefault(); cancel.current() }
      else if (e.key === 'Enter') {
        e.preventDefault()
        if (document.activeElement === no.current) cancel.current()
        else form.current?.requestSubmit()
      } else if (e.key === 'Tab') {
        const stops = [field.current, no.current, yes.current].filter(Boolean)
        const at = stops.indexOf(document.activeElement)
        e.preventDefault()
        stops[(at + (e.shiftKey ? -1 : 1) + stops.length) % stops.length]?.focus()
      }
    }
    window.addEventListener('keydown', onKey, true)
    return () => {
      window.removeEventListener('keydown', onKey, true)
      if (opener?.isConnected) opener.focus?.()
    }
  }, [q])

  const submit = (e) => {
    e.preventDefault()
    onAnswer(q.input ? value.trim() : true)
  }

  return (
    <div className="fixed inset-0 bg-ink/80 flex items-center justify-center z-[60] p-4 sm:p-6"
      // Only a press that both starts and ends on the backdrop cancels: selecting the name in the
      // text field and letting go outside the box must not. On the click, not the press, because
      // the press itself moves the focus away, after this handler has put it back on the opener.
      onMouseDown={(e) => { pressed.current = e.target === e.currentTarget }}
      onClick={(e) => { if (pressed.current && e.target === e.currentTarget) cancel.current() }}>
      <form ref={form} onSubmit={submit} role="dialog" aria-modal="true" aria-labelledby="ask-h"
        aria-describedby={body ? 'ask-b' : undefined}
        className="bg-white text-ink rounded-xl w-full max-w-md max-h-full overflow-auto p-5 sm:p-6 flex flex-col gap-3">
        <h2 id="ask-h" className="text-[17px] font-semibold break-words">{head}</h2>
        {body && <p id="ask-b" className="text-sm text-ink-soft whitespace-pre-line break-words">{body}</p>}
        {q.input && (
          <label className="flex flex-col gap-1">
            <span className="text-sm text-ink-soft">{q.input.label}</span>
            <input ref={field} value={value} onChange={(e) => setValue(e.target.value)}
              className="min-h-11 w-full rounded-lg border border-line bg-white px-3 text-[15px] outline-none focus:border-accent" />
          </label>
        )}
        <div className="flex flex-wrap justify-end gap-2.5 pt-2">
          {!q.notice && (
            <button ref={no} type="button" onClick={() => cancel.current()}
              className="min-h-11 px-4 rounded-lg border border-line bg-white hover:bg-ground text-[15px]">
              {q.cancel || 'ยกเลิก'}
            </button>
          )}
          <button ref={yes} type="submit"
            className={`min-h-11 px-5 rounded-lg text-white text-[15px] font-semibold ${
              q.danger ? 'bg-danger hover:bg-danger-ink' : 'bg-accent hover:bg-accent-hover'}`}>
            {q.confirm || 'ตกลง'}
          </button>
        </div>
      </form>
    </div>
  )
}
