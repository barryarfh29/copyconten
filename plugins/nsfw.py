#!/usr/bin/env python3
import os
import time

from aiopath import AsyncPath
from pyrogram import Client, filters
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaVideo,
)

from core import missav_dl
from utils import (
    get_video_info,
    progress_func,
    split_video_by_size,
    tools,
)

MAX_SIZE = 2097152000  # 2GB in bytes

# Dictionary to store links using message.id as key
cache = {}


@Client.on_message(filters.command("missav"))
async def missav_cmd(client: Client, message):
    if len(message.command) < 2:
        return await message.reply("Silakan pergi ke MissAV dan salin tautannya!")

    link = message.command[1]

    # Create quality selection buttons
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("High", callback_data="quality_high")],
            [InlineKeyboardButton("Medium", callback_data="quality_medium")],
            [InlineKeyboardButton("Lowest", callback_data="quality_lowest")],
        ]
    )

    # Save the link in cache using the message id
    cache[message.id] = link

    await message.reply(
        "Pilih kualitas video yang diinginkan:", reply_markup=keyboard, quote=True
    )


@Client.on_callback_query(filters.regex(r"quality_(high|medium|lowest)"))
async def quality_callback(client: Client, callback_query: CallbackQuery):
    # Get quality from callback data
    quality = callback_query.data.split("_")[1]

    # Retrieve the link from cache using the replied message id
    link = cache.get(callback_query.message.reply_to_message.id)
    if not link:
        return await callback_query.answer("Tautan tidak ditemukan!", show_alert=True)

    # Inform user that the download is starting
    process = await callback_query.message.edit("Memproses unduhan...")

    # Download the video using your missav_dl function
    success, path = await missav_dl(link, quality=quality, msg=process)

    if success:
        start_time = time.time()
        path = AsyncPath(path)
        file_size = os.path.getsize(str(path))

        if file_size > MAX_SIZE:
            # If file exceeds MAX_SIZE, split it into parts
            output_prefix = str(path.parent / "split_")
            split_files = await split_video_by_size(str(path), output_prefix, MAX_SIZE)

            # Build a media group; for each split part, retrieve duration and add it to the caption.
            media_group = []
            for i, file in enumerate(split_files):
                file_info = await get_video_info(file)
                seg_duration = float(file_info["format"]["duration"])
                media_group.append(
                    InputMediaVideo(
                        file,
                        caption=f"Part {i+1}\nDuration: {seg_duration:.2f} seconds",
                    )
                )
            await client.send_media_group(callback_query.message.chat.id, media_group)

            # Clean up the temporary split files
            for file in split_files:
                if os.path.exists(file):
                    os.remove(file)
        else:
            # For files within MAX_SIZE, get the video's duration and generate a thumbnail
            video_info = await get_video_info(str(path))
            duration = float(video_info["format"]["duration"])
            thumbnail_path = await tools.generate_thumbnail(str(path))
            thumbnail = AsyncPath(thumbnail_path)

            caption = (
                f"`{path.name}`\n"
                f"Duration: {duration:.2f} seconds\n"
                f"Diminta oleh: {callback_query.from_user.mention}"
            )

            await callback_query.message.reply_video(
                str(path),
                caption=caption,
                thumb=str(thumbnail),
                progress=progress_func,
                progress_args=(process, start_time, "upload", path.name),
            )

            # Cleanup the original file and thumbnail
            await path.unlink()
            await thumbnail.unlink()

    await process.delete()
