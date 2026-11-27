"""Compatibility imports: public geometry API moved to meshbuilder.geometry."""
import numpy as np  # Retained for callers instrumenting allocation guards.
from meshbuilder.geometry.model import BundleModel
from meshbuilder.geometry.types import RodData,Subchannel

__all__=["BundleModel","RodData","Subchannel"]
