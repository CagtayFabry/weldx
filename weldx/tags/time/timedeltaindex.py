from typing import List

import numpy as np
import pandas as pd
from asdf.tagged import TaggedDict

from weldx.asdf.types import WeldxConverter

__all__ = ["TimedeltaIndexConverter"]


class TimedeltaIndexConverter(WeldxConverter):
    """A simple implementation of serializing pandas TimedeltaIndex."""

    name = "time/timedeltaindex"
    version = "1.0.0"
    types = [pd.TimedeltaIndex]

    def to_yaml_tree(self, obj: pd.TimedeltaIndex, tag: str, ctx) -> dict:
        """Convert to python dict."""
        tree = {}
        if obj.inferred_freq is not None:
            tree["freq"] = obj.inferred_freq
        else:
            tree["values"] = obj.values.astype(np.int64)

        tree["start"] = obj[0]
        tree["end"] = obj[-1]
        tree["min"] = obj.min()
        tree["max"] = obj.max()

        return tree

    def from_yaml_tree(self, node: dict, tag: str, ctx):
        """Construct TimedeltaIndex from tree."""
        if "freq" in node:
            return pd.timedelta_range(
                start=node["start"], end=node["end"], freq=node["freq"]
            )
        values = node["values"]
        return pd.TimedeltaIndex(values)

    @staticmethod
    def shape_from_tagged(tree: TaggedDict) -> List[int]:
        """Calculate the shape (length of TDI) from static tagged tree instance."""
        if "freq" in tree:
            tdi_temp = pd.timedelta_range(
                start=tree["start"]["value"],
                end=tree["end"]["value"],
                freq=tree["freq"],
            )
            return [len(tdi_temp)]
        return tree["values"]["shape"]
