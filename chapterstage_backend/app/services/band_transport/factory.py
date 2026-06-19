"""Factory for selecting offline or live Band transports."""
from __future__ import annotations

from .base import BandTransportConfig, BandTransportConfigError
from .test_transport import TestBandTransport


def create_transport(mode: str | None = None):
    config = BandTransportConfig.from_env(mode)
    if config.mode == "test":
        return TestBandTransport()
    if config.mode == "live":
        from .sdk_transport import BandSdkTransport
        return BandSdkTransport(config)
    raise BandTransportConfigError(
        "BAND_TRANSPORT_MODE must be 'test' or 'live' (got %r)." % config.mode)


def create_band_service(mode: str | None = None):
    from band_service import BandService
    return BandService(transport=create_transport(mode))
