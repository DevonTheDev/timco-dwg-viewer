"""Export a filtered DXF with only visible layers."""

from __future__ import annotations

import logging
from pathlib import Path

import ezdxf

logger = logging.getLogger(__name__)


def export_filtered_dxf(
    source_path: Path,
    output_path: Path,
    visible_layers: set[str],
) -> None:
    """Load a fresh copy of the DXF, remove non-visible entities, and save.

    Args:
        source_path: Path to the original DXF file.
        output_path: Path to write the filtered DXF.
        visible_layers: Set of layer names to keep.
    """
    doc = ezdxf.readfile(str(source_path))
    msp = doc.modelspace()

    # Delete entities not on visible layers
    to_delete = [
        entity for entity in msp
        if entity.dxf.get("layer", "0") not in visible_layers
    ]
    for entity in to_delete:
        msp.delete_entity(entity)

    # Turn off non-visible layers in the layer table
    for layer in doc.layers:
        if layer.dxf.name not in visible_layers:
            layer.off()

    doc.saveas(str(output_path))
    logger.info("Exported %s: kept %d layers, removed %d entities",
                output_path.name, len(visible_layers), len(to_delete))


def export_all_layers(source_path: Path, output_path: Path) -> None:
    """Save a clean copy of the DXF with all layers intact."""
    doc = ezdxf.readfile(str(source_path))
    doc.saveas(str(output_path))
    logger.info("Exported %s with all layers", output_path.name)


def suggest_output_path(source_path: Path) -> Path:
    """Suggest a default output path for the filtered DXF."""
    return source_path.parent / f"{source_path.stem}_filtered.dxf"
