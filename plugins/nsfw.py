import time

from aiopath import AsyncPath
from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from core import missav_dl
from utils import progress_func, tools

# Dictionary untuk menyimpan link berdasarkan message.id
cache = {}


# Fungsi untuk menangani perintah /missav
@Client.on_message(filters.command("missav"))
async def missav_cmd(client: Client, message):
    if len(message.command) < 2:
        return await message.reply("Silakan pergi ke MissAV dan salin tautannya!")

    link = message.command[1]

    # Membuat tombol pilihan kualitas
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("High", callback_data="quality_high")],
            [InlineKeyboardButton("Medium", callback_data="quality_medium")],
            [InlineKeyboardButton("Lowest", callback_data="quality_lowest")],
        ]
    )

    # Menyimpan link di dalam cache dengan menggunakan message_id sebagai key
    cache[message.id] = link

    await message.reply(
        "Pilih kualitas video yang diinginkan:", reply_markup=keyboard, quote=True
    )


# Fungsi untuk menangani pemilihan kualitas menggunakan filters.regex
@Client.on_callback_query(filters.regex(r"quality_(high|medium|lowest)"))
async def quality_callback(client: Client, callback_query: CallbackQuery):
    # Mendapatkan kualitas dari callback_data
    quality = callback_query.data.split("_")[1]

    # Mengambil link dari cache berdasarkan message_id
    link = cache.get(callback_query.message.reply_to_message.id)
    if not link:
        return await callback_query.answer("Tautan tidak ditemukan!", show_alert=True)

    # Proses pengunduhan video berdasarkan kualitas yang dipilih
    process = await callback_query.message.edit("Memproses unduhan...")
    success, path = await missav_dl(link, quality=quality, msg=process)
    if success:
        start_time = time.time()
        path = AsyncPath(path)
        thumbnail = AsyncPath(await tools.generate_thumbnail(path))

        caption = f"`{path.name}`\nDiminta oleh: {callback_query.from_user.mention}"

        await callback_query.message.reply_video(
            path,
            caption=caption,
            thumb=thumbnail,
            progress=progress_func,
            progress_args=(process, start_time, "upload", path.name),
        )

        await path.unlink()
        await thumbnail.unlink()

    await process.delete()
