import { useRef, useState } from 'react'
import { api } from './api.js'

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

  return (
    <section className="bg-white rounded-xl shadow-sm border border-slate-200 p-5 h-fit">
      <h2 className="font-semibold mb-4">งานใหม่</h2>

      <label className="block text-sm text-slate-600 mb-1">ชื่อไรเดอร์ (ตามที่จะลง Excel)</label>
      <input
        value={driverName}
        onChange={(e) => setDriverName(e.target.value)}
        placeholder="เช่น กิตติพงศ์ สินประเสริฐ"
        className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm mb-3 focus:outline-none focus:ring-2 focus:ring-blue-400"
      />

      <div className="grid grid-cols-2 gap-3 mb-3">
        <div>
          <label className="block text-sm text-slate-600 mb-1">ตั้งแต่วันที่</label>
          <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
            className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm" />
        </div>
        <div>
          <label className="block text-sm text-slate-600 mb-1">ถึงวันที่</label>
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)}
            className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm" />
        </div>
      </div>

      <div
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); addFiles(e.dataTransfer.files) }}
        className={`border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition mb-3
          ${dragging ? 'border-blue-400 bg-blue-50' : 'border-slate-300 hover:border-slate-400'}`}
      >
        <p className="text-3xl mb-1">🖼️</p>
        <p className="text-sm text-slate-600">ลากรูปมาวาง หรือคลิกเพื่อเลือก</p>
        <p className="text-xs text-slate-400 mt-1">รองรับ .jpg .png .webp เลือกทั้งโฟลเดอร์ได้</p>
        <input
          ref={inputRef} type="file" multiple accept="image/*" className="hidden"
          onChange={(e) => { addFiles(e.target.files); e.target.value = '' }}
        />
      </div>

      {files.length > 0 && (
        <div className="mb-3 text-sm">
          <div className="flex items-center justify-between mb-1">
            <span className="text-slate-600">เลือกแล้ว {files.length} รูป</span>
            <button onClick={() => setFiles([])} className="text-xs text-red-500 hover:underline">ล้างทั้งหมด</button>
          </div>
          <div className="max-h-32 overflow-y-auto border border-slate-200 rounded-lg p-2 text-xs text-slate-500 space-y-0.5">
            {files.map((f) => <div key={f.name}>{f.name}</div>)}
          </div>
        </div>
      )}

      {error && <p className="text-sm text-red-600 mb-3">⚠️ {error}</p>}

      <button
        onClick={submit}
        disabled={submitting}
        className="w-full bg-blue-600 hover:bg-blue-700 disabled:bg-slate-300 text-white rounded-lg py-2.5 text-sm font-medium transition"
      >
        {submitting ? 'กำลังอัปโหลด...' : `เริ่มอ่านข้อมูล (${files.length} รูป)`}
      </button>
    </section>
  )
}
