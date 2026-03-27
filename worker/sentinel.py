"""
Worker node health monitoring and heartbeat system
"""

import psutil
import asyncio
import httpx
import logging
import argparse
import platform
from datetime import datetime
from pathlib import Path
from typing import Optional
from worker.gpu_detector import get_gpu_metrics
from shared.config import settings

logger = logging.getLogger(__name__)


class HealthSentinel:
    """Monitors worker node health and sends heartbeats to master"""
    
    def __init__(self, master_url: str, node_id: str, node_name: str):
        self.master_url = master_url
        self.node_id = node_id
        self.node_name = node_name
        self.overload_timer: Optional[float] = None
        
        # Thresholds from config
        self.cpu_threshold = settings.OVERLOAD_CPU_THRESHOLD
        self.thermal_threshold = settings.OVERLOAD_THERMAL_THRESHOLD
        self.duration_threshold = settings.OVERLOAD_DURATION_SEC
        
        # Get local IP
        self.ip = self._get_local_ip()
        
        logger.info(f"HealthSentinel initialized for {node_name} ({node_id})")
    
    def _get_local_ip(self) -> str:
        """Get local IP address"""
        import socket
        try:
            # Connect to master to determine which interface to use
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((settings.MASTER_HOST, settings.MASTER_PORT))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"
    
    def get_cpu_percent(self) -> float:
        """Get CPU utilization percentage"""
        return psutil.cpu_percent(interval=0.5)
    
    def get_ram_percent(self) -> float:
        """Get RAM utilization percentage"""
        return psutil.virtual_memory().percent
    
    def get_thermal(self) -> float:
        """
        Get system temperature in Celsius
        
        Returns:
            Temperature or 0 if unavailable
        """
        try:
            # Linux-specific thermal zone
            if platform.system() == "Linux":
                thermal_zone = Path("/sys/class/thermal/thermal_zone0/temp")
                if thermal_zone.exists():
                    temp_millidegrees = int(thermal_zone.read_text().strip())
                    return temp_millidegrees / 1000.0
            
            # Windows - use WMI if available
            elif platform.system() == "Windows":
                try:
                    import wmi
                    w = wmi.WMI(namespace="root\\wmi")
                    temperature_info = w.MSAcpi_ThermalZoneTemperature()[0]
                    # Convert from tenths of Kelvin to Celsius
                    temp_kelvin = temperature_info.CurrentTemperature / 10.0
                    return temp_kelvin - 273.15
                except ImportError:
                    logger.debug("WMI not available for thermal monitoring on Windows")
                    return 0
            
            # Fallback: try psutil sensors (Linux/macOS)
            if hasattr(psutil, "sensors_temperatures"):
                temps = psutil.sensors_temperatures()
                if temps:
                    # Get first available temperature sensor
                    for name, entries in temps.items():
                        if entries:
                            return entries[0].current
            
            return 0
        
        except Exception as e:
            logger.debug(f"Thermal reading failed: {e}")
            return 0
    
    def get_active_task_count(self) -> int:
        """Get number of active tasks (placeholder - will be updated by executor)"""
        # This will be updated by the task executor
        # For now, return estimate based on CPU usage
        cpu = self.get_cpu_percent()
        if cpu > 80:
            return 3
        elif cpu > 50:
            return 2
        elif cpu > 20:
            return 1
        return 0
    
    def is_overloaded(self, cpu: float, thermal: float) -> bool:
        """
        Check if node is overloaded
        
        Args:
            cpu: CPU usage percentage
            thermal: Temperature in Celsius
        
        Returns:
            True if overloaded for sustained period
        """
        import time
        
        # Check if both CPU and thermal exceed thresholds
        if cpu > self.cpu_threshold and thermal > self.thermal_threshold:
            if self.overload_timer is None:
                # Start timer
                self.overload_timer = time.time()
                logger.warning(f"Overload detected: CPU={cpu:.1f}%, Temp={thermal:.1f}°C")
                return False
            else:
                # Check if sustained for threshold duration
                elapsed = time.time() - self.overload_timer
                if elapsed > self.duration_threshold:
                    logger.error(f"Sustained overload for {elapsed:.1f}s! Requesting drain.")
                    return True
                return False
        else:
            # Reset timer if conditions improve
            if self.overload_timer is not None:
                logger.info("Overload condition cleared")
            self.overload_timer = None
            return False
    
    async def send_heartbeat(self) -> bool:
        """
        Send heartbeat with metrics to master
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Collect metrics
            cpu = self.get_cpu_percent()
            ram = self.get_ram_percent()
            thermal = self.get_thermal()
            gpu_metrics = get_gpu_metrics()
            active_tasks = self.get_active_task_count()
            
            # Build heartbeat payload
            payload = {
                "node_id": self.node_id,
                "name": self.node_name,
                "ip": self.ip,
                "status": "HEALTHY",
                "cpu": round(cpu, 2),
                "ram": round(ram, 2),
                "thermal": round(thermal, 2),
                "gpu_available": gpu_metrics["available"],
                "gpu_utilization": gpu_metrics["utilization"],
                "gpu_memory_used_mb": gpu_metrics["memory_used_mb"],
                "gpu_temperature": gpu_metrics["temperature"],
                "active_tasks": active_tasks,
                "timestamp": datetime.now().isoformat()
            }
            
            # Send to master
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    f"{self.master_url}/api/v1/nodes/heartbeat",
                    json=payload
                )
                response.raise_for_status()
            
            # Check for overload
            if self.is_overloaded(cpu, thermal):
                await self.request_drain()
            
            return True
        
        except httpx.HTTPStatusError as e:
            logger.error(f"Heartbeat failed with HTTP {e.response.status_code}: {e}")
            return False
        except Exception as e:
            logger.error(f"Heartbeat failed: {e}")
            return False
    
    async def request_drain(self):
        """Request master to drain this node"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.master_url}/api/v1/control/drain/{self.node_id}",
                    json={"reason": "thermal_overload"}
                )
                response.raise_for_status()
                logger.info("Drain request sent to master")
        except Exception as e:
            logger.error(f"Failed to request drain: {e}")
    
    async def run(self):
        """Main monitoring loop"""
        logger.info(f"Starting health monitoring for {self.node_name}")
        logger.info(f"Master URL: {self.master_url}")
        logger.info(f"Thresholds: CPU={self.cpu_threshold}%, Thermal={self.thermal_threshold}°C, Duration={self.duration_threshold}s")
        
        while True:
            try:
                await self.send_heartbeat()
                await asyncio.sleep(1)  # Send heartbeat every second
            except KeyboardInterrupt:
                logger.info("Health sentinel stopped by user")
                break
            except Exception as e:
                logger.error(f"Unexpected error in monitoring loop: {e}")
                await asyncio.sleep(5)  # Back off on errors


async def main():
    """Entry point for sentinel"""
    parser = argparse.ArgumentParser(description="Worker node health sentinel")
    parser.add_argument("--master-url", default=f"http://{settings.MASTER_HOST}:{settings.MASTER_PORT}",
                       help="Master node URL")
    parser.add_argument("--node-name", required=True, help="Node name (e.g., worker-1)")
    parser.add_argument("--node-id", help="Node ID (defaults to node-name)")
    
    args = parser.parse_args()
    
    node_id = args.node_id or args.node_name
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    sentinel = HealthSentinel(
        master_url=args.master_url,
        node_id=node_id,
        node_name=args.node_name
    )
    
    await sentinel.run()


if __name__ == "__main__":
    asyncio.run(main())
