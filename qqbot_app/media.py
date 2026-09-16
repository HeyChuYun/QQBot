from __future__ import annotations

from botpy import logging
from botpy.message import C2CMessage, GroupMessage, Message


logger = logging.get_logger()


async def reply_channel_image(message: Message, image_url: str) -> None:
    try:
        await message.reply(image=image_url)
    except Exception:
        logger.exception("频道图片发送失败")
        await message.reply(content="图片发送失败，请稍后重试。")


async def reply_group_image(message: GroupMessage, image_url: str) -> None:
    try:
        media = await message._api.post_group_file(group_openid=message.group_openid, file_type=1, url=image_url)
        await message._api.post_group_message(group_openid=message.group_openid, msg_type=7, msg_id=message.id, media=media)
    except Exception:
        logger.exception("群聊图片发送失败")
        await message._api.post_group_message(group_openid=message.group_openid, msg_type=0, msg_id=message.id, content="图片发送失败，请稍后重试。")


async def reply_c2c_image(message: C2CMessage, image_url: str) -> None:
    try:
        media = await message._api.post_c2c_file(openid=message.author.user_openid, file_type=1, url=image_url)
        await message._api.post_c2c_message(openid=message.author.user_openid, msg_type=7, msg_id=message.id, media=media)
    except Exception:
        logger.exception("单聊图片发送失败")
        await message._api.post_c2c_message(openid=message.author.user_openid, msg_type=0, msg_id=message.id, content="图片发送失败，请稍后重试。")
