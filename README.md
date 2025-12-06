# The Evil Within -  Vibe-Coded Real-Time Radar

I had already written a python script that tracked the player, and enemies. I fed this into Claude, and iterated over until it gave me the script that was "good enough". I am actually well impressed at how much lifting Claude did. This Readme was created by Claude, so take everything in it with a pinch of salt :)

A real-time radar/minimap overlay for *The Evil Within* that reads game memory to display entity positions, health, and facing directions. Built for speedrunners and players who want enhanced situational awareness.

TODO: Make sure the Enemies & Patners are properly defined in the script.

## Features

### Core Functionality
- **Real-Time Entity Tracking**: Displays all game entities including players, enemies, NPCs, and objects
- **Rotating Minimap**: Player-centric view that rotates based on character orientation
- **Distance Calculation**: Shows exact distance to all visible entities
- **Dynamic Range Control**: Zoom in/out to adjust radar coverage (100-5000 units)

### Visual Features
- **Entity Classification**: Color-coded markers for different entity types
  - 🔵 **Blue Triangle**: Player (always centered, pointing forward)
  - 🔴 **Red Circles**: Enemies with health bars
  - 🟡 **Yellow Circles**: NPCs
  - ⚪ **Gray Circles**: Objects
- **Direction Indicators**: Arrows showing which way enemies and NPCs are facing
- **Health Bars**: Real-time health display for enemies
- **Compass Heading**: Shows player's facing direction in degrees
- **Performance Metrics**: Live FPS counter and entity count

### Technical Features
- Handles dynamic memory allocation (entities tracked even when game reallocates memory)
- Validates entity positions to filter out invalid data
- Efficient memory reading with error handling
- 60 FPS update rate for smooth visualization

## Screenshots

```
┌─────────────────────────────────────┐
│  Entities: 23 | Range: 1000         │
│  Player: FOUND                       │
│  Facing: 127.3°                      │
│  FPS: 60                             │
│                                      │
│  Controls:                           │
│  +/= : Zoom in                       │
│  - : Zoom out                        │
│  ESC : Exit                          │
│                                      │
│           ●  ──→                     │
│       ●                              │
│    ○          △                      │
│         ●   ──→                      │
│                                      │
└─────────────────────────────────────┘
```

## Requirements

- **Operating System**: Windows (The Evil Within is Windows-only)
- **Python**: 3.8 or higher
- **Game**: The Evil Within (Steam version)
- **Administrator Rights**: Required for memory access

### Python Dependencies
- `pymem` - Windows memory reading
- `pygame` - Graphics and display

## Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/yourusername/tew-radar.git
   cd tew-radar
   ```

2. **Install dependencies**:
   ```bash
   pip install pymem pygame
   ```

## Usage

### Basic Usage

1. **Launch The Evil Within**
2. **Start the radar** (as Administrator):
   ```bash
   python tew_radar.py
   ```
3. **Load or continue your game**
4. The radar window will appear and begin tracking entities

### Controls

| Key | Action |
|-----|--------|
| `+` or `=` | Zoom in (decrease radar range) |
| `-` | Zoom out (increase radar range) |
| `ESC` | Exit application |

### Understanding the Display

#### Entity Colors
- **Blue Triangle**: Your character (always at center)
- **Red Circles**: Enemies (with health bars above)
- **Yellow Circles**: NPCs and friendly characters
- **Gray Circles**: Interactive objects and items

#### Direction Arrows
Enemies and NPCs display arrows indicating their facing direction relative to the player's orientation.

#### Radar Range
- Default: 1000 units
- Minimum: 100 units
- Maximum: 5000 units
- Adjustable in 100-unit increments

## Configuration

You can modify radar behavior by editing constants in `tew_radar.py`:

```python
# Radar configuration
RADAR_CONFIG = {
    "default_range": 1000,    # Starting zoom level
    "min_range": 100,         # Closest zoom
    "max_range": 5000,        # Farthest zoom
    "range_step": 100,        # Zoom increment
    "fps": 60,                # Update rate
    "width": 800,             # Window width
    "height": 800,            # Window height
}
```

### Adjusting Entity Detection

```python
MAX_ENTITIES = 100  # Increase to track more entities (may impact performance)
```

### Color Customization

```python
COLORS = {
    "background": (20, 20, 30),
    "grid": (40, 40, 50),
    "player": (0, 150, 255),
    "enemy": (255, 50, 50),
    "npc": (255, 200, 50),
    "object": (100, 100, 100),
    "text": (200, 200, 200),
}
```

## Technical Details

### Memory Structure
The radar reads from The Evil Within's memory using reverse-engineered offsets:

- **Base Offset**: `0x01E7AF20` - Entity list pointer
- **Pointer Spacing**: `0x18` - Distance between entity pointers

### Entity Data Structure
Each entity contains:
- **Position**: X, Y, Z coordinates (`0x6C8`, `0x6CC`, `0x6D0`)
- **Rotation**: Cosine and Sine values (`0x6D4`, `0x6E0`)
- **Health**: Float value (`0x8C4`)
- **Class Name**: String identifier via pointer (`+0x18` → `+0xA4`)
- **Instance Name**: String identifier via pointer (`+0x08` → `+0x00`)

For complete technical documentation, see [TECHNICAL.md](TECHNICAL.md).

## How It Works

1. **Process Attachment**: Attaches to `EvilWithin.exe` using pymem
2. **Memory Reading**: Scans entity list at base offset + module base
3. **Entity Classification**: Determines entity type from class names and health values
4. **Coordinate Transformation**: Converts world coordinates to player-relative radar space
5. **Rotation Handling**: Applies player rotation matrix to keep player facing "up"
6. **Rendering**: Draws entities using pygame with appropriate colors and indicators


## Limitations

- **Windows Only**: Uses Windows-specific memory reading APIs
- **EPIC Version**: Memory offsets are for the EPIC version of the game


## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.



## Support

This is unsupported. Please fork and develop to you heart's content!

---

**Disclaimer**: This tool is for educational and personal use. The author is not responsible for any consequences of using this software, including potential conflicts with game terms of service.
