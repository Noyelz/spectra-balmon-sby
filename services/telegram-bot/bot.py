import io
import os
import sys
import httpx
from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# 1. Membaca Environment Variables dari .env (Rule #8)
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CORE_WEB_URL = os.getenv("CORE_WEB_URL", "http://127.0.0.1:5000")

# 2. Fail-Fast Validation (Rule #8): Crash langsung jika token kosong
if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN.strip() == "" or "token" in TELEGRAM_BOT_TOKEN.lower():
    print("❌ [FATAL ERROR] TELEGRAM_BOT_TOKEN belum diatur dengan benar di file .env!")
    print("👉 Pastikan Anda telah mengisi TELEGRAM_BOT_TOKEN di /root/balmon-sfr/.env")
    sys.exit(1)

# Penyimpanan State Session Sementara User (Memory Buffer)
USER_SESSIONS = {}


def get_user_session(user_id):
    if user_id not in USER_SESSIONS:
        USER_SESSIONS[user_id] = {
            "step": "IDLE",
            "stasiun_id": None,
            "stasiun_name": None,
            "frekuensi": None,
            "kota": None,
            "obw_fmspa": None,
            "obw_img": None,
            "harmonisa_fmspa": None,
            "harmonisa_img": None,
            "deviasi_fmspa": None,
            "deviasi_img": None,
            "history_page": 1,
        }
    return USER_SESSIONS[user_id]


# 1. MENU UTAMA (/balmon & /start)


async def balmon_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler /balmon & /start: Menampilkan Menu Interaktif Utama"""
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name if update.effective_user else "Petugas"
    session = get_user_session(user_id)
    session["step"] = "MAIN_MENU"

    keyboard = [
        [InlineKeyboardButton("Upload File Pengukuran", callback_data="menu_upload")],
        [InlineKeyboardButton("Riwayat & Unduh Laporan", callback_data="menu_riwayat_1")],
        [InlineKeyboardButton("Stop / Batal", callback_data="menu_stop")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    pesan = (
        f"Halo, **{user_name}**!\n\n"
        "**Sistem Monitoring Spektrum Frekuensi Radio (Balmon SFR)**\n"
        "Silakan pilih menu operasional di bawah ini:"
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(pesan, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(pesan, reply_markup=reply_markup, parse_mode="Markdown")



# 2. ALUR PILIH KOTA & STASIUN RADIO (DINAMIS DARI DB)


async def handle_pilih_kota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mengambil daftar kota unik dari database PostgreSQL via Core-Web"""
    query = update.callback_query
    await query.answer()

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{CORE_WEB_URL}/api/internal/telegram/kota")

        if resp.status_code != 200:
            await query.edit_message_text("Gagal mengambil daftar kota dari Core-Web.")
            return

        kota_list = resp.json().get("data", [])
        if not kota_list:
            await query.edit_message_text("Belum ada data stasiun radio di database.")
            return

        keyboard = []
        for kota in kota_list:
            keyboard.append([InlineKeyboardButton(f"{kota}", callback_data=f"kota:{kota}")])
        keyboard.append([InlineKeyboardButton("Kembali ke Menu Utama", callback_data="menu_main")])

        await query.edit_message_text(
            "**PILIH KOTA / KABUPATEN:**\nPilih wilayah stasiun radio yang diukur:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )
    except Exception as e:
        await query.edit_message_text(f"Terjadi kesalahan koneksi: `{e}`", parse_mode="Markdown")


async def handle_pilih_stasiun(update: Update, context: ContextTypes.DEFAULT_TYPE, kota: str):
    """Mengambil daftar stasiun di kota terpilih dari database PostgreSQL via Core-Web"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    session = get_user_session(user_id)
    session["kota"] = kota

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{CORE_WEB_URL}/api/internal/telegram/stasiun-by-kota", params={"kota": kota})

        if resp.status_code != 200:
            await query.edit_message_text(f"Gagal mengambil stasiun untuk {kota}.")
            return

        stasiun_list = resp.json().get("data", [])
        if not stasiun_list:
            await query.edit_message_text(f"Tidak ada stasiun terdaftar di {kota}.")
            return

        keyboard = []
        for s in stasiun_list:
            btn_text = f"{s['nama_stasiun']} ({s['frekuensi_mhz']} MHz)"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"stasiun:{s['id']}:{s['nama_stasiun']}:{s['frekuensi_mhz']}")])
        keyboard.append([InlineKeyboardButton("Ganti Kota", callback_data="menu_upload")])

        await query.edit_message_text(
            f"**PILIH STASIUN RADIO ({kota}):**\nPilih stasiun yang hasil pengukurannya akan diunggah:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )
    except Exception as e:
        await query.edit_message_text(f"Terjadi kesalahan koneksi: `{e}`", parse_mode="Markdown")


# 3. alur panduan upload 6 file


async def start_upload_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, stasiun_id: str, stasiun_name: str, frekuensi: str):
    """Memulai alur penerimaan 6 file pengukuran (OBW -> Harmonisa -> Deviasi)"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    session = get_user_session(user_id)

    session["stasiun_id"] = stasiun_id
    session["stasiun_name"] = stasiun_name
    session["frekuensi"] = frekuensi
    session["step"] = "UPLOAD_OBW"
    # Reset file buffer
    session["obw_fmspa"] = None
    session["obw_img"] = None
    session["harmonisa_fmspa"] = None
    session["harmonisa_img"] = None
    session["deviasi_fmspa"] = None
    session["deviasi_img"] = None

    keyboard = [[InlineKeyboardButton("Batal & Kembali", callback_data="menu_main")]]

    pesan = (
        f"**Target Stasiun:** {stasiun_name} ({frekuensi} MHz)\n"
        f"**Wilayah:** {session['kota']}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "**LANGKAH 1 DARI 3: PENGUKURAN OBW (BANDWIDTH)**\n"
        "Silakan kirimkan **2 File OBW**:\n"
        "1. File parameter data (`.fmspa`)\n"
        "2. File gambar grafik spectrum (`.png` / `.jpg`)\n\n"
        "*(Anda bebas mengirim file `.fmspa` dulu atau gambar dulu, sistem otomatis mendeteksinya)*"
    )
    await query.edit_message_text(pesan, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


async def handle_incoming_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menerima dan memilah file yang dikirimkan oleh pengguna secara otomatis"""
    user_id = update.effective_user.id
    session = get_user_session(user_id)
    step = session.get("step")

    if step not in ["UPLOAD_OBW", "UPLOAD_HARMONISA", "UPLOAD_DEVIAISI"]:
        # Jika user kirim file saat tidak dalam mode upload
        return

    file_bytes = None
    filename = ""

    # Cek apakah berupa Dokumen (.fmspa atau gambar dokumen)
    if update.message.document:
        doc = update.message.document
        filename = doc.file_name or "file.dat"
        file_obj = await context.bot.get_file(doc.file_id)
        f_bytearray = await file_obj.download_as_bytearray()
        file_bytes = bytes(f_bytearray)

    # Cek apakah berupa Foto Telegram
    elif update.message.photo:
        photo = update.message.photo[-1] # Resolusi tertinggi
        filename = f"photo_{user_id}.png"
        file_obj = await context.bot.get_file(photo.file_id)
        f_bytearray = await file_obj.download_as_bytearray()
        file_bytes = bytes(f_bytearray)
    else:
        await update.message.reply_text("Mohon kirimkan file dalam bentuk Dokumen (`.fmspa`) atau Gambar (`.png`/`.jpg`).")
        return

    # Logika Cerdas Memilah File (.fmspa vs Gambar)
    is_fmspa = filename.lower().endswith(".fmspa") or filename.lower().endswith(".xml")
    is_img = filename.lower().endswith((".png", ".jpg", ".jpeg")) or update.message.photo is not None

    if step == "UPLOAD_OBW":
        if is_fmspa:
            session["obw_fmspa"] = (filename, file_bytes)
            await update.message.reply_text(f"Diterima: File OBW Data `{filename}`")
        elif is_img:
            session["obw_img"] = (filename, file_bytes)
            await update.message.reply_text(f"Diterima: Gambar Grafik OBW `{filename}`")
        else:
            await update.message.reply_text("Format file tidak dikenali sebagai `.fmspa` atau gambar.")

        if session["obw_fmspa"] and session["obw_img"]:
            session["step"] = "UPLOAD_HARMONISA"
            await update.message.reply_text(
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "**LANGKAH 2 DARI 3: PENGUKURAN HARMONISA**\n"
                "Silakan kirimkan **2 File Harmonisa**:\n"
                "1. File parameter Harmonisa (`.fmspa`)\n"
                "2. File gambar grafik Harmonisa (`.png`/`.jpg`)",
                parse_mode="Markdown"
            )

    elif step == "UPLOAD_HARMONISA":
        if is_fmspa:
            session["harmonisa_fmspa"] = (filename, file_bytes)
            await update.message.reply_text(f"Diterima: File Harmonisa Data `{filename}`")
        elif is_img:
            session["harmonisa_img"] = (filename, file_bytes)
            await update.message.reply_text(f"Diterima: Gambar Grafik Harmonisa `{filename}`")
        else:
            await update.message.reply_text("Format file tidak dikenali sebagai `.fmspa` atau gambar.")

        if session["harmonisa_fmspa"] and session["harmonisa_img"]:
            session["step"] = "UPLOAD_DEVIAISI"
            await update.message.reply_text(
                "━━━━━━━━━━━━━━━━━━━━━\n"
                "**LANGKAH 3 DARI 3: PENGUKURAN DEVIASI FM**\n"
                "Silakan kirimkan **2 File Deviasi**:\n"
                "1. File parameter Deviasi (`.fmspa`)\n"
                "2. File gambar grafik Deviasi (`.png`/`.jpg`)",
                parse_mode="Markdown"
            )

    elif step == "UPLOAD_DEVIAISI":
        if is_fmspa:
            session["deviasi_fmspa"] = (filename, file_bytes)
            await update.message.reply_text(f"Diterima: File Deviasi Data `{filename}`")
        elif is_img:
            session["deviasi_img"] = (filename, file_bytes)
            await update.message.reply_text(f"Diterima: Gambar Grafik Deviasi `{filename}`")
        else:
            await update.message.reply_text("Format file tidak dikenali sebagai `.fmspa` atau gambar.")

        if session["deviasi_fmspa"] and session["deviasi_img"]:
            session["step"] = "READY_TO_PROCESS"
            keyboard = [
                [InlineKeyboardButton("Upload & Proses Sekarang", callback_data="eksekusi_upload")],
                [InlineKeyboardButton("Upload Ulang File", callback_data=f"stasiun:{session['stasiun_id']}:{session['stasiun_name']}:{session['frekuensi']}")],
                [InlineKeyboardButton("Kembali ke Menu Utama", callback_data="menu_main")],
                [InlineKeyboardButton("Stop", callback_data="menu_stop")],
            ]
            await update.message.reply_text(
                f"**SELURUH 6 FILE LENGKAP!**\n\n"
                f"**Stasiun:** {session['stasiun_name']} ({session['frekuensi']} MHz)\n"
                f"1. OBW: `{session['obw_fmspa'][0]}` + `{session['obw_img'][0]}`\n"
                f"2. Harmonisa: `{session['harmonisa_fmspa'][0]}` + `{session['harmonisa_img'][0]}`\n"
                f"3. Deviasi: `{session['deviasi_fmspa'][0]}` + `{session['deviasi_img'][0]}`\n\n"
                "Silakan tekan tombol di bawah untuk memproses:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )


# 4. eksekusi proses upload dan trigger pipline xml dan ai harness


async def handle_eksekusi_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mengirim 6 file ke Core-Web API via multipart/form-data dan memicu antrean RQ"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    session = get_user_session(user_id)

    await query.edit_message_text(
        "⏳ **Sedang mengunggah 6 file ke MinIO Storage dan mendaftarkan ke antrean XML Parser...**\nMohon tunggu beberapa saat...",
        parse_mode="Markdown"
    )

    try:
        files = {
            "obw_fmspa": (session["obw_fmspa"][0], session["obw_fmspa"][1]),
            "obw_img": (session["obw_img"][0], session["obw_img"][1]),
            "harmonisa_fmspa": (session["harmonisa_fmspa"][0], session["harmonisa_fmspa"][1]),
            "harmonisa_img": (session["harmonisa_img"][0], session["harmonisa_img"][1]),
            "deviasi_fmspa": (session["deviasi_fmspa"][0], session["deviasi_fmspa"][1]),
            "deviasi_img": (session["deviasi_img"][0], session["deviasi_img"][1]),
        }
        data = {"stasiun_id": session["stasiun_id"]}

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"{CORE_WEB_URL}/api/internal/telegram/upload-sesi", data=data, files=files)

        if resp.status_code != 201:
            await query.edit_message_text(f"Gagal memproses sesi: {resp.text}")
            return

        res_json = resp.json()
        session_uuid = res_json.get("session_uuid")

        keyboard = [
            [
                InlineKeyboardButton("Unduh Word (.docx)", callback_data=f"dl_word:{session_uuid}"),
                InlineKeyboardButton("Unduh PDF (.pdf)", callback_data=f"dl_pdf:{session_uuid}")
            ],
            [InlineKeyboardButton("Cek Status / Teks Laporan", callback_data=f"lihat_lap:{session_uuid}")],
            [InlineKeyboardButton("Menu Utama", callback_data="menu_main")]
        ]

        await query.edit_message_text(
            f"**SESI BERHASIL DIBUAT & MASUK ANTREAN!**\n\n"
            f"**Stasiun:** {session['stasiun_name']} ({session['frekuensi']} MHz)\n"
            f"**UUID Sesi:** `{session_uuid}`\n"
            f"**Status:** XML Parser & AI Harness sedang menganalisis data secara otomatis.\n\n"
            "Silakan pilih format laporan yang ingin diunduh:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    except Exception as e:
        await query.edit_message_text(f"Terjadi kesalahan pengiriman ke server: `{e}`", parse_mode="Markdown")



# 5. riwayat pengukuran


async def handle_riwayat_paginated(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1):
    """Menampilkan 15 daftar riwayat sesi pengukuran per halaman"""
    query = update.callback_query
    if query:
        await query.answer()

    user_id = update.effective_user.id
    session = get_user_session(user_id)
    session["history_page"] = page
    session["step"] = "HISTORY_PAGINATED"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{CORE_WEB_URL}/api/internal/telegram/sesi-paginated", params={"page": page, "per_page": 15})

        if resp.status_code != 200:
            msg = "Gagal mengambil riwayat sesi dari Core-Web."
            if query: await query.edit_message_text(msg)
            else: await update.message.reply_text(msg)
            return

        res = resp.json()
        sesi_list = res.get("data", [])
        total_pages = res.get("total_pages", 1)
        total_items = res.get("total_items", 0)
        has_next = res.get("has_next", False)
        has_prev = res.get("has_prev", False)

        if not sesi_list:
            msg = "Belum ada riwayat sesi pengukuran di database."
            if query: await query.edit_message_text(msg)
            else: await update.message.reply_text(msg)
            return

        # Header teks riwayat
        lines = [
            f"**RIWAYAT SESI PENGUKURAN (Hal {page}/{total_pages} - Total {total_items} Sesi):**\n"
        ]

        # Tombol navigasi
        nav_buttons = []
        if has_prev:
            nav_buttons.append(InlineKeyboardButton("Halaman Sebelumnya", callback_data=f"menu_riwayat_{page - 1}"))
        if has_next:
            nav_buttons.append(InlineKeyboardButton("Halaman Selanjutnya", callback_data=f"menu_riwayat_{page + 1}"))

        keyboard = []
        if nav_buttons:
            keyboard.append(nav_buttons)

        # Mapping nomor urut untuk user (misal 1-15 di hal 1, 16-30 di hal 2)
        session["current_page_items"] = {}
        start_no = (page - 1) * 15 + 1

        for idx, s in enumerate(sesi_list):
            item_no = start_no + idx
            session["current_page_items"][item_no] = s["session_uuid"]
            status_tag = "Selesai AI" if s["status"] == "completed" else f"⏳ {s['status'].title()}"
            lines.append(
                f"**{item_no}. {s['nama_stasiun']}** ({s['frekuensi_mhz']} MHz)\n"
                f"   • Wilayah: {s['kab_kota']} | {s['tanggal']}\n"
                f"   • Status: {status_tag}\n"
                f"   • Unduh / Detail: `/laporan_{s['session_uuid'][:8]}` atau ketik angka `{item_no}`\n"
            )

        keyboard.append([InlineKeyboardButton("Kembali ke Menu Utama", callback_data="menu_main")])
        keyboard.append([InlineKeyboardButton("Stop", callback_data="menu_stop")])

        full_msg = "\n".join(lines)
        reply_markup = InlineKeyboardMarkup(keyboard)

        if query:
            await query.edit_message_text(full_msg, reply_markup=reply_markup, parse_mode="Markdown")
        else:
            await update.message.reply_text(full_msg, reply_markup=reply_markup, parse_mode="Markdown")

    except Exception as e:
        msg = f"Terjadi kesalahan mengambil riwayat: `{e}`"
        if query: await query.edit_message_text(msg, parse_mode="Markdown")
        else: await update.message.reply_text(msg, parse_mode="Markdown")



# 6. download langsung pdf dan docx


async def download_file_direct(update: Update, context: ContextTypes.DEFAULT_TYPE, doc_type: str, session_uuid: str):
    """Mengunduh file Word/PDF dari Core-Web dan mengirimkannya langsung sebagai dokumen Telegram"""
    query = update.callback_query
    if query:
        await query.answer()

    status_msg = await (query.message.reply_text if query else update.message.reply_text)(
        f"Sedang menghasilkan file **{doc_type.upper()}** resmi...", parse_mode="Markdown"
    )

    endpoint = f"{CORE_WEB_URL}/api/internal/telegram/export/{doc_type}/{session_uuid}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(endpoint)

        if resp.status_code != 200:
            await status_msg.edit_text(f"Gagal menghasilkan dokumen {doc_type.upper()} (Status: {resp.status_code}).")
            return

        file_bytes = resp.content
        filename = f"Laporan_Balmon_SFR_{session_uuid[:8]}.{ 'docx' if doc_type == 'word' else 'pdf' }"

        await (query.message.reply_document if query else update.message.reply_document)(
            document=io.BytesIO(file_bytes),
            filename=filename,
            caption=f"**Laporan Hasil Pengukuran Spektrum Frekuensi Radio**\nUUID Sesi: `{session_uuid}`",
            parse_mode="Markdown"
        )
        await status_msg.delete()

    except Exception as e:
        await status_msg.edit_text(f"Terjadi kesalahan saat mengunduh dokumen: `{e}`", parse_mode="Markdown")


async def tampilkan_laporan_teks(update: Update, context: ContextTypes.DEFAULT_TYPE, session_uuid: str):
    """Mengambil dan menampilkan ringkasan laporan teks audit AI"""
    query = update.callback_query
    if query:
        await query.answer()

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{CORE_WEB_URL}/api/internal/telegram/laporan/{session_uuid}")

        if resp.status_code == 404:
            msg = "Sesi pengukuran tidak ditemukan di database."
            if query: await query.message.reply_text(msg)
            else: await update.message.reply_text(msg)
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
            f"**Kesimpulan AI Auditor:**\n"
        )

        keyboard = [
            [
                InlineKeyboardButton("Unduh Word (.docx)", callback_data=f"dl_word:{session_uuid}"),
                InlineKeyboardButton("Unduh PDF (.pdf)", callback_data=f"dl_pdf:{session_uuid}")
            ],
            [InlineKeyboardButton("Menu Utama", callback_data="menu_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        full_text = header + catatan
        if len(full_text) > 3800:
            full_text = full_text[:3800] + "\n\n*(Laporan dipotong untuk Telegram, silakan unduh Word/PDF untuk versi lengkap)*"

        if query:
            await query.message.reply_text(full_text, reply_markup=reply_markup)
        else:
            await update.message.reply_text(full_text, reply_markup=reply_markup)

    except Exception as e:
        msg = f"Terjadi kesalahan mengambil laporan: `{e}`"
        if query: await query.message.reply_text(msg)
        else: await update.message.reply_text(msg)


# =========================================================
# 7. ROUTER CALLBACK QUERY & TEXT HANDLER
# =========================================================

async def handle_callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Router pusat penanganan klik tombol Inline Keyboard"""
    query = update.callback_query
    data = query.data

    if data == "menu_main":
        await balmon_command(update, context)
    elif data == "menu_upload":
        await handle_pilih_kota(update, context)
    elif data.startswith("menu_riwayat_"):
        page_num = int(data.split("_")[-1])
        await handle_riwayat_paginated(update, context, page=page_num)
    elif data.startswith("kota:"):
        kota_name = data.split("kota:")[1]
        await handle_pilih_stasiun(update, context, kota=kota_name)
    elif data.startswith("stasiun:"):
        parts = data.split(":")
        s_id = parts[1]
        s_name = parts[2]
        s_freq = parts[3]
        await start_upload_flow(update, context, s_id, s_name, s_freq)
    elif data == "eksekusi_upload":
        await handle_eksekusi_upload(update, context)
    elif data.startswith("dl_word:"):
        s_uuid = data.split("dl_word:")[1]
        await download_file_direct(update, context, doc_type="word", session_uuid=s_uuid)
    elif data.startswith("dl_pdf:"):
        s_uuid = data.split("dl_pdf:")[1]
        await download_file_direct(update, context, doc_type="pdf", session_uuid=s_uuid)
    elif data.startswith("lihat_lap:"):
        s_uuid = data.split("lihat_lap:")[1]
        await tampilkan_laporan_teks(update, context, session_uuid=s_uuid)
    elif data == "menu_stop":
        await query.answer()
        user_id = update.effective_user.id
        USER_SESSIONS.pop(user_id, None)
        await query.edit_message_text("**Sesi interaksi bot telah ditutup.**\nKetik `/balmon` kapan saja untuk membuka kembali menu utama.", parse_mode="Markdown")


async def handle_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Router pesan teks biasa (pencarian nomor riwayat atau perintah manual)"""
    user_id = update.effective_user.id
    session = get_user_session(user_id)
    text = update.message.text.strip()

    # Jika user mengetik angka saat berada di halaman riwayat
    if text.isdigit() and "current_page_items" in session:
        item_no = int(text)
        if item_no in session["current_page_items"]:
            s_uuid = session["current_page_items"][item_no]
            await tampilkan_laporan_teks(update, context, session_uuid=s_uuid)
            return

    # Jika user mengklik /laporan_<short_uuid>
    if text.startswith("/laporan_"):
        short_id = text.replace("/laporan_", "").strip()
        # Cari session_uuid yang cocok
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{CORE_WEB_URL}/api/internal/telegram/sesi-paginated?page=1&per_page=100")
            if resp.status_code == 200:
                for s in resp.json().get("data", []):
                    if s["session_uuid"].startswith(short_id):
                        await tampilkan_laporan_teks(update, context, session_uuid=s["session_uuid"])
                        return
        await update.message.reply_text("Sesi tidak ditemukan.")
        return

    # Default: Arahkan ke /balmon
    await balmon_command(update, context)


def main():
    """Fungsi utama menjalankan Telegram Bot Interaktif Balmon SFR"""
    print("Menyiapkan Balmon SFR Interactive Bot (@balmon_sby_bot)...")

    # Konfigurasi timeout koneksi yang longgar (30 detik)
    t_request = HTTPXRequest(
        connection_pool_size=8,
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0
    )
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).request(t_request).build()

    # Mendaftarkan handler
    app.add_handler(CommandHandler(["balmon", "start"], balmon_command))
    app.add_handler(CallbackQueryHandler(handle_callback_router))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, handle_incoming_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_router))

    print("Telegram Bot Balmon SFR AKTIF dengan Fitur Tombol Interaktif!")
    app.run_polling()


if __name__ == '__main__':
    main()
