"""rs-sdk synchronous scripting API backed by Bot Scape's local gateway.

Only low-level send_* methods acknowledge queueing. High-level methods wait
for snapshot evidence. Unsupported features return failed Results explicitly.
"""
from ._codec import RSObject, Result, Pattern, decode
from ._client import (SyncClient, connect_sync, RSError, StaleEntityError,
                      FeatureUnavailable, configure_script)

__all__ = ["SyncClient", "connect_sync", "RSObject", "Result", "Pattern",
           "RSError", "StaleEntityError", "FeatureUnavailable"]
