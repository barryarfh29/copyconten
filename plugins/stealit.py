import time
from typing import Union

from aiopath import AsyncPath
from pyrogram import Client, filters, types

from core import delta
from utils import MessageType, get_message_type, progress_func, tools


async def stealer(
    message: types.Message, target_chat: Union[int, str], target_id: int
) -> None:
    bot = delta.bot_client
    user = delta.user_client

    target_msg: types.messages_and_media.message.Message = await user.get_messages(
        chat_id=target_chat, message_ids=target_id
    )
    message_type = get_message_type(target_msg)

    if message_type == MessageType.TEXT:
        await bot.send_message(
            chat_id=message.chat.id,
            text=target_msg.text,
            entities=target_msg.entities,
            reply_markup=target_msg.reply_markup,
            reply_parameters=types.ReplyParameters(message_id=message.id),
        )
        return

    start_time = time.time()
    media_obj = next(
        (
            getattr(target_msg, m)
            for m in [
                "audio",
                "video",
                "photo",
                "document",
                "animation",
                "sticker",
                "voice",
            ]
            if getattr(target_msg, m, None)
        ),
        None,
    )
    file_name = getattr(media_obj, "file_name", None)
    media_dl = AsyncPath(
        await user.download_media(
            target_msg,
            progress=progress_func,
            progress_args=(message, start_time, "download", file_name),
        )
    )
    thumbnail = AsyncPath(await tools.download_thumbnail(user, target_msg))

    if message_type == MessageType.AUDIO:
        await bot.send_audio(
            chat_id=message.chat.id,
            audio=media_dl,
            caption=target_msg.caption,
            caption_entities=target_msg.caption_entities,
            duration=target_msg.audio.duration,
            performer=target_msg.audio.performer,
            title=target_msg.audio.title,
            thumb=thumbnail,
            file_name=media_dl.name,
            reply_parameters=types.ReplyParameters(
                message_id=message.reply_to_message.id
            ),
            reply_markup=target_msg.reply_markup,
            progress=progress_func,
            progress_args=(message, start_time, "upload", media_dl.name),
        )
    elif message_type == MessageType.PHOTO:
        await bot.send_photo(
            chat_id=message.chat.id,
            photo=media_dl,
            caption=target_msg.caption,
            caption_entities=target_msg.caption_entities,
            has_spoiler=target_msg.has_media_spoiler,
            reply_parameters=types.ReplyParameters(
                message_id=message.reply_to_message.id
            ),
            reply_markup=target_msg.reply_markup,
            progress=progress_func,
            progress_args=(message, start_time, "upload", media_dl.name),
        )
    elif message_type == MessageType.DOCUMENT:
        await bot.send_document(
            chat_id=message.chat.id,
            document=media_dl,
            caption=target_msg.caption,
            caption_entities=target_msg.caption_entities,
            file_name=target_msg.document.file_name,
            reply_parameters=types.ReplyParameters(
                message_id=message.reply_to_message.id
            ),
            reply_markup=target_msg.reply_markup,
            progress=progress_func,
            progress_args=(message, start_time, "upload", media_dl.name),
        )
    elif message_type == MessageType.VIDEO:
        await bot.send_video(
            chat_id=message.chat.id,
            video=media_dl,
            caption=target_msg.caption,
            caption_entities=target_msg.caption_entities,
            duration=target_msg.video.duration,
            width=target_msg.video.width,
            height=target_msg.video.height,
            supports_streaming=getattr(target_msg.video, "supports_streaming", False),
            file_name=getattr(target_msg.video, "file_name", None),
            reply_parameters=types.ReplyParameters(
                message_id=message.reply_to_message.id
            ),
            reply_markup=target_msg.reply_markup,
            progress=progress_func,
            progress_args=(message, start_time, "upload", media_dl.name),
        )
    elif message_type == MessageType.ANIMATION:
        await bot.send_animation(
            chat_id=message.chat.id,
            animation=media_dl,
            caption=target_msg.caption,
            caption_entities=target_msg.caption_entities,
            duration=target_msg.animation.duration,
            width=target_msg.animation.width,
            height=target_msg.animation.height,
            file_name=getattr(target_msg.animation, "file_name", None),
            reply_parameters=types.ReplyParameters(
                message_id=message.reply_to_message.id
            ),
            reply_markup=target_msg.reply_markup,
            progress=progress_func,
            progress_args=(message, start_time, "upload", media_dl.name),
        )
    elif message_type == MessageType.STICKER:
        await bot.send_sticker(
            chat_id=message.chat.id,
            sticker=media_dl,
            reply_parameters=types.ReplyParameters(
                message_id=message.reply_to_message.id
            ),
            reply_markup=target_msg.reply_markup,
            progress=progress_func,
            progress_args=(message, start_time, "upload", media_dl.name),
        )
    elif message_type == MessageType.VOICE:
        await bot.send_voice(
            chat_id=message.chat.id,
            voice=media_dl,
            caption=target_msg.caption,
            caption_entities=target_msg.caption_entities,
            duration=target_msg.voice.duration,
            file_name=getattr(target_msg.voice, "file_name", None),
            reply_parameters=types.ReplyParameters(
                message_id=message.reply_to_message.id
            ),
            reply_markup=target_msg.reply_markup,
            progress=progress_func,
            progress_args=(message, start_time, "upload", media_dl.name),
        )
    else:
        await bot.send_message(message.chat.id, "Media type not supported.")

    await media_dl.unlink()
    if thumbnail:
        await thumbnail.unlink()


@Client.on_message(filters.command("steal"))
async def steal_cmd(client: delta.bot_client, message: types.Message) -> None:
    try:
        chat_id, msg_id, dl_mode = tools.parse_telegram_url(message.text)
    except ValueError:
        await message.reply("Send me link")
        return

    msg = await message.reply_text("Processing..")
    await stealer(msg, chat_id, int(msg_id))
    await msg.delete()
