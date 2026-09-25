"""Acquisition backends for the MH DAQ system.

The base interface is shared by the simulation backend and the real nidaqmx
backend so the daemon code is identical on the dev box and the DAQ PC.
"""

from .base import AcquisitionBackend, BackendError
from .simulation import SimulationBackend

__all__ = ["AcquisitionBackend", "BackendError", "SimulationBackend"]
