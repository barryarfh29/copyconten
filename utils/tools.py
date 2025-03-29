import logging
from typing import Tuple
from urllib.parse import parse_qs, urlparse

from pyrogram import Client, types

from . import MessageType, get_message_type

logger = logging.getLogger("Delta")


async def download_thumbnail(client: Client, msg: types.Message) -> str:
    """
    Auto-detect the message type and download the corresponding thumbnail if available.
    Returns the file path of the downloaded thumbnail or None if not available.
    """
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


from typing import Tuple
from urllib.parse import parse_qs, urlparse


def parse_telegram_url(url: str) -> Tuple[str, str, str]:
    if not url:
        raise ValueError("No URL provided")

    text = url.strip()

    # Remove a command prefix if present.
    if text.startswith("/"):
        parts = text.split(" ", 1)
        if len(parts) == 2:
            text = parts[1].strip()
        else:
            raise ValueError("No URL provided after command")

    parsed = urlparse(text)
    path_parts = parsed.path.strip("/").split("/")
    if len(path_parts) < 2:
        raise ValueError("Invalid URL: missing chat id or message id")

    chat_id = path_parts[0]
    # If there are more than two parts, assume this is a topic link and use the last segment as the message id.
    if len(path_parts) == 2:
        msg_id = path_parts[1]
    else:
        msg_id = path_parts[-1]

    qs = parse_qs(parsed.query)
    if "single" in qs:
        msg_type = "single"
    elif parsed.query:
        msg_type = parsed.query
    else:
        msg_type = "default"

    return chat_id, msg_id, msg_type
