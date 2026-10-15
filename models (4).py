"""
Vision Radar - Video Ingestion Layer
Shared data models and enums.

Spec reference: PDF Section 4 (Video ingestion layer)
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np


class CameraStatus(str, Enum):
    """Lifecycle status of a video source connection."""
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"
    ERROR = "ERROR"


class SessionState(str, Enum):
    """Lifecycle status of an ingestion session."""
    IDLE = "IDLE"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


@dataclass
class VideoSourceConfig:
    """Configuration for a video source. Source-independent by design (Section 4)."""
    source_uri: str            # device index ("0"), file path, or stream URL
    target_fps: Optional[float] = None   # None = use source's native fps
    target_width: Optional[int] = None   # None = use source's native resolution
    target_height: Optional[int] = None
    max_reconnect_attempts: int = 5
    reconnect_backoff_seconds: float = 1.0  # multiplied by attempt number


@dataclass
class Frame:
    """A single acquired frame with ingestion metadata."""
    session_id: str
    frame_id: int
    image: np.ndarray
    captured_at: float          # epoch seconds, set at acquisition time
    width: int
    height: int

    @property
    def shape(self) -> tuple:
        return self.image.shape


@dataclass
class SourceHealth:
    """Live health snapshot of a video source, used by the dashboard (Section 27)."""
    status: CameraStatus = CameraStatus.DISCONNECTED
    fps_actual: float = 0.0
    frames_read: int = 0
    frames_dropped: int = 0
    reconnect_attempts: int = 0
    last_frame_at: Optional[float] = None
    last_error: Optional[str] = None


@dataclass
class SessionInfo:
    """Persisted/queryable representation of an ingestion session (Section 23 - Data architecture)."""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    camera_uri: str = ""
    state: SessionState = SessionState.IDLE
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    frame_count: int = 0
    error_message: Optional[str] = None

    def duration_seconds(self) -> Optional[float]:
        if self.started_at is None:
            return None
        end = self.ended_at if self.ended_at is not None else time.time()
        return end - self.started_at
