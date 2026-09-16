# QQ 官方机器人 Python 起步项目

本项目使用腾讯 QQ 机器人官方文档推荐的 Python SDK
[`tencent-connect/botpy`](https://github.com/tencent-connect/botpy)，PyPI 包名为
[`qq-botpy`](https://pypi.org/project/qq-botpy/)。

已实现：

- QQ 频道中 `@机器人` 后回复
- QQ 群中 `@机器人` 后回复
- QQ 消息列表中与机器人单聊
- `/帮助`、`/状态` 两个示例指令
- `/虚拟` 主动给指定管理者发送“你好”
- `/我的ID` 在单聊中查询配置管理者所需的 `user_openid`
- `/你好` 回复带 Emoji 的问候
- `/表情` 随机回复一个 Unicode 表情
- `/图片` 在单聊、群聊或频道中发送机器人头像
- 定时监听一个或多个 GitHub 仓库的默认分支提交，并主动通知指定 QQ 群
- `/本群ID` 查询配置通知目标所需的 `group_openid`
- `/仓库状态` 查询监听是否已启动、仓库列表和检查间隔
- 其他文字原样回显，方便继续添加业务逻辑

## 1. 在 QQ 开放平台创建机器人

1. 打开 [QQ 机器人开放平台](https://q.qq.com/#/)并完成个人或企业主体入驻。
2. 创建机器人，在“开发设置”中取得 `AppID` 和 `AppSecret`。
3. 选择频道、群聊、消息列表单聊等开发场景，并配置沙箱群、沙箱频道或沙箱账号。
4. 新机器人正式上线前通常还要配置服务器公网 IP 白名单；沙箱环境不受正式环境 IP 白名单限制。

`AppSecret` 等同于密码，不要发给他人，也不要写入代码或提交到 Git。

## 2. 准备本地环境

安装 Python 3.8 或更高版本，然后在项目目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install -r plugins/github_monitor/requirements.txt
Copy-Item .env.example .env
```

编辑根目录 `.env`，这里只存放机器人核心凭据：

```dotenv
QQ_BOT_APPID=你的AppID
QQ_BOT_SECRET=你的AppSecret
QQ_BOT_ADMIN_OPENID=管理者的user_openid
```

各插件的业务设置放在插件自己的 `config.env` 中。

## 3. 启动机器人

首次运行或修改指令列表后，先同步 QQ 输入框的 `/` 指令面板：

```powershell
python sync_commands.py
```

脚本会为单聊、群聊和文字子频道创建或更新全局指令面板，不会重复创建由本项目管理的面板。

```powershell
python bot.py
```

日志出现“机器人 ... 已连接”后，在已配置的沙箱环境中测试：

- 频道或群聊：发送 `@机器人 /帮助`
- 单聊：直接发送 `/状态`

首次配置管理者时，先在机器人单聊中发送 `/我的ID`，把返回值写入
`.env` 的 `QQ_BOT_ADMIN_OPENID`，然后重启服务。此后在任意已开通场景发送
`/虚拟`，机器人都会尝试给该管理者单聊发送“你好”。主动消息受 QQ 平台权限和频次限制。

## 4. GitHub 提交监听

1. 管理员在机器人单聊中发送 `/我的ID`，群聊中发送 `/本群ID`，取得对应的 OpenID。
2. 打开 `plugins/github_monitor/subscriptions.json`，在 `personal` 和 `groups` 列表中分别填写接收者及其仓库列表。
3. 私有仓库需要在 `plugins/github_monitor/config.env` 中填写只读 GitHub Token。
4. 重启机器人，发送 `/仓库状态` 确认监听已运行。

订阅配置示例：

```json
{
  "personal": [
    {
      "name": "管理员",
      "openid": "个人 user_openid",
      "repositories": ["owner/repo", "another-owner/another-repo"]
    }
  ],
  "groups": [
    {
      "name": "开发群",
      "openid": "群 group_openid",
      "repositories": ["owner/repo"]
    },
    {
      "name": "测试群",
      "openid": "另一个群 group_openid",
      "repositories": ["another-owner/another-repo"]
    }
  ]
}
```

每个个人或群组都有独立的仓库列表和推送进度。一个接收者发送失败不会阻止其他订阅者，失败的通知会在下次检查时重试。

首次启动只记录每个仓库最新提交作为基线，不会补发历史提交。此后默认每 300 秒检查一次，发现多条新提交时按从旧到新的顺序发送。状态保存在插件自己的 `plugins/github_monitor/data/state.json`，服务重启不会重复通知。

公开仓库可以不填写 `GITHUB_TOKEN`。私有仓库必须使用有只读 Contents 权限的 Fine-grained GitHub Token；监听较多公开仓库时也建议配置 Token，避免匿名 API 每小时 60 次的限额。

通知默认由 Playwright 调用本机 Edge，将 HTML 卡片渲染成 PNG 后通过 QQ 官方接口上传。Windows 使用 `BROWSER_CHANNEL=msedge`；容器通过 `BROWSER_EXECUTABLE=/usr/bin/chromium` 使用镜像内的 Chromium。渲染或图片上传失败时，`FALLBACK_TO_TEXT=true` 会自动改发文本，避免漏通知。

`GITHUB_INCLUDE_LINK=false` 控制降级文本是否包含链接。需要链接时改为 `true`，并先在 QQ 开放平台配置 `github.com` 白名单。主动消息仍受 QQ 平台权限和频次限制。

## 5. 项目结构

```text
bot.py                         启动入口
sync_commands.py               同步 QQ 指令面板
qqbot_app/config.py            环境配置和校验
qqbot_app/commands.py          指令定义与普通回复
qqbot_app/client.py            QQ 事件分发
qqbot_app/media.py             图片发送
qqbot_app/plugin.py            插件发现、生命周期和指令分发
plugins/github_monitor/        GitHub 监听插件（代码、配置、数据）
tests/                         单元测试
```

本项目通过 WebSocket 接收官方事件，不需要为了收消息额外搭建公网 HTTP 回调地址。进程必须持续运行；部署到服务器时需要使用守护进程、容器或云服务保持在线。

## 6. 插件系统

机器人启动时会扫描 `plugins/` 下所有带 `plugin.json` 的目录。每个插件独立包含入口代码、配置和运行数据；删除整个插件目录并重启服务，即可彻底移除该功能。修改插件指令后再执行一次 `python sync_commands.py`，QQ 输入框中的 `/` 补全也会同步更新。

插件目录的最小结构：

```text
plugins/my_plugin/
  plugin.json       插件 ID、名称、版本和入口类
  plugin.py         继承 BotPlugin 的插件代码
  requirements.txt  插件自己的 Python 依赖（可选）
  config.env        插件私有配置（不会提交到 Git）
  data/             插件运行数据（不会提交到 Git）
```

插件可以声明自己的 QQ 指令，并实现 `start()`、`stop()`、`handle_command()` 和 `on_message()`。某个插件加载或运行失败时会写入日志，不会阻止其他插件加载。现有 `plugins/github_monitor/` 可以直接作为新插件模板。

GitHub 通知图片的 HTML 和 CSS 位于 `plugins/github_monitor/template.html`。可以直接编辑该文件调整卡片样式；保留 `{{REPOSITORY}}`、`{{TITLE}}`、`{{AUTHOR}}`、`{{SHA}}` 和 `{{TIMESTAMP}}` 占位符即可。模板在每次生成图片时重新读取，修改后无需改动 Python 代码。

三个入口分别是：

| QQ 场景 | SDK 事件方法 | 所需 Intent |
| --- | --- | --- |
| 频道内 @ 机器人 | `on_at_message_create` | `public_guild_messages` |
| 群内 @ 机器人 | `on_group_at_message_create` | `public_messages` |
| 消息列表单聊 | `on_c2c_message_create` | `public_messages` |

## 7. Docker 部署

Docker 镜像只包含机器人框架，不包含 `plugins/` 下的任何插件代码、配置或数据。`Dockerfile` 只复制核心文件，`.dockerignore` 同时排除整个插件目录，构建阶段还会检查容器中的 `/app/plugins` 是否为空。

使用 Compose 启动：

```powershell
docker compose up -d --build
docker compose logs -f qqbot
```

Compose 会进行两个挂载：

- 宿主机 `./plugins` 绑定到容器 `/app/plugins`，删除宿主机插件目录并重启容器即可卸载插件。
- 命名卷 `plugin-dependencies` 挂载到 `/app/.plugin-deps`，缓存各插件 `requirements.txt` 声明的依赖。

修改插件或配置后执行 `docker compose restart qqbot`。插件指令发生变化后，用下面的命令同步 QQ `/` 面板：

```powershell
docker compose run --rm qqbot python sync_commands.py
```

容器内置系统 Chromium 和中文字体，但没有 GitHub 插件代码。GitHub 插件挂载后，其 Playwright Python 依赖由 `docker_entrypoint.py` 自动安装；依赖清单未变化时会直接使用命名卷缓存。

## 8. GitHub Actions

工作流位于 `.github/workflows/docker.yml`。推送到 `main` 或 `master`、推送 `v*` 标签以及手动运行时，会构建框架镜像并发布到 `ghcr.io/<仓库所有者>/<仓库名>`。Pull Request 只构建验证，不推送。工作流使用 GitHub 自动提供的 `GITHUB_TOKEN`，无需额外配置镜像仓库密码。

服务器使用 GHCR 镜像时，可设置镜像名后启动：

```powershell
$env:QQBOT_IMAGE="ghcr.io/owner/repository:latest"
docker compose pull
docker compose up -d
```

## 官方资料

- [QQ 机器人介绍与接入指南](https://bot.q.qq.com/wiki/)
- [QQ 机器人 API v2 启动接入](https://bot.q.qq.com/wiki/develop/api-v2/)
- [Access Token 鉴权说明](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/access-token.html)
- [创建指令面板 API](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_panels.post.html)
- [修改全局自定义菜单 API](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_menu.put.html)
- [官方 Python SDK 源码和示例](https://github.com/tencent-connect/botpy)

官方已废弃旧的 Token 鉴权。当前应使用 `AppID + AppSecret`，SDK 会处理 Access Token 获取与 WebSocket 连接。
