"""
MinIO client wrapper for checkpoint storage with retry logic
"""

from minio import Minio
from minio.error import S3Error
import io
import pickle
import zlib
import logging
from typing import Optional, List, Any
from shared.config import settings
import time

logger = logging.getLogger(__name__)


class MinIOClient:
    """Wrapper for MinIO operations with error handling and retries"""
    
    def __init__(self):
        self.endpoint = settings.MINIO_ENDPOINT
        self.access_key = settings.MINIO_ACCESS_KEY
        self.secret_key = settings.MINIO_SECRET_KEY
        self.bucket = settings.MINIO_BUCKET
        self.client = None
        self.init_minio()
    
    def init_minio(self):
        """Initialize MinIO client and create bucket if needed"""
        try:
            # Remove http:// prefix if present
            endpoint = self.endpoint.replace("http://", "").replace("https://", "")
            
            self.client = Minio(
                endpoint,
                access_key=self.access_key,
                secret_key=self.secret_key,
                secure=False  # Use HTTP for local development
            )
            
            # Create bucket if it doesn't exist
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
                logger.info(f"Created MinIO bucket: {self.bucket}")
            else:
                logger.info(f"Connected to MinIO bucket: {self.bucket}")
        
        except S3Error as e:
            logger.error(f"MinIO initialization error: {e}")
            raise
    
    def _retry_operation(self, operation, *args, max_retries=3, delay=1, **kwargs):
        """Retry an operation with exponential backoff"""
        for attempt in range(max_retries):
            try:
                return operation(*args, **kwargs)
            except S3Error as e:
                if attempt == max_retries - 1:
                    raise
                logger.warning(f"MinIO operation failed (attempt {attempt + 1}/{max_retries}): {e}")
                time.sleep(delay * (2 ** attempt))  # Exponential backoff
    
    def save_checkpoint(self, task_id: str, state: Any) -> bool:
        """
        Save task checkpoint to MinIO
        
        Args:
            task_id: Unique task identifier
            state: Task state (will be pickled)
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Serialize state
            state_bytes = pickle.dumps(state)
            
            # Calculate CRC32 for validation
            crc32 = zlib.crc32(state_bytes)
            
            # Add CRC32 to metadata
            metadata = {"crc32": str(crc32)}
            
            # Upload to MinIO
            object_name = f"{task_id}.ckpt"
            data_stream = io.BytesIO(state_bytes)
            
            self._retry_operation(
                self.client.put_object,
                self.bucket,
                object_name,
                data_stream,
                length=len(state_bytes),
                metadata=metadata
            )
            
            logger.info(f"Saved checkpoint for task {task_id} ({len(state_bytes)} bytes)")
            return True
        
        except Exception as e:
            logger.error(f"Failed to save checkpoint for task {task_id}: {e}")
            return False
    
    def get_checkpoint(self, task_id: str) -> Optional[Any]:
        """
        Retrieve task checkpoint from MinIO
        
        Args:
            task_id: Unique task identifier
        
        Returns:
            Deserialized state or None if not found or corrupted
        """
        try:
            object_name = f"{task_id}.ckpt"
            
            # Download from MinIO
            response = self._retry_operation(
                self.client.get_object,
                self.bucket,
                object_name
            )
            
            state_bytes = response.read()
            response.close()
            response.release_conn()
            
            # Validate CRC32 if available
            if not self.validate_checkpoint_data(task_id, state_bytes):
                logger.warning(f"Checkpoint for task {task_id} failed CRC32 validation")
                return None
            
            # Deserialize
            state = pickle.loads(state_bytes)
            logger.info(f"Loaded checkpoint for task {task_id}")
            return state
        
        except S3Error as e:
            if e.code == "NoSuchKey":
                logger.debug(f"No checkpoint found for task {task_id}")
            else:
                logger.error(f"Error loading checkpoint for task {task_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to deserialize checkpoint for task {task_id}: {e}")
            return None
    
    def delete_checkpoint(self, task_id: str) -> bool:
        """
        Delete task checkpoint from MinIO
        
        Args:
            task_id: Unique task identifier
        
        Returns:
            True if successful, False otherwise
        """
        try:
            object_name = f"{task_id}.ckpt"
            
            self._retry_operation(
                self.client.remove_object,
                self.bucket,
                object_name
            )
            
            logger.info(f"Deleted checkpoint for task {task_id}")
            return True
        
        except S3Error as e:
            if e.code == "NoSuchKey":
                logger.debug(f"Checkpoint for task {task_id} doesn't exist")
                return True  # Already deleted
            logger.error(f"Failed to delete checkpoint for task {task_id}: {e}")
            return False
    
    def list_checkpoints(self) -> List[str]:
        """
        List all checkpoints in the bucket
        
        Returns:
            List of task IDs
        """
        try:
            objects = self.client.list_objects(self.bucket, recursive=True)
            task_ids = [obj.object_name.replace(".ckpt", "") for obj in objects]
            return task_ids
        except S3Error as e:
            logger.error(f"Failed to list checkpoints: {e}")
            return []
    
    def validate_checkpoint(self, task_id: str) -> bool:
        """
        Validate checkpoint integrity using CRC32
        
        Args:
            task_id: Unique task identifier
        
        Returns:
            True if valid, False otherwise
        """
        try:
            object_name = f"{task_id}.ckpt"
            
            # Get object metadata and data
            response = self.client.get_object(self.bucket, object_name)
            state_bytes = response.read()
            response.close()
            response.release_conn()
            
            return self.validate_checkpoint_data(task_id, state_bytes)
        
        except S3Error:
            return False
    
    def validate_checkpoint_data(self, task_id: str, state_bytes: bytes) -> bool:
        """Validate checkpoint data using CRC32"""
        try:
            object_name = f"{task_id}.ckpt"
            
            # Get stored CRC32 from metadata
            stat = self.client.stat_object(self.bucket, object_name)
            if not stat.metadata or "crc32" not in stat.metadata:
                logger.debug(f"No CRC32 metadata for task {task_id}")
                return True  # No validation metadata, assume valid
            
            stored_crc32 = int(stat.metadata["crc32"])
            calculated_crc32 = zlib.crc32(state_bytes)
            
            return stored_crc32 == calculated_crc32
        
        except Exception as e:
            logger.error(f"CRC32 validation error for task {task_id}: {e}")
            return False
    
    def get_checkpoint_size(self, task_id: str) -> int:
        """
        Get checkpoint size in bytes
        
        Args:
            task_id: Unique task identifier
        
        Returns:
            Size in bytes or 0 if not found
        """
        try:
            object_name = f"{task_id}.ckpt"
            stat = self.client.stat_object(self.bucket, object_name)
            return stat.size
        except S3Error:
            return 0


# Singleton instance
minio_client = MinIOClient()
