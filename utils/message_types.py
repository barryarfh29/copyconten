from enum import Enum

import pyrogram


class MessageType(Enum):
    DOCUMENT = "Document"
    VIDEO = "Video"
    ANIMATION = "Animation"
    STICKER = "Sticker"
    VOICE = "Voice"
    AUDIO = "Audio"
    PHOTO = "Photo"
    TEXT = "Text"
    UNKNOWN = "Unknown"


def get_message_type(
    msg: pyrogram.types.messages_and_media.message.Message,
) -> MessageType:
    if msg.document:
        return MessageType.DOCUMENT
    elif msg.video:
        return MessageType.VIDEO
    elif msg.animation:
        return MessageType.ANIMATION
    elif msg.sticker:
        return MessageType.STICKER
    elif msg.voice:
        return MessageType.VOICE
    elif msg.audio:
        return MessageType.AUDIO
    elif msg.photo:
        return MessageType.PHOTO
    elif msg.text:
        return MessageType.TEXT
    return MessageType.UNKNOWN
