from __future__ import annotations

import botpy
from botpy import logging
from botpy.message import C2CMessage, GroupMessage, Message

from .commands import build_text_reply, is_command, normalize_content
from .config import Settings
from .media import reply_c2c_image, reply_channel_image, reply_group_image
from .plugin import MessageContext, PluginManager


logger = logging.get_logger()


class QQBotClient(botpy.Client):
    def __init__(self, settings: Settings, plugin_manager: PluginManager, **kwargs):
        super().__init__(**kwargs)
        self.settings = settings
        self.plugin_manager = plugin_manager

    async def on_ready(self) -> None:
        logger.info("机器人 %s 已连接", self.robot.name)
        await self.plugin_manager.start(self)

    async def close(self) -> None:
        await self.plugin_manager.stop()
        await super().close()

    async def on_at_message_create(self, message: Message) -> None:
        if is_command(message.content, "图片"):
            await reply_channel_image(message, self.robot.avatar)
            return
        await message.reply(
            content=await self.command_reply(message.content, message, "channel")
        )

    async def on_group_at_message_create(self, message: GroupMessage) -> None:
        if is_command(message.content, "图片"):
            await reply_group_image(message, self.robot.avatar)
            return
        if is_command(message.content, "本群ID"):
            reply = f"当前群的 group_openid：\n{message.group_openid}"
        else:
            reply = await self.command_reply(message.content, message, "group")
        await message._api.post_group_message(group_openid=message.group_openid, msg_type=0, msg_id=message.id, content=reply)

    async def on_c2c_message_create(self, message: C2CMessage) -> None:
        if is_command(message.content, "图片"):
            await reply_c2c_image(message, self.robot.avatar)
            return
        if is_command(message.content, "我的ID"):
            reply = f"你的 user_openid：\n{message.author.user_openid}"
        else:
            reply = await self.command_reply(message.content, message, "c2c")
        await message._api.post_c2c_message(openid=message.author.user_openid, msg_type=0, msg_id=message.id, content=reply)

    async def command_reply(self, content: str, message, scope: str) -> str:
        plugin_response = await self.plugin_manager.dispatch(
            MessageContext(
                client=self,
                message=message,
                scope=scope,
                content=content,
            )
        )
        if plugin_response is not None:
            return plugin_response

        if normalize_content(content) not in {"/虚拟", "虚拟"}:
            return build_text_reply(
                content, plugin_help=self.plugin_manager.help_lines(scope)
            )
        if not self.settings.admin_openid:
            return "尚未配置管理者。请先在单聊发送 /我的ID，再把得到的值写入 .env 的 QQ_BOT_ADMIN_OPENID 并重启。"

        try:
            await self.api.post_c2c_message(openid=self.settings.admin_openid, msg_type=0, content="你好")
        except Exception:
            logger.exception("向管理者发送消息失败")
            return "向管理者发送失败，请检查主动消息权限和调用频次。"
        return "已向管理者发送：你好"
