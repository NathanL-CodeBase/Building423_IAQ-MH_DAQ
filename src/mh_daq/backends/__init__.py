"""Acquisition backends for the MH DAQ system.

The base interface is shared by the simulation backend and the real nidaqmx
backend so the daemon code is identical on the dev box and the DAQ PC.
"""

from .base import AcquisitionBackend, BackendError
from .simulation import SimulationBackend

# The real backend imports nidaqmx, which is present but only fully functional
# with the NI driver. Import lazily so the package still loads on machines
# without the driver (the simulator path stays usable).
try:
    from .nidaqmx_backend import NiDaqmxBackend
except Exception:  # noqa: BLE001
    NiDaqmxBackend = None

__all__ = [
    "AcquisitionBackend",
    "BackendError",
    "SimulationBackend",
    "NiDaqmxBackend",
]
