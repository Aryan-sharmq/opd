"""
Vision Radar - service bootstrap
Builds a fully-wired ApiService from environment variables. No web framework
needed, so this is testable (and usable from scripts/CLIs) on its own.

  VISION_RADAR_DATA_DIR                built-in storage dir  (default: data) - holds the SQLite database,
                                       evidence images and the auto-generated token signing key
  VISION_RADAR_DB                      sqlite file           (default: <data dir>/vision_radar.db; or ":memory:")
  VISION_RADAR_EVIDENCE_DIR            evidence image dir    (default: <data dir>/evidence)
  VISION_RADAR_MODEL_PATH              YOLOv8 .onnx model    (default: unset -> sessions can't start)
  VISION_RADAR_JWT_SECRET              token signing key     (default: generated once and kept in the built-in
                                       storage, so logins survive restarts)
  VISION_RADAR_TOKEN_TTL_SECONDS       token lifetime        (default: 3600)
  VISION_RADAR_ADMIN_USERNAME / _PASSWORD
                                       optional: creates the FIRST administrator, only if no users exist yet.
                                       Without them, the dashboard shows a one-time "create admin" screen.
  VISION_RADAR_EVENT_RETENTION_DAYS    finished-event retention  (default: 30)
  VISION_RADAR_EVIDENCE_RETENTION_DAYS evidence-image retention  (default: 7)

There are deliberately no default credentials: the first administrator is
created either from the two ADMIN variables or, on a fresh install, through
the built-in first-run setup screen (which closes as soon as a user exists).
"""

from __future__ import annotations

import logging
import os
import secrets
from typing import Mapping, Optional

from vision_radar.api.service import ApiService
from vision_radar.data_layer.database import Database
from vision_radar.data_layer.repository import Repository
from vision_radar.data_layer.retention import RetentionPolicy
from vision_radar.monitoring.health import HealthRegistry
from vision_radar.monitoring.performance import PerformanceMonitor
from vision_radar.security.auth import AuthService

logger = logging.getLogger("vision_radar.bootstrap")


def _number(env: Mapping[str, str], key: str, default: float) -> float:
    raw = env.get(key)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{key} must be a number, got {raw!r}")
    if value <= 0:
        raise ValueError(f"{key} must be greater than zero, got {raw!r}")
    return value


def build_service(env: Optional[Mapping[str, str]] = None) -> ApiService:
    env = os.environ if env is None else env

    retention = RetentionPolicy(
        event_retention_days=_number(env, "VISION_RADAR_EVENT_RETENTION_DAYS", 30.0),
        evidence_image_retention_days=_number(env, "VISION_RADAR_EVIDENCE_RETENTION_DAYS", 7.0))
    retention.validate()
    token_ttl = _number(env, "VISION_RADAR_TOKEN_TTL_SECONDS", 3600.0)

    data_dir = env.get("VISION_RADAR_DATA_DIR") or "data"
    db_path = env.get("VISION_RADAR_DB") or os.path.join(data_dir, "vision_radar.db")
    evidence_dir = env.get("VISION_RADAR_EVIDENCE_DIR") or os.path.join(data_dir, "evidence")
    if db_path != ":memory:":
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    os.makedirs(evidence_dir, exist_ok=True)

    health = HealthRegistry()
    database = Database(db_path, health=health)
    logger.info("Using built-in SQLite storage at %s", db_path)
    repo = Repository(database)

    secret = env.get("VISION_RADAR_JWT_SECRET") or None
    if secret is not None and len(secret) < 32:
        raise ValueError("VISION_RADAR_JWT_SECRET must be at least 32 characters")
    if secret is None:
        # Built-in: generate once, keep in the app's own storage so tokens survive restarts.
        secret = repo.get_state("jwt_secret")
        if not secret:
            secret = secrets.token_hex(32)
            repo.set_state("jwt_secret", secret)
    auth = AuthService(repo, secret_key=secret, token_ttl_seconds=token_ttl)

    admin_user, admin_pw = env.get("VISION_RADAR_ADMIN_USERNAME"), env.get("VISION_RADAR_ADMIN_PASSWORD")
    if admin_user and admin_pw:
        if auth.ensure_admin(admin_user, admin_pw) is not None:
            logger.info("Created initial administrator '%s'", admin_user)
    elif repo.user_count() == 0:
        logger.info("No users yet: open the dashboard to create the first administrator.")

    return ApiService(repo, auth, health, PerformanceMonitor(), evidence_dir=evidence_dir,
                      retention=retention, model_path=env.get("VISION_RADAR_MODEL_PATH") or None)
