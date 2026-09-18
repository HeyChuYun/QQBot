from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Optional


class UpsPowerState(str, Enum):
    ONLINE = "online"
    ON_BATTERY = "on_battery"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class FnosSnapshot:
    system: dict[str, Any]
    cpu: dict[str, Any]
    memory: dict[str, Any]
    disks: dict[str, Any]
    ups: dict[str, Any]


class UpsStateStore:
    def __init__(self, path: Path):
        self.path = path
        self._state = self._load()

    def _load(self) -> dict[str, str]:
        if not self.path.is_file():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return {str(key): str(value) for key, value in data.items()}

    def get(self, openid: str) -> Optional[UpsPowerState]:
        value = self._state.get(openid)
        try:
            return UpsPowerState(value) if value else None
        except ValueError:
            return None

    def set(self, openid: str, state: UpsPowerState) -> None:
        self._state[openid] = state.value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(self.path)


def _walk(value: Any, path: tuple[str, ...] = ()) -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk(child, (*path, str(key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, (*path, str(index)))
    else:
        yield ".".join(path).lower(), value


def _normalized(value: Any) -> str:
    return re.sub(r"[\s_-]+", " ", str(value).strip().lower())


def classify_ups_state(payload: Any) -> UpsPowerState:
    entries = list(_walk(payload))
    values = {_normalized(value) for _, value in entries}

    battery_values = {
        "ob",
        "on battery",
        "battery mode",
        "battery power",
        "电池供电",
        "电池模式",
        "市电异常",
        "市电断开",
        "断电",
        "停电",
    }
    online_values = {
        "ol",
        "online",
        "on line",
        "line mode",
        "utility power",
        "ac power",
        "市电正常",
        "市电供电",
        "交流供电",
    }

    if any(
        value in battery_values
        or value.startswith("ob ")
        or "on battery" in value
        or "电池供电" in value
        for value in values
    ):
        return UpsPowerState.ON_BATTERY

    for path, value in entries:
        normalized_path = re.sub(r"[^a-z0-9]", "", path)
        if normalized_path.endswith(("onbattery", "batteryactive")) and value is True:
            return UpsPowerState.ON_BATTERY
        if normalized_path.endswith(("acpresent", "lineonline", "utilityonline")):
            if value is False or _normalized(value) in {"0", "false", "no", "off"}:
                return UpsPowerState.ON_BATTERY

    if any(
        value in online_values
        or value.startswith("ol ")
        or "line mode" in value
        or "市电正常" in value
        or "市电供电" in value
        for value in values
    ):
        return UpsPowerState.ONLINE

    for path, value in entries:
        normalized_path = re.sub(r"[^a-z0-9]", "", path)
        if normalized_path.endswith(("acpresent", "lineonline", "utilityonline")):
            if value is True or _normalized(value) in {"1", "true", "yes", "on"}:
                return UpsPowerState.ONLINE
    return UpsPowerState.UNKNOWN


def ups_transition_message(
    previous: Optional[UpsPowerState],
    current: UpsPowerState,
    notify_on_recovery: bool,
    host_name: str = "飞牛 NAS",
) -> Optional[str]:
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    if current == UpsPowerState.ON_BATTERY and previous != current:
        return (
            f"【UPS 断电提醒】\n{host_name} 检测到市电中断，"
            f"UPS 已切换为电池供电。\n时间：{now}\n请及时检查供电情况。"
        )
    if (
        notify_on_recovery
        and previous == UpsPowerState.ON_BATTERY
        and current == UpsPowerState.ONLINE
    ):
        return f"【UPS 供电恢复】\n{host_name} 已恢复市电供电。\n时间：{now}"
    return None


def _unwrap(payload: Any) -> Any:
    value = payload
    for _ in range(3):
        if not isinstance(value, dict):
            break
        if "data" in value and isinstance(value["data"], (dict, list)):
            value = value["data"]
        else:
            break
    return value


def _find(payload: Any, aliases: set[str]) -> Any:
    for path, value in _walk(_unwrap(payload)):
        key = re.sub(r"[^a-z0-9]", "", path.rsplit(".", 1)[-1])
        if key in aliases and value not in (None, "", [], {}):
            return value
    return None


def _percent(value: Any) -> str:
    if value is None:
        return "未知"
    text = str(value)
    return text if "%" in text else f"{text}%"


def _duration(value: Any) -> str:
    try:
        seconds = int(float(value))
    except (TypeError, ValueError):
        return str(value or "未知")
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    return f"{days}天 {hours}小时 {minutes}分钟" if days else f"{hours}小时 {minutes}分钟"


def _disk_records(payload: Any) -> list[dict[str, Any]]:
    value = _unwrap(payload)
    candidates: list[list[dict[str, Any]]] = []

    def visit(node: Any) -> None:
        if isinstance(node, list) and node and all(isinstance(item, dict) for item in node):
            candidates.append(node)
        if isinstance(node, dict):
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    signatures = {"name", "device", "devname", "model", "serial", "health", "smart", "temperature", "temp"}
    for records in candidates:
        keys = {
            re.sub(r"[^a-z0-9]", "", str(key).lower())
            for record in records
            for key in record
        }
        if len(keys & signatures) >= 2:
            return records
    return []


def _compact_payload(payload: Any, limit: int = 260) -> str:
    value = _unwrap(payload)
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return text if len(text) <= limit else text[: limit - 1] + "…"


def format_snapshot(snapshot: FnosSnapshot, limit: int = 1800) -> str:
    host = _find(snapshot.system, {"hostname", "name"}) or "飞牛 NAS"
    version = _find(snapshot.system, {"trimversion", "version", "osversion"}) or "未知"
    uptime = _find(snapshot.system, {"uptime", "runtime", "upseconds"})
    cpu_model = _find(snapshot.system, {"cpumodel", "processor", "modelname"})
    cpu_usage = _find(snapshot.cpu, {"cpubusy", "usage", "percent", "utilization", "busy"})
    cpu_temp = _find(snapshot.cpu, {"temperature", "temp", "cputemp"})
    cpu_cores = _find(snapshot.system, {"cpucores", "cores", "corecount", "logicalcores"})
    mem_usage = _find(snapshot.memory, {"mempercent", "usage", "percent", "usedpercent"})
    mem_total = _find(snapshot.memory, {"total", "memtotal", "totalmemory"})
    ups_state = classify_ups_state(snapshot.ups)
    ups_labels = {
        UpsPowerState.ONLINE: "市电供电",
        UpsPowerState.ON_BATTERY: "电池供电（市电异常）",
        UpsPowerState.UNKNOWN: "未启用、未连接或状态未知",
    }

    lines = [
        "飞牛系统状态",
        f"主机：{host}",
        f"版本：{version}",
        f"运行时间：{_duration(uptime)}",
        "",
        "CPU",
        f"使用率：{_percent(cpu_usage)}",
    ]
    if cpu_model is not None:
        lines.append(f"型号：{cpu_model}")
    if cpu_cores is not None:
        lines.append(f"核心：{cpu_cores}")
    if cpu_temp is not None:
        lines.append(f"温度：{cpu_temp}°C" if "°" not in str(cpu_temp) else f"温度：{cpu_temp}")
    lines.extend(["", "内存", f"使用率：{_percent(mem_usage)}"])
    if mem_total is not None:
        lines.append(f"总量：{mem_total}")

    lines.extend(["", "硬盘"])
    records = _disk_records(snapshot.disks)
    if records:
        for index, record in enumerate(records, start=1):
            name = _find(record, {"name", "device", "devname", "model"}) or f"硬盘 {index}"
            health = _find(record, {"health", "smart", "status", "state"}) or "状态未知"
            temp = _find(record, {"temperature", "temp"})
            size = _find(record, {"capacity", "size", "total"})
            details = [str(health)]
            if temp is not None:
                details.append(f"{temp}°C" if "°" not in str(temp) else str(temp))
            if size is not None:
                details.append(str(size))
            lines.append(f"• {name}：{' / '.join(details)}")
    else:
        lines.append(f"• {_compact_payload(snapshot.disks)}")

    lines.extend(["", f"UPS：{ups_labels[ups_state]}"])
    text = "\n".join(lines)
    return text if len(text) <= limit else text[: limit - 1] + "…"
