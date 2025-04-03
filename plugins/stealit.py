import time
from typing import Union

from aiopath import AsyncPath
from pyrogram import Client, filters, types
from pyrogram.errors import (
    InviteHashExpired,
    RPCError,
    UserAlreadyParticipant,
    UsernameNotOccupied,
)

from core import delta
from utils import MessageType, get_message_type, progress_func, tools


async def stealer(
    message: types.Message, target_chat: Union[int, str], target_id: int
) -> None:
    """
    Download and forward a message from target chat to current chat.

    Args:
        message: The original command message.
        target_chat: Source chat ID or username.
        target_id: Source message ID.
    """
    bot = delta.bot_client
    user = delta.user_client

    # Get the target message from user client
    target_msg: types.messages_and_media.message.Message = await user.get_messages(
        chat_id=target_chat, message_ids=target_id
    )
    message_type = get_message_type(target_msg)

    # Handle text messages directly
    if message_type == MessageType.TEXT:
        await bot.send_message(
            chat_id=message.chat.id,
            text=target_msg.text,
            entities=target_msg.entities,
            reply_markup=target_msg.reply_markup,
            reply_parameters=types.ReplyParameters(message_id=message.id),
        )
        return

    # Download the media file
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
    try:
        media_dl = AsyncPath(
            await user.download_media(
                target_msg,
                progress=progress_func,
                progress_args=(message, start_time, "download", file_name),
            )
        )
    except ValueError:
        return

    # Download thumbnail if available
    thumbnail = (
        await tools.generate_thumbnail(media_dl)
        if message_type == MessageType.VIDEO
        else await tools.download_thumbnail(user, target_msg)
    )
    if thumbnail:
        thumbnail = AsyncPath(thumbnail)

    # Use reply_to_message.id if available, otherwise message.id
    reply_msg_id = (
        message.reply_to_message.id if message.reply_to_message else message.id
    )

    try:
        # Send different types of media based on message type
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
                reply_parameters=types.ReplyParameters(message_id=reply_msg_id),
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
                reply_parameters=types.ReplyParameters(message_id=reply_msg_id),
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
                thumb=thumbnail,
                disable_content_type_detection=True,
                reply_parameters=types.ReplyParameters(message_id=reply_msg_id),
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
                supports_streaming=getattr(
                    target_msg.video, "supports_streaming", False
                ),
                thumb=thumbnail,
                file_name=getattr(target_msg.video, "file_name", None),
                reply_parameters=types.ReplyParameters(message_id=reply_msg_id),
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
                reply_parameters=types.ReplyParameters(message_id=reply_msg_id),
                reply_markup=target_msg.reply_markup,
                progress=progress_func,
                progress_args=(message, start_time, "upload", media_dl.name),
            )
        elif message_type == MessageType.STICKER:
            await bot.send_sticker(
                chat_id=message.chat.id,
                sticker=media_dl,
                reply_parameters=types.ReplyParameters(message_id=reply_msg_id),
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
                reply_parameters=types.ReplyParameters(message_id=reply_msg_id),
                reply_markup=target_msg.reply_markup,
                progress=progress_func,
                progress_args=(message, start_time, "upload", media_dl.name),
            )
        else:
            await bot.send_message(message.chat.id, "Media type not supported.")
    finally:
        # Clean up temporary files
        await media_dl.unlink()
        if thumbnail:
            await thumbnail.unlink()


@Client.on_message(filters.command("steal"))
async def steal_cmd(client: Client, message: types.Message) -> None:
    """
    Command handler for /steal command.

    Args:
        client: The Pyrogram client.
        message: The command message.
    """
    # Check if URL is provided
    if len(message.command) < 2:
        await message.reply_text("No URL provided.")
        return

    url = message.command[1]
    msg = await message.reply_text("Processing...")

    # Handle invite links
    if any(link in url for link in ["https://t.me/+", "https://t.me/joinchat/"]):
        try:
            await delta.user_client.join_chat(url)
        except UserAlreadyParticipant:
            pass
        except InviteHashExpired:
            await msg.edit(
                "The invite link has expired. Please provide a valid invite link."
            )
            return
        except UsernameNotOccupied:
            await msg.edit("The username does not exist. Please check the username.")
            return
        except RPCError as e:
            await msg.edit(f"Something went wrong!\n{str(e)}")
            return

        await msg.edit("Joined successfully!")
        return

    # Parse Telegram URL
    try:
        chat_type, chat_id, msg_id, msg_type, to_id = tools.parse_telegram_url(
            message.text
        )
    except ValueError:
        await msg.edit("Send me a valid Telegram link.")
        return

    # Fix the int too big to convert issue
    try:
        msg_id = int(msg_id)
        to_id = int(to_id) if to_id is not None else msg_id
    except ValueError:
        await msg.edit("Invalid message ID in the URL.")
        return

    # Retrieve the chat information to check for protected content
    try:
        target_chat_info = await delta.user_client.get_chat(chat_id)
    except Exception:
        pass

    # Process each message in the range
    try:
        for m_id in range(msg_id, to_id + 1):
            # If the target chat has protected content, always use the stealer method.
            if target_chat_info.has_protected_content:
                await stealer(msg, chat_id, m_id)
            else:
                if chat_type == "public":
                    try:
                        if msg_type == "single":
                            await delta.bot_client.copy_message(
                                msg.chat.id,
                                chat_id,
                                m_id,
                                reply_parameters=types.ReplyParameters(
                                    message_id=message.id
                                ),
                            )
                        else:
                            try:
                                await delta.bot_client.copy_media_group(
                                    msg.chat.id,
                                    chat_id,
                                    m_id,
                                    reply_parameters=types.ReplyParameters(
                                        message_id=message.id
                                    ),
                                )
                            except Exception:
                                await delta.user_client.copy_media_group(
                                    msg.chat.id,
                                    chat_id,
                                    m_id,
                                    reply_parameters=types.ReplyParameters(
                                        message_id=message.id
                                    ),
                                )
                    except Exception:
                        await msg.edit(
                            f"Using alternative method for message {m_id}..."
                        )
                        await stealer(msg, chat_id, m_id)
                else:
                    try:
                        await delta.bot_client.copy_message(
                            msg.chat.id,
                            chat_id,
                            m_id,
                            reply_parameters=types.ReplyParameters(
                                message_id=message.id
                            ),
                        )
                    except Exception:
                        await stealer(msg, chat_id, m_id)
    except Exception as e:
        await msg.edit(f"Failed to process messages: {str(e)}")
        return

    await msg.delete()
