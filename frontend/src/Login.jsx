import { useState } from 'react'
import { api } from './api.js'

export default function Login({ onLoggedIn }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      await api.login(password)
      onLoggedIn()
    } catch (err) {
      setError(err.message === 'รหัสผ่านไม่ถูกต้อง' ? 'รหัสผ่านไม่ถูกต้อง ลองใหม่อีกครั้ง' : `เข้าสู่ระบบไม่ได้: ${err.message}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-6 bg-ground">
      <form onSubmit={submit} className="bg-white rounded-xl border border-line p-8 w-full max-w-sm flex flex-col gap-4">
        <div className="flex flex-col items-center gap-2 text-center">
          <span className="w-11 h-11 rounded-xl bg-ink text-white flex items-center justify-center text-lg font-semibold">R</span>
          <h1 className="font-semibold text-lg">Rider Photo OCR</h1>
          <p className="text-sm text-muted">ใส่รหัสผ่านของทีมเพื่อเข้าใช้งาน</p>
        </div>
        <label className="flex flex-col gap-1 text-sm text-ink-soft">รหัสผ่าน
          <input type="password" autoFocus autoComplete="current-password" value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="min-h-11 w-full border border-line rounded-lg px-3 text-[15px] focus:border-accent outline-none" />
        </label>
        {error && <p role="alert" className="text-sm text-danger-ink">{error}</p>}
        <button type="submit" disabled={busy || !password}
          className="min-h-11 w-full bg-accent hover:bg-accent-hover text-white rounded-lg text-[15px] font-semibold disabled:opacity-40">
          {busy ? 'กำลังเข้าสู่ระบบ…' : 'เข้าสู่ระบบ'}
        </button>
      </form>
    </div>
  )
}
