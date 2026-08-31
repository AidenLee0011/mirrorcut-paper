# -*- coding: utf-8 -*-
"""mirrorcut - which parts of your agent harness earn their place.

Every run travels with its mirror. What survives the pair is the effect of the component;
what does not survive is the interaction, the task difficulty, and the baseline.
"""
from .core import MirrorScreen, UnpairedScreen, ACTIVE, ADMITTED, PRUNED, RETIRED, PINNED
from .choose import pairing_gain, shrunk_rates

__all__ = ["MirrorScreen", "UnpairedScreen", "pairing_gain", "shrunk_rates", "ACTIVE", "ADMITTED", "PRUNED", "RETIRED", "PINNED"]
__version__ = "0.4.0"
