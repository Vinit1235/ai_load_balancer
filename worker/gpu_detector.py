"""
GPU detection and monitoring for NVIDIA GPUs
"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class GPUInfo:
    """GPU information container"""
    available: bool
    name: Optional[str] = None
    memory_total_mb: int = 0
    memory_used_mb: int = 0
    utilization_percent: int = 0
    temperature: int = 0


def detect_gpu() -> GPUInfo:
    """
    Detect NVIDIA GPU using pynvml
    
    Returns:
        GPUInfo object with GPU metrics or available=False if no GPU
    """
    try:
        import pynvml
        
        pynvml.nvmlInit()
        device_count = pynvml.nvmlDeviceGetCount()
        
        if device_count == 0:
            logger.info("No NVIDIA GPUs detected")
            return GPUInfo(available=False)
        
        # Use first GPU (index 0)
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        
        # Get device name
        name = pynvml.nvmlDeviceGetName(handle)
        if isinstance(name, bytes):
            name = name.decode('utf-8')
        
        # Get memory info
        memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
        
        # Get utilization rates
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        
        # Get temperature
        temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
        
        gpu_info = GPUInfo(
            available=True,
            name=name,
            memory_total_mb=memory.total // (1024 ** 2),
            memory_used_mb=memory.used // (1024 ** 2),
            utilization_percent=util.gpu,
            temperature=temp
        )
        
        logger.info(f"GPU detected: {gpu_info.name}")
        return gpu_info
    
    except ImportError:
        logger.debug("pynvml not installed, GPU monitoring disabled")
        return GPUInfo(available=False)
    
    except Exception as e:
        logger.warning(f"GPU detection failed: {e}")
        return GPUInfo(available=False)


def get_gpu_metrics() -> dict:
    """
    Get current GPU metrics as a dictionary
    
    Returns:
        Dictionary with GPU metrics
    """
    gpu_info = detect_gpu()
    
    return {
        "available": gpu_info.available,
        "name": gpu_info.name if gpu_info.available else None,
        "utilization": gpu_info.utilization_percent,
        "memory_used_mb": gpu_info.memory_used_mb,
        "memory_total_mb": gpu_info.memory_total_mb,
        "temperature": gpu_info.temperature
    }
