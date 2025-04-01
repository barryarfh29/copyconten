from pyrogram import Client, filters

from core import missav_dl


@Client.on_message(filters.command("missav"))
async def missav_cmd(client: Client, message):
    if len(message.command) < 2:
        return await message.reply("Go to MissAV and copy the link!")

    link = message.command[1]

    process = await message.reply("Processing...")
    data = await missav_dl(link, quality="lowest", msg=process)
    print(data)
