import os
import time

from aiopath import AsyncPath
from pyrogram import Client

from core import missav_dl
from utils import split_video_by_size, tools

MAX_SIZE = 2097152000  # 2GB in bytes


async def split_and_upload(client, message, path, start_time):
    """Split video if it's larger than MAX_SIZE and upload via media group."""
    file_size = os.path.getsize(path)

    if file_size > MAX_SIZE:
        # Split the file into smaller parts
        output_prefix = str(AsyncPath(path).parent / "split_")
        output_files = await split_video_by_size(path, output_prefix, MAX_SIZE)

        # Upload the split files using media group
        media_group = [
            InputMediaVideo(file, caption=f"Part {i+1}")
            for i, file in enumerate(output_files)
        ]
        await client.send_media_group(message.chat.id, media_group)
    else:
        # If the file is smaller than MAX_SIZE, upload directly
        thumbnail = AsyncPath(await tools.generate_thumbnail(path))
        caption = f"`{path.name}`\nDiminta oleh: {message.from_user.mention}"

        await message.reply_video(
            path,
            caption=caption,
            thumb=thumbnail,
            progress=progress_func,
            progress_args=(start_time, "upload", path.name),
        )

        await path.unlink()
        await thumbnail.unlink()


@Client.on_callback_query(filters.regex(r"quality_(high|medium|lowest)"))
async def quality_callback(client: Client, callback_query):
    quality = callback_query.data.split("_")[1]
    link = cache.get(callback_query.message.reply_to_message.id)

    if not link:
        return await callback_query.answer("Tautan tidak ditemukan!", show_alert=True)

    process = await callback_query.message.edit("Memproses unduhan...")
    success, path = await missav_dl(link, quality=quality, msg=process)

    if success:
        start_time = time.time()
        path = AsyncPath(path)

        # Process the file and upload it, splitting if needed
        await split_and_upload(client, callback_query.message, path, start_time)

    await process.delete()
