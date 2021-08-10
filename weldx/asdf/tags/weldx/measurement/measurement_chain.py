from weldx.asdf.types import WeldxConverter
from weldx.measurement import MeasurementChain

__all__ = [
    "MeasurementChain",
    "MeasurementChainConverter",
]


class MeasurementChainConverter(WeldxConverter):
    """Serialization class for measurement chains"""

    name = "measurement/measurement_chain"
    version = "1.0.0"
    types = [MeasurementChain]
    requires = ["weldx"]
    handle_dynamic_subclasses = True

    @classmethod
    def to_tree(cls, node: MeasurementChain, ctx):
        return node.to_dict()

    @classmethod
    def from_tree(cls, tree, ctx) -> MeasurementChain:
        return MeasurementChain.from_dict(tree)
