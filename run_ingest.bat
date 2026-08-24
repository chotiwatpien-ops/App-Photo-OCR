@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Rider OCR: อ่านรูปใหม่จาก Google Drive ===
python backend\ingest.py
echo.
echo เสร็จแล้ว - ผลอยู่ใน Export Pic บน Drive และตรวจได้ในแอป (start_app.bat)
pause
