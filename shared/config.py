"""
Configuration management using Pydantic settings
"""

from pydantic_settings import BaseSettings
from typing import Literal


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Master Node
    MASTER_HOST: str = "192.168.1.100"
    MASTER_PORT: int = 8000
    RAY_HEAD_PORT: int = 6379
    
    # MinIO Storage
    MINIO_ENDPOINT: str = "192.168.1.100:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "checkpoints"
    
    # Database
    DATABASE_PATH: str = "cluster_state.db"
    
    # Dashboard
    DASHBOARD_PASSWORD: str = "capstone2026"
    
    # Scheduler Settings
    FORCE_HEURISTIC: int = 0
    AI_MIN_SAMPLES: int = 50
    CHECKPOINT_INTERVAL: int = 30
    
    # Thresholds
    OVERLOAD_CPU_THRESHOLD: int = 85
    OVERLOAD_THERMAL_THRESHOLD: int = 80
    OVERLOAD_DURATION_SEC: int = 3
    
    # LLM Configuration
    LLM_PROVIDER: Literal["gemini", "grok", "openai"] = "gemini"
    GEMINI_API_KEY: str = ""
    GROK_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    LLM_MODEL: str = "gemini-2.0-flash"
    LLM_MAX_TOKENS: int = 1024
    LLM_TEMPERATURE: float = 0.3
    
    class Config:
        env_file = ".env"
        case_sensitive = True


# Singleton instance
settings = Settings()


def get_master_url() -> str:
    """Get the master node URL"""
    return f"http://{settings.MASTER_HOST}:{settings.MASTER_PORT}"


def get_ray_address() -> str:
    """Get the Ray cluster address"""
    return f"{settings.MASTER_HOST}:{settings.RAY_HEAD_PORT}"


def is_heuristic_mode() -> bool:
    """Check if forced to heuristic mode"""
    return bool(settings.FORCE_HEURISTIC)
