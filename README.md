# Edge Zone Navigation (Exocad-style) for Blender

This Blender addon adds interactive zones on the edges of the 3D Viewport, allowing you to rotate and pan the camera by simply dragging the mouse near the edges, similar to navigation in Exocad software.

## Features

- **Roll Zone (Right Edge):** Click and drag vertically on the right edge of the viewport to roll the camera view.
- **Vertical Pan Zone (Left Edge):** Click and drag vertically on the left edge to pan the camera up and down.
- **Horizontal Pan Zone (Bottom Edge):** Click and drag horizontally on the bottom edge to pan the camera left and right.
- **Visual Feedback:** Zones light up when active (customizable colors).
- **Cursor Warping:** Allows continuous dragging without hitting the screen edge.
- **Customizable:** Adjust zone width, sensitivity, opacity, and invert directions.
- **Auto-Start:** Can be set to start automatically with Blender.

## Installation

1. Download the `Edge_Zone_Navigation.py` file.
2. Open Blender.
3. Go to `Edit > Preferences > Add-ons`.
4. Click `Install...` and select the downloaded file.
5. Enable the addon by checking the box next to "3D View: Edge Zone Navigation".

## Usage

1. By default, the addon starts automatically. If not, you can start it via the **View** menu in the 3D Viewport (`View > Start Edge Zone Navigation`) or from the Sidebar (N-Panel) > **View** tab.
2. Move your mouse to the right edge of the 3D view. You will see a highlighted zone.
3. **Right-Click and Drag** in the zone to rotate/roll the view.
4. Use the Left and Bottom edges to Pan the view.

## Preferences

You can configure the addon in `Edit > Preferences > Add-ons` or quickly access settings in the N-Panel > View > Edge Zone Navigation.

- **Zone Color/Opacity:** Change the visual appearance of the zones.
- **Sensitivity:** Adjust how fast the camera moves.
- **Zone Width/Thickness:** Adjust how large the active area is.
- **Invert Axes:** Reverse the direction of movement if desired.

## Requirements

- Blender 3.3 or higher.

## License

MIT License
