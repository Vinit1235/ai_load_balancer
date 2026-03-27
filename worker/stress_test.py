"""
Synthetic stress generator for testing and demos
"""

import subprocess
import platform
import multiprocessing
import time
import logging
from typing import Literal

logger = logging.getLogger(__name__)

StressProfile = Literal["light", "medium", "heavy"]


def generate_cpu_load(cores: int = 2, duration_sec: int = 30) -> bool:
    """
    Generate CPU load using stress-ng or fallback
    
    Args:
        cores: Number of CPU cores to stress
        duration_sec: Duration in seconds
    
    Returns:
        True if successful
    """
    try:
        if platform.system() == "Linux":
            # Use stress-ng on Linux
            cmd = ["stress-ng", "--cpu", str(cores), "--timeout", f"{duration_sec}s"]
            logger.info(f"Running stress-ng with {cores} cores for {duration_sec}s")
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                logger.info("CPU stress completed successfully")
                return True
            else:
                logger.error(f"stress-ng failed: {result.stderr}")
                return False
        
        else:
            # Fallback for Windows/macOS
            logger.info(f"Using Python CPU burn (stress-ng not available on {platform.system()})")
            return _python_cpu_burn(cores, duration_sec)
    
    except FileNotFoundError:
        logger.warning("stress-ng not installed, using Python fallback")
        return _python_cpu_burn(cores, duration_sec)
    except Exception as e:
        logger.error(f"CPU stress generation failed: {e}")
        return False


def _python_cpu_burn(cores: int, duration_sec: int) -> bool:
    """Pure Python CPU burning"""
    def burn_cpu():
        """Worker function for CPU burning"""
        end_time = time.time() + duration_sec
        while time.time() < end_time:
            # Intensive calculation
            _ = sum([i**2 for i in range(100000)])
    
    processes = []
    for _ in range(cores):
        p = multiprocessing.Process(target=burn_cpu)
        p.start()
        processes.append(p)
    
    for p in processes:
        p.join()
    
    logger.info(f"Python CPU burn completed ({cores} cores, {duration_sec}s)")
    return True


def generate_memory_pressure(mb: int = 500, duration_sec: int = 30) -> bool:
    """
    Generate memory pressure
    
    Args:
        mb: Memory to allocate in MB
        duration_sec: How long to hold the memory
    
    Returns:
        True if successful
    """
    try:
        import numpy as np
        
        logger.info(f"Allocating {mb}MB of memory for {duration_sec}s")
        
        # Allocate memory (8 bytes per float64)
        array_size = (mb * 1024 * 1024) // 8
        data = np.random.rand(array_size)
        
        # Hold for duration
        time.sleep(duration_sec)
        
        # Explicitly delete
        del data
        
        logger.info("Memory pressure released")
        return True
    
    except Exception as e:
        logger.error(f"Memory pressure generation failed: {e}")
        return False


def generate_io_load(mb_per_sec: int = 10, duration_sec: int = 30) -> bool:
    """
    Generate I/O load by writing/reading files
    
    Args:
        mb_per_sec: MB to write per second
        duration_sec: Duration in seconds
    
    Returns:
        True if successful
    """
    import tempfile
    import os
    
    try:
        logger.info(f"Generating I/O load: {mb_per_sec}MB/s for {duration_sec}s")
        
        chunk_size = mb_per_sec * 1024 * 1024  # Convert to bytes
        end_time = time.time() + duration_sec
        
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name
            
            while time.time() < end_time:
                # Write random data
                data = os.urandom(chunk_size)
                tmp.write(data)
                tmp.flush()
                os.fsync(tmp.fileno())
                
                time.sleep(1)  # Wait 1 second between writes
        
        # Clean up
        os.unlink(tmp_path)
        
        logger.info("I/O load completed")
        return True
    
    except Exception as e:
        logger.error(f"I/O load generation failed: {e}")
        return False


def generate_mixed_load(profile: StressProfile = "medium") -> bool:
    """
    Generate combined CPU, memory, and I/O load based on profile
    
    Args:
        profile: "light", "medium", or "heavy"
    
    Returns:
        True if successful
    """
    profiles = {
        "light": {
            "cores": 2,
            "memory_mb": 200,
            "duration": 30
        },
        "medium": {
            "cores": 4,
            "memory_mb": 500,
            "duration": 60
        },
        "heavy": {
            "cores": max(multiprocessing.cpu_count() - 1, 1),
            "memory_mb": 1000,
            "duration": 90
        }
    }
    
    if profile not in profiles:
        logger.error(f"Invalid profile: {profile}")
        return False
    
    config = profiles[profile]
    
    logger.info(f"Starting {profile} mixed load: {config}")
    
    # Start CPU load in background
    cpu_process = multiprocessing.Process(
        target=generate_cpu_load,
        args=(config["cores"], config["duration"])
    )
    cpu_process.start()
    
    # Start memory pressure in background
    mem_process = multiprocessing.Process(
        target=generate_memory_pressure,
        args=(config["memory_mb"], config["duration"])
    )
    mem_process.start()
    
    # Wait for completion
    cpu_process.join()
    mem_process.join()
    
    logger.info(f"{profile.capitalize()} mixed load completed")
    return True


if __name__ == "__main__":
    import argparse
    
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    parser = argparse.ArgumentParser(description="Generate synthetic system load")
    parser.add_argument("--type", choices=["cpu", "memory", "io", "mixed"], default="mixed",
                       help="Type of load to generate")
    parser.add_argument("--profile", choices=["light", "medium", "heavy"], default="medium",
                       help="Load profile for mixed load")
    parser.add_argument("--cores", type=int, default=2, help="CPU cores for CPU load")
    parser.add_argument("--duration", type=int, default=30, help="Duration in seconds")
    parser.add_argument("--memory-mb", type=int, default=500, help="Memory to allocate in MB")
    parser.add_argument("--io-mb-per-sec", type=int, default=10, help="I/O throughput in MB/s")
    
    args = parser.parse_args()
    
    if args.type == "cpu":
        generate_cpu_load(args.cores, args.duration)
    elif args.type == "memory":
        generate_memory_pressure(args.memory_mb, args.duration)
    elif args.type == "io":
        generate_io_load(args.io_mb_per_sec, args.duration)
    elif args.type == "mixed":
        generate_mixed_load(args.profile)
