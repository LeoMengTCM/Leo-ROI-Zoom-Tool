# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Leo ROI Zoom Tool is a scientific image processing application for creating composite images with zoomed insets. It automatically identifies ROI (Region of Interest) positions using template matching and generates publication-ready figures with guide lines, scale bars, and annotations.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the application
python roi_zoom_gui.py
```

## Architecture

### Two-Module Structure

**roi_zoom_tool_v2.py** - Core processing module
- `find_roi_position()`: OpenCV template matching to locate zoom region in panorama
- `create_zoom_figure()`: Main function that composites panorama + zoom with guide lines
- `draw_scale_bar()`: Renders scale bars with multiple styles (line/ends/ticks)
- `draw_annotation()`: Adds arrows, circles, triangles, stars, text
- `draw_watermark()`: Adds semi-transparent watermarks

**roi_zoom_gui.py** - Tkinter GUI (~2200 lines)
- `ROIZoomGUI`: Main application class
- `PreviewDebouncer`: Delays preview generation to avoid excessive recomputation
- `HistoryManager`: Undo/redo state management
- `CollapsiblePanel`: Expandable UI sections for scale bar, annotations, watermark
- `RatioCalculatorDialog`: Helper to calculate pixels/μm ratio from known scale bars
- `ExportDialog`: Export settings (format, DPI, quality)
- `BatchProcessDialog`: Process multiple image pairs

### Data Flow

1. User selects panorama image + zoom image
2. `find_roi_position()` uses multi-scale template matching to locate zoom region
3. `create_zoom_figure()` composites images with configurable:
   - Position (right/left/top/bottom)
   - Guide lines (solid/dashed)
   - Scale bars (separate settings for panorama and zoom)
   - Annotations and watermarks
4. Result displayed in preview canvas with zoom/pan support
5. Export to PNG/JPEG/TIFF with configurable DPI

### Configuration

Settings persist to `.roi_zoom_config.json` in the project directory. Includes colors, thicknesses, scale bar settings, watermark preferences.
