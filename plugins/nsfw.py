import os
import time
from pathlib import Path

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
    format_duration,
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
            await process.edit("<pre language=Status>Splitting video...</pre>")
            # For split files, include the original file name in the output prefix.
            # For example, if original is "original.mp4", output files will be "original_splited_001.mp4", etc.
            output_prefix = str(path.parent / f"{path.stem}_splited_")
            split_files = await split_video_by_size(str(path), output_prefix, MAX_SIZE)

            media_group = (
                []
            )  # Will contain InputMediaVideo objects for final media group
            uploaded_msgs = []  # To store individual upload messages

            # Upload each split part one by one with progress callback
            for i, file in enumerate(split_files):
                file_info = await get_video_info(file)
                seg_duration = float(file_info["format"]["duration"])
                thumb_path = await tools.generate_thumbnail(
                    file, output_image=f"{path.name}-{process.date}.jpg"
                )
                formatted_duration = format_duration(seg_duration)
                caption = (
                    f"{path.name}\n"  # Include original file name in the caption
                    f"Part {i+1}\n"
                    f"Duration: {formatted_duration}\n"
                    f"Diminta oleh: {callback_query.from_user.mention}"
                )
                msg = await callback_query.message.reply_video(
                    file,
                    caption=caption,
                    thumb=thumb_path,
                    duration=int(seg_duration),
                    progress=progress_func,
                    progress_args=(process, time.time(), "upload", Path(file).name),
                )
                uploaded_msgs.append(msg)
                # Use the file_id from the uploaded message's video field
                media_group.append(InputMediaVideo(msg.video.file_id, caption=caption))

            # Now, send a consolidated media group with the uploaded parts
            await process.edit("<pre language=Status>Mengirim media group...</pre>")

            # Send media group in chunks of 10 (Telegram limit)
            for i in range(0, len(media_group), 10):
                chunk = media_group[i : i + 10]
                await client.send_media_group(callback_query.message.chat.id, chunk)

            # Delete the individual upload messages to clean up the chat
            for msg in uploaded_msgs:
                try:
                    await msg.delete()
                except Exception:
                    pass

            # Clean up the temporary split files and generated thumbnails
            for file in split_files:
                if os.path.exists(file):
                    os.remove(file)
            # Clean up original file
            await path.unlink(missing_ok=True)

        else:
            # For files within MAX_SIZE, get the video's duration and generate a thumbnail
            video_info = await get_video_info(str(path))
            duration = float(video_info["format"]["duration"])
            thumbnail_path = await tools.generate_thumbnail(str(path))
            formatted_duration = format_duration(duration)
            caption = (
                f"`{path.name}`\n"
                f"Duration: {formatted_duration}\n"
                f"Diminta oleh: {callback_query.from_user.mention}"
            )

            await callback_query.message.reply_video(
                str(path),
                caption=caption,
                thumb=thumbnail_path,
                duration=int(duration),
                progress=progress_func,
                progress_args=(process, start_time, "upload", path.name),
            )

            # Cleanup the original file and thumbnail
            await path.unlink(missing_ok=True)
            if os.path.exists(thumbnail_path):
                os.remove(thumbnail_path)

    await process.delete()
