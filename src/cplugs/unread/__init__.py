
from src.cplugs.sdk import CplugDefinition, load_manifest

CPLUG = CplugDefinition(manifest=load_manifest(__file__))

__all__ = ["CPLUG"]
