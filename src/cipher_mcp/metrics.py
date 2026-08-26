from __future__ import annotations

import os
import time
from typing import Any

import psutil


class ServerMetrics:
    def cpu(self) -> dict[str, Any]:
        return {
            "percent": psutil.cpu_percent(interval=0.1),
            "logical_cpus": psutil.cpu_count(logical=True),
            "physical_cpus": psutil.cpu_count(logical=False),
        }

    def memory(self) -> dict[str, Any]:
        value = psutil.virtual_memory()
        return {
            "total_bytes": value.total,
            "available_bytes": value.available,
            "used_bytes": value.used,
            "percent": value.percent,
        }

    def load(self) -> dict[str, Any]:
        one, five, fifteen = os.getloadavg()
        return {"load_1m": one, "load_5m": five, "load_15m": fifteen}

    def uptime(self) -> dict[str, Any]:
        seconds = max(0, int(time.time() - psutil.boot_time()))
        return {"seconds": seconds, "human": _human_duration(seconds)}

    def disk_usage(self, path: str = "/") -> dict[str, Any]:
        if path != "/":
            raise ValueError("only the root filesystem is available")
        value = psutil.disk_usage(path)
        return {
            "path": path,
            "total_bytes": value.total,
            "used_bytes": value.used,
            "free_bytes": value.free,
            "percent": value.percent,
        }

    def temperature(self) -> dict[str, Any]:
        try:
            readings = psutil.sensors_temperatures(fahrenheit=False)
        except (AttributeError, OSError):
            readings = {}
        values: list[dict[str, Any]] = []
        for chip, entries in readings.items():
            for entry in entries:
                values.append(
                    {
                        "chip": chip,
                        "label": entry.label or "sensor",
                        "celsius": entry.current,
                        "high_celsius": entry.high,
                        "critical_celsius": entry.critical,
                    }
                )
        return {
            "available": bool(values),
            "sensors": values,
            "message": None if values else "No temperature sensors are exposed to this process.",
        }

    def health_summary(self) -> dict[str, Any]:
        cpu = self.cpu()
        memory = self.memory()
        disk = self.disk_usage()
        status = "healthy"
        warnings: list[str] = []
        if cpu["percent"] >= 90:
            warnings.append("CPU utilization is high")
        if memory["percent"] >= 90:
            warnings.append("memory utilization is high")
        if disk["percent"] >= 90:
            warnings.append("root filesystem utilization is high")
        if warnings:
            status = "warning"
        return {
            "status": status,
            "warnings": warnings,
            "cpu": cpu,
            "memory": memory,
            "load": self.load(),
            "uptime": self.uptime(),
            "disk": disk,
            "temperature": self.temperature(),
        }


def _human_duration(seconds: int) -> str:
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    return f"{days}d {hours}h {minutes}m"
