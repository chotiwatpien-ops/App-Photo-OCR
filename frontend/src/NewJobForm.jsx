import { useRef, useState } from 'react'
import { api } from './api.js'
import Icon from './Icon.jsx'

export default function NewJobForm({ onCreated }) {
  const [driverName, setDriverName] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [files, setFiles] = useState([])
  const [dragging, setDragging] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const inputRef = useRef(null)

  const addFiles = (list) => {
    const imgs = [...list].filter((f) => /\.(jpe?g|png|webp)$/i.test(f.name))
    setFiles((prev) => {
      const names = new Set(prev.map((f) => f.name))
      return [...prev, ...imgs.filter((f) => !names.has(f.name))]
    })
  }

  const submit = async () => {
    setError('')
    if (!driverName.trim()) return setError('กรอกชื่อไรเดอร์ก่อน')
    if (!dateFrom || !dateTo) return setError('เลือกช่วงวันที่ของสัปดาห์')
    if (dateFrom > dateTo) return setError('วันเริ่มต้นต้องมาก่อนวันสิ้นสุด')
    if (files.length === 0) return setError('ยังไม่ได้เลือกรูป')
    setSubmitting(true)
    try {
      const fd = new FormData()
      fd.append('driver_name', driverName.trim())
      fd.append('date_from', dateFrom)
      fd.append('date_to', dateTo)
      files.forEach((f) => fd.append('files', f))
      const job = await api.createJob(fd)
      onCreated(job)
    } catch (e) {
      setError(e.message)
    } finally {
      setSubmitting(false)
    }
  }

  const box = 'min-h-11 w-full border border-line rounded-lg px-3 text-[15px] bg-white focus:border-accent outline-none'
  return (
    <div className="flex flex-col gap-3">
      <label className="flex flex-col gap-1 text-sm text-ink-soft">ชื่อไรเดอร์ (ตามที่จะลงในไฟล์)
        <input value={driverName} onChange={(e) => setDriverName(e.target.value)} placeholder="เช่น กิตติพงศ์ ส." className={box} />
      </label>
      <div className="grid grid-cols-2 gap-3">
        <label className="flex flex-col gap-1 text-sm text-ink-soft">ตั้งแต่วันที่
          <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className={box} />
        </label>
        <label className="flex flex-col gap-1 text-sm text-ink-soft">ถึงวันที่
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className={box} />
        </label>
      </div>

      <button type="button"
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); addFiles(e.dataTransfer.files) }}
        className={`border-2 border-dashed rounded-xl p-6 text-center flex flex-col items-center gap-1 transition
          ${dragging ? 'border-accent bg-accent-bg' : 'border-line hover:border-ink-soft'}`}>
        <Icon name="download" size={26} className="text-ink-soft rotate-180" />
        <span className="text-sm text-ink-soft">ลากรูปมาวาง หรือกดเพื่อเลือก</span>
        <span className="text-xs text-muted">รองรับ .jpg .png .webp เลือกหลายรูปพร้อมกันได้</span>
      </button>
      <input ref={inputRef} type="file" multiple accept="image/*" className="hidden"
        onChange={(e) => { addFiles(e.target.files); e.target.value = '' }} />

      {files.length > 0 && (
        <div className="text-sm">
          <div className="flex items-center justify-between mb-1">
            <span className="text-ink-soft">เลือกแล้ว {files.length} รูป</span>
            <button onClick={() => setFiles([])} className="min-h-9 text-danger-ink hover:underline">ล้างทั้งหมด</button>
          </div>
          <div className="max-h-32 overflow-y-auto border border-line rounded-lg p-2 text-xs text-muted space-y-0.5">
            {files.map((f) => <div key={f.name}>{f.name}</div>)}
          </div>
        </div>
      )}

      {error && <p role="alert" className="text-sm text-danger-ink">{error}</p>}

      <button onClick={submit} disabled={submitting || files.length === 0}
        className="min-h-11 w-full sm:w-auto sm:self-start px-6 bg-accent hover:bg-accent-hover text-white rounded-lg text-[15px] font-semibold disabled:opacity-40">
        {submitting ? 'กำลังอัปโหลด…' : `เริ่มอ่านรูป (${files.length} รูป)`}
      </button>
    </div>
  )
}
