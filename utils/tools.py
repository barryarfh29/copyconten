import asyncio
import logging
from typing import Optional, Tuple
from urllib.parse import parse_qs, urlparse

from pyrogram import Client, types

from . import MessageType, get_message_type

logger = logging.getLogger("Delta")


async def get_video_duration(input_video: str) -> float:

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        input_video,
    ]
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        error_message = stderr.decode().strip()
        raise Exception(f"ffprobe error: {error_message}")
    try:
        duration = float(stdout.decode().strip())
        return duration
    except ValueError:
        raise Exception("Tidak dapat memparsing durasi video.")


async def generate_thumbnail(
    input_video: str,
    output_image: str = "downloads/thumbs.jpg",
    time_position: str = None,
) -> str:
    if time_position is None:
        full_duration = await get_video_duration(input_video)
        time_offset = full_duration * 0.1
        time_position = str(time_offset)
    ffmpeg_cmd = [
        "ffmpeg",
        "-ss",
        time_position,
        "-i",
        input_video,
        "-vframes",
        "1",
        "-q:v",
        "8",
        output_image,
        "-y",
    ]
    process = await asyncio.create_subprocess_exec(
        *ffmpeg_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        error_message = stderr.decode().strip()
        raise Exception(f"ffmpeg error: {error_message}")
    return output_image


async def download_thumbnail(client: Client, msg: types.Message) -> str:
    thumb = None
    try:
        msg_type = get_message_type(msg)
        if msg_type == MessageType.DOCUMENT and msg.document.thumbs:
            thumb = await client.download_media(msg.document.thumbs[0].file_id)
        elif msg_type == MessageType.VIDEO and msg.video.thumbs:
            thumb = await client.download_media(msg.video.thumbs[0].file_id)
        elif msg_type == MessageType.AUDIO and msg.audio.thumbs:
            thumb = await client.download_media(msg.audio.thumbs[0].file_id)
    except Exception as e:
        logger.error(str(e))
        thumb = None
    return thumb


from typing import Optional, Tuple
from urllib.parse import parse_qs, urlparse


def parse_telegram_url(url: str) -> Tuple[str, str, str, Optional[str], str]:
    if not url:
        raise ValueError("No URL provided")
    text = url.strip()
    if text.startswith("/"):
        parts = text.split(" ", 1)
        if len(parts) == 2:
            text = parts[1].strip()
        else:
            raise ValueError("No URL provided after command")
    msg_id_second = None
    if " - " in text:
        first_url, second_url = text.split(" - ", 1)
        parsed1 = urlparse(first_url.strip())
        path_parts1 = parsed1.path.strip("/").split("/")
        if len(path_parts1) < 2:
            raise ValueError("Invalid first URL: missing chat id or message id")
        if path_parts1[0] == "c":
            chat_type = "private"
            chat_id = path_parts1[1]
        else:
            chat_type = "public"
            chat_id = path_parts1[0]
        msg_id = path_parts1[-1] if len(path_parts1) >= 3 else path_parts1[1]
        query_params = parse_qs(parsed1.query)
        if "single" in query_params:
            msg_type = "single"
        elif parsed1.query:
            msg_type = parsed1.query
        else:
            msg_type = "default"
        parsed2 = urlparse(second_url.strip())
        path_parts2 = parsed2.path.strip("/").split("/")
        if len(path_parts2) < 2:
            raise ValueError("Invalid second URL: missing chat id or message id")
        msg_id_second = path_parts2[-1] if len(path_parts2) >= 3 else path_parts2[1]
    else:
        parsed = urlparse(text)
        path_parts = parsed.path.strip("/").split("/")
        if len(path_parts) < 2:
            raise ValueError("Invalid URL: missing chat id or message id")
        if path_parts[0] == "c":
            chat_type = "private"
            chat_id = path_parts[1]
        else:
            chat_type = "public"
            chat_id = path_parts[0]
        msg_id = path_parts[-1] if len(path_parts) >= 3 else path_parts[1]
        query_params = parse_qs(parsed.query)
        if "single" in query_params:
            msg_type = "single"
        elif parsed.query:
            msg_type = parsed.query
        else:
            msg_type = "default"

    if chat_type == "private":
        _chat_id = "-100" + chat_id
        chat_id = int(_chat_id)

    return chat_type, chat_id, msg_id, msg_type, msg_id_second
