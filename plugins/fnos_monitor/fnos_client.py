from __future__ import annotations

import asyncio
from typing import Any

from .monitor import FnosSnapshot


class FnosGateway:
    def __init__(
        self,
        *,
        endpoint: str,
        username: str,
        password: str,
        token: str,
        long_token: str,
        secret: str,
        use_ssl: bool,
        skip_ssl_verify: bool,
        connect_timeout: int,
        request_timeout: int,
    ):
        self.endpoint = endpoint
        self.username = username
        self.password = password
        self.token = token
        self.long_token = long_token
        self.secret = secret
        self.use_ssl = use_ssl
        self.skip_ssl_verify = skip_ssl_verify
        self.connect_timeout = connect_timeout
        self.request_timeout = request_timeout
        self._client: Any = None
        self._lock = asyncio.Lock()

    async def _connect_locked(self) -> Any:
        if self._client and self._client.connected and self._client.get_decrypted_secret():
            return self._client

        await self._close_locked()
        from fnos import FnosClient

        client = FnosClient()
        try:
            await client.connect(
                self.endpoint,
                timeout=self.connect_timeout,
                use_ssl=self.use_ssl,
                skip_ssl_verify=self.skip_ssl_verify,
            )
            if self.token and self.long_token and self.secret:
                result = await client.login_via_token(
                    self.token,
                    self.long_token,
                    self.secret,
                    timeout=self.request_timeout,
                )
            else:
                result = await client.login(
                    self.username,
                    self.password,
                    timeout=self.request_timeout,
                )
                if result.get("twofaRequired"):
                    raise RuntimeError(
                        "飞牛账号已开启两步验证，请在 config.env 中填写 "
                        "FNOS_TOKEN、FNOS_LONG_TOKEN 和 FNOS_SECRET"
                    )
                if result.get("twofaSetupRequired"):
                    raise RuntimeError("飞牛账号要求先在管理界面完成两步验证绑定")

            if not client.get_decrypted_secret() or result.get("result") == "fail":
                message = result.get("msg") or result.get("errmsg") or result
                raise RuntimeError(f"飞牛登录失败：{message}")
        except Exception:
            await client.close()
            raise
        self._client = client
        return client

    @property
    def host_name(self) -> str:
        return str(getattr(self._client, "host_name", "") or "")

    async def _close_locked(self) -> None:
        if self._client:
            try:
                await self._client.close()
            finally:
                self._client = None

    async def close(self) -> None:
        async with self._lock:
            await self._close_locked()

    async def get_ups_status(self) -> dict[str, Any]:
        async with self._lock:
            client = await self._connect_locked()
            try:
                from fnos import SAC

                return await SAC(client).ups_status(timeout=self.request_timeout)
            except Exception:
                await self._close_locked()
                raise

    async def collect_snapshot(self, include_ups: bool = True) -> FnosSnapshot:
        async with self._lock:
            client = await self._connect_locked()
            try:
                from fnos import ResourceMonitor, SAC, Store, SystemInfo

                resources = ResourceMonitor(client)
                system = SystemInfo(client)
                store = Store(client)

                system_data: dict[str, Any] = {}
                for name, request in (
                    ("host", system.get_host_name),
                    ("version", system.get_trim_version),
                    ("hardware", system.get_hardware_info),
                    ("uptime", system.get_uptime),
                ):
                    try:
                        system_data[name] = await request(timeout=self.request_timeout)
                    except Exception as error:
                        system_data[name] = {"error": str(error)}

                cpu, memory, disks = await asyncio.gather(
                    resources.cpu(timeout=self.request_timeout),
                    resources.memory(timeout=self.request_timeout),
                    store.list_disks(timeout=self.request_timeout),
                )
                ups: dict[str, Any] = {}
                if include_ups:
                    try:
                        ups = await SAC(client).ups_status(timeout=self.request_timeout)
                    except Exception as error:
                        ups = {"error": str(error)}
                return FnosSnapshot(system_data, cpu, memory, disks, ups)
            except Exception:
                await self._close_locked()
                raise
