"""
VPS & Cloud Container CPU Core & Quota Detection and Load Governor.
Detects virtualization, cgroup CPU quotas, CPU affinity, and system load
to calculate safe concurrency without overloading the host VPS.
"""

import os
import math
from typing import Dict, Any, Optional, Tuple


class GovernorMode:
    VPS_SAFE = "VPS_SAFE"          # Caps at 70% to guarantee OS / DB headroom
    BALANCED = "BALANCED"          # Caps at 85% for general compute
    MAX_PERFORMANCE = "MAX_PERF"   # Uses 100% of detected quota


class VPSHardwareGovernor:
    """Detects VPS virtualization and cgroup quotas, and regulates CPU workload."""
    def __init__(self, mode: str = GovernorMode.VPS_SAFE):
        self.mode = mode
        self.hardware_profile = self._profile_environment()

    def _profile_environment(self) -> Dict[str, Any]:
        """Inspects kernel, cgroups, and CPU topology."""
        raw_cores = os.cpu_count() or 1
        affinity_cores = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else raw_cores
        cgroup_quota_cores = self._detect_cgroup_quota()
        is_virtual = self._detect_virtualization()
        is_container = self._detect_container()

        # Effective core limit is the minimum of affinity, raw cores, and cgroup quota
        effective_limit = float(affinity_cores)
        if cgroup_quota_cores is not None:
            effective_limit = min(effective_limit, cgroup_quota_cores)

        effective_limit = max(1.0, effective_limit)

        return {
            "raw_cpu_count": raw_cores,
            "affinity_cpu_count": affinity_cores,
            "cgroup_quota_cores": cgroup_quota_cores,
            "effective_cores": effective_limit,
            "is_virtualized": is_virtual,
            "is_container": is_container,
        }

    def _detect_cgroup_quota(self) -> Optional[float]:
        """Reads cgroup v1 or v2 CPU bandwidth limits."""
        # Check cgroup v2
        cgroup_v2_path = "/sys/fs/cgroup/cpu.max"
        if os.path.exists(cgroup_v2_path):
            try:
                with open(cgroup_v2_path, "r") as f:
                    parts = f.read().strip().split()
                    if len(parts) >= 2 and parts[0] != "max":
                        quota = float(parts[0])
                        period = float(parts[1])
                        return quota / period
            except Exception:
                pass

        # Check cgroup v1
        quota_paths = [
            "/sys/fs/cgroup/cpu/cpu.cfs_quota_us",
            "/sys/fs/cgroup/cpu,cpuacct/cpu.cfs_quota_us"
        ]
        period_paths = [
            "/sys/fs/cgroup/cpu/cpu.cfs_period_us",
            "/sys/fs/cgroup/cpu,cpuacct/cpu.cfs_period_us"
        ]

        quota = None
        period = 100000.0

        for qp in quota_paths:
            if os.path.exists(qp):
                try:
                    with open(qp, "r") as f:
                        val = float(f.read().strip())
                        if val > 0:
                            quota = val
                            break
                except Exception:
                    pass

        for pp in period_paths:
            if os.path.exists(pp):
                try:
                    with open(pp, "r") as f:
                        period = float(f.read().strip())
                        break
                except Exception:
                    pass

        if quota is not None and period > 0:
            return quota / period

        return None

    def _detect_virtualization(self) -> bool:
        """Checks CPU flags and DMI tables for hypervisor indicators."""
        # 1. Check /proc/cpuinfo flags
        try:
            with open("/proc/cpuinfo", "r") as f:
                content = f.read()
                if "hypervisor" in content.lower():
                    return True
        except Exception:
            pass

        # 2. Check DMI / sys vendor
        for path in ["/sys/class/dmi/id/sys_vendor", "/sys/class/dmi/id/product_name"]:
            if os.path.exists(path):
                try:
                    with open(path, "r") as f:
                        val = f.read().lower()
                        if any(v in val for v in ["qemu", "kvm", "vmware", "virtualbox", "xen", "amazon", "google"]):
                            return True
                except Exception:
                    pass

        return False

    def _detect_container(self) -> bool:
        """Detects if execution takes place in Docker / LXC container."""
        if os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv"):
            return True
        try:
            with open("/proc/1/cgroup", "r") as f:
                if any(x in f.read().lower() for x in ["docker", "kubepods", "containerd", "lxc"]):
                    return True
        except Exception:
            pass
        return False

    def get_current_system_load(self) -> Tuple[float, float, float]:
        """Returns 1-minute, 5-minute, and 15-minute system load averages."""
        try:
            return os.getloadavg()
        except Exception:
            return (0.0, 0.0, 0.0)

    def calculate_safe_concurrency(self) -> int:
        """Calculates optimal worker count to prevent VPS throttling or host freeze."""
        eff_cores = self.hardware_profile["effective_cores"]

        # Usage multiplier based on governor mode
        if self.mode == GovernorMode.VPS_SAFE:
            factor = 0.70  # Keep 30% headroom for OS, network, databases
        elif self.mode == GovernorMode.BALANCED:
            factor = 0.85  # Keep 15% headroom
        else:
            factor = 1.00  # Max compute

        safe_workers = max(1, int(math.floor(eff_cores * factor)))

        # Also inspect current 1-minute load average: if host is already heavily loaded, throttle back
        load_1m = self.get_current_system_load()[0]
        if load_1m > eff_cores * 0.9 and safe_workers > 1:
            safe_workers = max(1, safe_workers - 1)

        return safe_workers

    def get_status_report(self) -> Dict[str, Any]:
        """Returns comprehensive VPS hardware and governor telemetry."""
        safe_workers = self.calculate_safe_concurrency()
        load = self.get_current_system_load()
        return {
            "mode": self.mode,
            "raw_cpu_cores": self.hardware_profile["raw_cpu_count"],
            "effective_cpu_cores": self.hardware_profile["effective_cores"],
            "cgroup_quota_detected": self.hardware_profile["cgroup_quota_cores"] is not None,
            "is_vps_virtualized": self.hardware_profile["is_virtualized"],
            "is_container": self.hardware_profile["is_container"],
            "system_load_avg_1m": load[0],
            "recommended_safe_workers": safe_workers,
            "headroom_percentage": f"{(1.0 - (safe_workers / self.hardware_profile['effective_cores'])) * 100:.1f}%",
        }


governor = VPSHardwareGovernor()
