import os
import sys
import httpx
from dotenv import load_dotenv
from telegram import Update
from telegram.request import HTTPXRequest
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# 1. Membaca Environment Variables dari .env (Rule #8)
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CORE_WEB_URL = os.getenv("CORE_WEB_URL", "http://127.0.0.1:5000")

# 2. Fail-Fast Validation (Rule #8): Crash langsung jika token kosong
if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN.strip() == "" or "token" in TELEGRAM_BOT_TOKEN.lower():
    print("[FATAL ERROR] TELEGRAM_BOT_TOKEN belum diatur dengan benar di file .env!")
    print("Pastikan Anda telah mengisi TELEGRAM_BOT_TOKEN=<token_asli_botfather> di /root/balmon-sfr/.env")
    sys.exit(1)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler /start: Salam pembuka dan panduan bot Balmon SFR"""
    user_name = update.effective_user.first_name if update.effective_user else "Petugas"
    pesan = (
        f"Halo, **{user_name}**!\n\n"
        "**Sistem Monitoring Spektrum Frekuensi Radio (Balmon SFR)**\n"
        "Bot ini terintegrasi langsung dengan Core Web Dashboard dan Sistem AI Auditor Balmon.\n\n"
        "**Daftar Perintah yang Tersedia:**\n"
        "• `/cek <frekuensi/nama>` — Cari stasiun radio (misal: `/cek 97.0` atau `/cek Mitra`)\n"
        "• `/terbaru` — Cek 5 sesi pengukuran lapangan terbaru\n"
        "• `/laporan <uuid>` — Unduh ringkasan Laporan Audit AI\n"
        "• `/help` — Bantuan & informasi perintah\n\n"
        "*Tips: Anda juga bisa langsung mengetik frekuensi (contoh: `97.0`) atau nama stasiun.*"
    )
    await update.message.reply_text(pesan, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler /help: Bantuan perintah"""
    pesan = (
        "**PANDUAN PENGGUNAAN BOT BALMON SFR**\n\n"
        "**Pencarian Stasiun Radio:**\n"
        "`/cek 97.0` atau `/cek Mitra FM`\n\n"
        "**Melihat Riwayat Pengukuran Lapangan:**\n"
        "`/terbaru`\n\n"
        "**Melihat Hasil Audit AI:**\n"
        "`/laporan <id_sesi>`\n\n"
        "*Sistem Single Source of Truth Balmon SFR Microservices.*"
    )
    await update.message.reply_text(pesan, parse_mode="Markdown")


async def cek_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler /cek: Mencari stasiun radio ke Core-Web API"""
    if not context.args:
        await update.message.reply_text("Mohon sertakan nama atau frekuensi.\nContoh: `/cek 97.0` atau `/cek Mitra`", parse_mode="Markdown")
        return

    query = " ".join(context.args).strip()
    await proses_pencarian_stasiun(update, query)


async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler pesan teks biasa (otomatis mencari stasiun)"""
    text = update.message.text.strip()
    if text.startswith("/"):
        return
    await proses_pencarian_stasiun(update, text)


async def proses_pencarian_stasiun(update: Update, query: str):
    """Mengirim request HTTP ke Core-Web API internal (Rule #5) untuk mencari stasiun"""
    await update.message.reply_text(f"🔍 Mencari data stasiun untuk: *{query}*...", parse_mode="Markdown")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{CORE_WEB_URL}/api/internal/telegram/stasiun", params={"q": query})

        if resp.status_code != 200:
            await update.message.reply_text(f"Gagal mengambil data dari Core-Web (Status: {resp.status_code}).")
            return

        result = resp.json()
        stasiun_list = result.get("data", [])

        if not stasiun_list:
            await update.message.reply_text(f"Tidak ditemukan data stasiun untuk kata kunci *'{query}'*.", parse_mode="Markdown")
            return

        for s in stasiun_list:
            hasil = s.get("hasil_terakhir")
            hasil_text = (
                f"   • Tgl Ukur: {hasil['tanggal']}\n"
                f"   • Level: `{hasil['level_dbm']}` dBm\n"
                f"   • OBW: `{hasil['obw_khz']}` kHz\n"
                f"   • Deviasi: `{hasil['deviasi_khz']}` kHz\n"
            ) if hasil else "   • *Belum ada riwayat pengukuran lapangan.*\n"

            pesan = (
                f"**{s['nama_stasiun']}** ({s['frekuensi_mhz']} MHz)\n"
                f"Penyelenggara: {s['penyelenggara']}\n"
                f"Wilayah: {s['kab_kota']} | Kanal: {s['kanal']}\n"
                f"**Data Pengukuran Terakhir:**\n"
                f"{hasil_text}"
            )
            await update.message.reply_text(pesan, parse_mode="Markdown")

    except Exception as e:
        await update.message.reply_text(f"Terjadi kesalahan koneksi ke server Core-Web: `{e}`", parse_mode="Markdown")


async def terbaru_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler /terbaru: Menampilkan 5 sesi pengukuran terbaru dari Core-Web"""
    await update.message.reply_text("Mengambil riwayat sesi pengukuran terbaru...")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{CORE_WEB_URL}/api/internal/telegram/sesi-terbaru")

        if resp.status_code != 200:
            await update.message.reply_text(f"Gagal mengambil sesi dari Core-Web (Status: {resp.status_code}).")
            return

        sesi_list = resp.json().get("data", [])
        if not sesi_list:
            await update.message.reply_text("Belum ada riwayat sesi pengukuran.")
            return

        pesan_list = ["**5 SESI PENGUKURAN TERBARU:**\n"]
        for idx, s in enumerate(sesi_list, start=1):
            status_icon = "Selesai AI" if s["status"] == "completed" else f"{s['status'].title()}"
            pesan_list.append(
                f"**{idx}. {s['nama_stasiun']}** ({s['frekuensi_mhz']} MHz)\n"
                f"   • Lokasi: {s['kab_kota']}\n"
                f"   • Waktu: {s['tanggal']}\n"
                f"   • Status: {status_icon}\n"
                f"   • Cek Laporan: `/laporan {s['session_uuid']}`\n"
            )

        await update.message.reply_text("\n".join(pesan_list), parse_mode="Markdown")

    except Exception as e:
        await update.message.reply_text(f"Terjadi kesalahan koneksi ke server Core-Web: `{e}`", parse_mode="Markdown")


async def laporan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler /laporan <uuid>: Mengambil teks laporan audit AI dari Core-Web"""
    if not context.args:
        await update.message.reply_text("Mohon sertakan ID Sesi.\nContoh: `/laporan 10d755c5-2dd9-4ab9-8393-a8d0d842dfe4`", parse_mode="Markdown")
        return

    session_uuid = context.args[0].strip()
    await update.message.reply_text(f"Mengambil laporan audit AI untuk sesi: `{session_uuid}`...", parse_mode="Markdown")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{CORE_WEB_URL}/api/internal/telegram/laporan/{session_uuid}")

        if resp.status_code == 404:
            await update.message.reply_text("Sesi pengukuran tidak ditemukan di database.")
            return
        elif resp.status_code != 200:
            await update.message.reply_text(f"Gagal mengambil laporan (Status: {resp.status_code}).")
            return

        data = resp.json()
        stasiun = data.get("stasiun", {})
        pengukuran = data.get("pengukuran") or {}
        catatan = data.get("catatan_llm", "")

        header = (
            f"**LAPORAN AUDIT TEKNIS SPECTRUM**\n\n"
            f"**Stasiun:** {stasiun.get('nama_stasiun')} ({stasiun.get('frekuensi_mhz')} MHz)\n"
            f"**Penyelenggara:** {stasiun.get('penyelenggara')}\n"
            f"**Lokasi:** {stasiun.get('kab_kota')}\n"
            f"**Hasil Ukur:** Level: `{pengukuran.get('level_dbm')}` dBm | OBW: `{pengukuran.get('obw_khz')}` kHz | Dev: `{pengukuran.get('deviasi_khz')}` kHz\n\n"
            f"**Kesimpulan & Referensi Regulasi AI:**\n"
        )

        full_text = header + catatan

        # Batas maksimal panjang pesan Telegram adalah 4096 karakter
        if len(full_text) > 4000:
            for i in range(0, len(full_text), 4000):
                await update.message.reply_text(full_text[i:i+4000])
        else:
            await update.message.reply_text(full_text)

    except Exception as e:
        await update.message.reply_text(f"Terjadi kesalahan koneksi ke server Core-Web: `{e}`", parse_mode="Markdown")


def main():
    """Fungsi utama untuk menyalakan Telegram Bot"""
    print("🤖 Menyiapkan Balmon SFR Telegram Bot (@balmon_sby_bot)...")

    # Konfigurasi timeout yang lebih longgar (30 detik) agar koneksi stabil
    t_request = HTTPXRequest(
        connection_pool_size=8,
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0
    )
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).request(t_request).build()

    # Mendaftarkan semua perintah bot
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("cek", cek_command))
    app.add_handler(CommandHandler("terbaru", terbaru_command))
    app.add_handler(CommandHandler("laporan", laporan_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))

    print("🚀 Telegram Bot Balmon SFR AKTIF dan siap menerima pesan dari petugas!")
    app.run_polling()



if __name__ == '__main__':
    main()
