import time

from aiopath import AsyncPath
from pyrogram import Client, filters

from core import missav_dl
from utils import progress_func, tools


@Client.on_message(filters.command("missav"))
async def missav_cmd(client: Client, message):
    if len(message.command) < 2:
        return await message.reply("Go to MissAV and copy the link!")

    link = message.command[1]

    process = await message.reply("Processing...")
    succes, path = await missav_dl(link, quality="lowest", msg=process)
    if succes:
        start_time = time.time()
        path = AsyncPath(path)
        thumbnail = AsyncPath(await tools.generate_thumbnail(path))

        caption = f"`{path.name}`\nRequested by: {message.from_user.mention}"

        await message.reply_video(
            path,
            caption=caption,
            thumb=thumbnail,
            progress=progress_func,
            progress_args=(process, start_time, "upload", path.name),
        )

        await path.unlink()
        await thumbnail.unlink()

    await process.delete()
