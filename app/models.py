"""Data models for the application."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import ezdxf

logger = logging.getLogger(__name__)


@dataclass
class LayerInfo:
    """Metadata about a single DXF layer."""
    name: str
    entity_count: int = 0
    color: int = 7  # DXF ACI color index
    is_visible: bool = True


@dataclass
class LayerPreset:
    """A named set of visible layer names."""
    name: str
    visible_layers: set[str] = field(default_factory=set)


@dataclass
class DrawingDocument:
    """Represents a loaded DXF drawing with layer info."""
    file_path: Path
    doc: ezdxf.document.Drawing
    layers: dict[str, LayerInfo] = field(default_factory=dict)

    @classmethod
    def from_dxf(cls, path: Path) -> DrawingDocument:
        """Load a DXF file and extract layer information."""
        doc = ezdxf.readfile(str(path))
        msp = doc.modelspace()

        # Count entities per layer
        entity_counts: dict[str, int] = {}
        for entity in msp:
            try:
                layer = entity.dxf.get("layer", "0")
            except Exception:
                layer = "0"
            entity_counts[layer] = entity_counts.get(layer, 0) + 1

        logger.info("Loaded %s: %d entities across %d layers",
                     path.name, sum(entity_counts.values()), len(entity_counts))

        # Build layer info from layer table
        layers: dict[str, LayerInfo] = {}
        for layer_entry in doc.layers:
            name = layer_entry.dxf.name
            layers[name] = LayerInfo(
                name=name,
                entity_count=entity_counts.get(name, 0),
                color=layer_entry.dxf.get("color", 7),
                is_visible=not layer_entry.is_off(),
            )

        # Include layers that have entities but aren't in the layer table
        for layer_name, count in entity_counts.items():
            if layer_name not in layers:
                layers[layer_name] = LayerInfo(
                    name=layer_name,
                    entity_count=count,
                )

        return cls(file_path=path, doc=doc, layers=layers)

    @property
    def total_entities(self) -> int:
        return sum(li.entity_count for li in self.layers.values())
