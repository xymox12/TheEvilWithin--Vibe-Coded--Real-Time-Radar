# Technical Documentation

In-depth technical documentation for developers and advanced users interested in how the TEW Radar works.

## Table of Contents
- [Architecture Overview](#architecture-overview)
- [Memory Structure](#memory-structure)
- [Entity Detection](#entity-detection)
- [Coordinate Systems](#coordinate-systems)
- [Rotation Mathematics](#rotation-mathematics)
- [Rendering Pipeline](#rendering-pipeline)
- [Performance Considerations](#performance-considerations)
- [Extending the Radar](#extending-the-radar)

## Architecture Overview

![System Architecture](images/architecture.svg)
*Complete system architecture showing data flow from game memory to display*

### Component Structure

```
RadarApp
├── GameMemoryReader    (Memory access and entity parsing)
│   ├── Process attachment
│   ├── Module base resolution
│   ├── Entity list traversal
│   └── Data structure parsing
│
└── RadarDisplay       (Visualization and user interface)
    ├── Coordinate transformation
    ├── Entity rendering
    ├── UI overlay
    └── Input handling
```

### Data Flow

```
Game Memory → pymem → Raw Bytes → Parser → Entity Objects → 
Coordinate Transform → Screen Coordinates → pygame Renderer → Display
```

## Memory Structure

![Memory Structure and Pointer Layout](images/memory-structure.svg)
*Entity list structure and pointer dereferencing process*

### Base Pointers

The Evil Within stores entities in a linked list structure:

```
Module Base Address (EvilWithin.exe)
    ↓
+ 0x01E7AF20 (ENTITY_LIST_BASE_OFFSET)
    ↓
Entity List Pointer
    ↓
First Entity Pointer ──→ Entity Object 1
    ↓ +0x18
Second Entity Pointer ──→ Entity Object 2
    ↓ +0x18
Third Entity Pointer ──→ Entity Object 3
    ...
```

### Entity Structure Layout

Each entity occupies a memory block with the following structure:

```
Entity Base Address
├── +0x08 → Instance Name Pointer
│           └── +0x00 → String data
├── +0x18 → Class Name Pointer
│           └── +0xA4 → String data
├── +0x6C8 → X Position (float)
├── +0x6CC → Y Position (float)
├── +0x6D0 → Z Position (float)
├── +0x6D4 → Rotation Cosine (float)
├── +0x6E0 → Rotation Sine (float)
└── +0x8C4 → Health (float)
```

### Memory Offset Configuration

```python
ENTITY_FIELD_CONFIG = {
    "class_name": {
        "pointer_offset": 0x18,    # Offset to pointer
        "value_offset": 0xA4,      # Offset from pointer to data
        "type": "string"
    },
    "instance_name": {
        "pointer_offset": 0x08,
        "value_offset": 0x00,
        "type": "string"
    },
    "health": {
        "offset": 0x8C4,           # Direct offset (no pointer)
        "type": "float"
    },
    "x": {"offset": 0x6C8, "type": "float"},
    "y": {"offset": 0x6CC, "type": "float"},
    "z": {"offset": 0x6D0, "type": "float"},
    "rot_c": {"offset": 0x6D4, "type": "float"},
    "rot_s": {"offset": 0x6E0, "type": "float"},
}
```

### Pointer Dereference

String fields require two-level indirection:

```python
# Reading class name
entity_address = 0x12345678
pointer_offset = 0x18
value_offset = 0xA4

# Step 1: Read pointer
pointer = read_longlong(entity_address + 0x18)
# pointer = 0x23456789

# Step 2: Read string data
string_address = pointer + 0xA4
class_name = read_string(string_address)
```

## Entity Detection

### Classification Algorithm

Entities are classified using a priority-based system:

```python
def classify_entity(class_name, instance_name, health):
    # Priority 1: Check for player identifiers
    if "player" in class_name.lower() or "player" in instance_name.lower():
        return EntityType.PLAYER
    
    # Priority 2: Living entities with health
    if health and health > 0:
        return EntityType.ENEMY
    
    # Priority 3: Known NPC identifiers
    if "npc" in class_name.lower() or "friendly" in instance_name.lower():
        return EntityType.NPC
    
    # Default: Generic object
    return EntityType.OBJECT
```

### Entity Validation

Invalid entities are filtered using position checks:

```python
def is_valid_position(position):
    """Entities with coordinates beyond ±1,000,000 are invalid"""
    return (abs(position.x) < 1_000_000 and
            abs(position.y) < 1_000_000 and
            abs(position.z) < 1_000_000)
```

### Dynamic Memory Handling

The Evil Within uses dynamic memory allocation. Entity addresses change frequently:

**Problem**: Entity list pointers can be reallocated during gameplay.

**Solution**: Continuous scanning rather than caching addresses:

```python
def read_all_entities():
    entities = []
    entity_list_addr = module_base + ENTITY_LIST_BASE_OFFSET
    
    for i in range(MAX_ENTITIES):
        # Read pointer for each entity
        pointer_addr = entity_list_addr + (i * POINTER_SPACING)
        entity_addr = read_longlong(pointer_addr)
        
        # Validate and parse
        if entity_addr and entity_addr > 0x10000:
            entity = parse_entity(entity_addr)
            if entity and entity.is_valid_position():
                entities.append(entity)
    
    return entities
```

## Coordinate Systems

![Coordinate System Transformation](images/coordinate-systems.svg)
*Complete transformation pipeline from world space to radar display*

### World Space

The game uses a standard 3D coordinate system:
- **X**: Horizontal (East/West)
- **Y**: Horizontal (North/South)
- **Z**: Vertical (Up/Down)

```
     Y (North)
     ↑
     |
     |
     └────→ X (East)
    /
   /
  ↙ Z (Down)
```

### Radar Space

Radar uses a 2D player-centric coordinate system:
- Player is always at origin (0, 0)
- Player always faces "up" (negative Y direction on screen)
- X increases to the right
- Y increases downward (screen coordinates)

```
Screen Space:
    0────→ X (right)
    |
    |
    ↓ Y (down)

Radar Semantics:
    ↑ Player forward direction
    |
    |
    •────→ Right
 Player
```

## Rotation Mathematics

### Rotation Matrix

The game stores rotation as cosine and sine values representing a 2D rotation matrix:

```
R = [cos θ   -sin θ]
    [sin θ    cos θ]
```

Where:
- `rot_c` = cos(θ)
- `rot_s` = sin(θ)
- θ is the rotation angle (0° = facing East)

### World to Player-Local Transform

```python
def world_to_local(world_x, world_y, player_rot):
    """Transform world coordinates to player's local coordinate frame"""
    cos_theta = player_rot.cos_theta
    sin_theta = player_rot.sin_theta
    
    # Apply rotation matrix
    local_x = cos_theta * world_x - sin_theta * world_y
    local_y = sin_theta * world_x + cos_theta * world_y
    
    return local_x, local_y
```

### Local to Radar Transform

To make the player face "up" on the radar, we apply a final transformation:

```python
def local_to_radar(local_x, local_y):
    """
    Transform player-local coordinates to radar display coordinates
    
    Transformation ensures:
    - Player faces UP (negative Y on screen)
    - Positive X remains to the right
    - Maintains correct spatial relationships
    """
    radar_x = -local_y
    radar_y = -local_x
    
    return radar_x, radar_y
```

### Complete Transformation Pipeline

```python
def transform_entity_to_radar(entity_pos, player_pos, player_rot):
    """Complete pipeline: World → Radar"""
    
    # 1. Get relative position (world space)
    rel_x = entity_pos.x - player_pos.x
    rel_y = entity_pos.y - player_pos.y
    
    # 2. Transform to player-local space
    local_x = player_rot.cos_theta * rel_x - player_rot.sin_theta * rel_y
    local_y = player_rot.sin_theta * rel_x + player_rot.cos_theta * rel_y
    
    # 3. Transform to radar space
    radar_x = -local_y
    radar_y = -local_x
    
    # 4. Convert to screen coordinates
    center_x = SCREEN_WIDTH / 2
    center_y = SCREEN_HEIGHT / 2
    scale = SCREEN_HEIGHT / (2 * radar_range)
    
    screen_x = center_x + radar_x * scale
    screen_y = center_y + radar_y * scale
    
    return screen_x, screen_y
```

### Direction Vector Transform

For displaying entity facing directions:

```python
def transform_direction_to_radar(direction_x, direction_y, player_rot):
    """Transform a direction vector from world to radar space"""
    
    # Direction vectors use same rotation as positions
    local_dir_x = player_rot.cos_theta * direction_x - player_rot.sin_theta * direction_y
    local_dir_y = player_rot.sin_theta * direction_x + player_rot.cos_theta * direction_y
    
    # Apply radar transform
    radar_dir_x = -local_dir_y
    radar_dir_y = -local_dir_x
    
    return radar_dir_x, radar_dir_y
```

### Forward Vector Calculation

Each entity's facing direction is computed from rotation data:

```python
def get_forward_vector(rotation):
    """
    Get entity's forward direction in world space
    Note: Negated sin for proper direction
    """
    forward_x = rotation.cos_theta
    forward_y = -rotation.sin_theta
    return forward_x, forward_y
```

## Rendering Pipeline

### Frame Update Cycle

```python
while running:
    # 1. Input handling
    for event in pygame.event.get():
        handle_event(event)
    
    # 2. Memory reading
    entities = memory_reader.read_all_entities()
    player = find_player(entities)
    
    # 3. Rendering
    screen.fill(BACKGROUND_COLOR)
    draw_grid()
    
    if player:
        for entity in entities:
            # Transform coordinates
            radar_x, radar_y = transform_to_radar(entity, player)
            screen_x, screen_y = world_to_screen(radar_x, radar_y)
            
            # Draw entity
            if is_on_screen(screen_x, screen_y):
                draw_entity(entity, screen_x, screen_y)
    
    draw_ui()
    
    # 4. Display update
    pygame.display.flip()
    clock.tick(FPS)
```

### Drawing Functions

#### Grid Rendering

```python
def draw_grid():
    """Draw concentric range circles"""
    center = (width // 2, height // 2)
    max_radius = height // 2
    
    for i in range(1, 5):
        radius = (max_radius * i) // 4
        pygame.draw.circle(screen, GRID_COLOR, center, radius, 1)
```

#### Entity Rendering

```python
def draw_entity(entity, x, y, distance, player_rotation):
    if entity.type == PLAYER:
        # Draw triangle pointing up
        draw_player_triangle(x, y)
    
    elif entity.type == ENEMY:
        # Draw red circle
        pygame.draw.circle(screen, RED, (x, y), 8)
        
        # Draw health bar
        draw_health_bar(x, y - 15, entity.health)
        
        # Draw direction arrow
        if entity.rotation:
            draw_direction_arrow(x, y, entity.rotation, player_rotation)
    
    # Draw distance label
    if distance > 10:
        text = font.render(f"{int(distance)}", True, WHITE)
        screen.blit(text, (x + 10, y - 5))
```

#### Direction Indicators

```python
def draw_direction_arrow(x, y, entity_rot, player_rot, color):
    # Get entity's forward direction in world space
    forward_x, forward_y = entity_rot.forward_vector
    
    # Transform to radar space
    radar_dir_x, radar_dir_y = player_rot.transform_direction_to_radar(
        forward_x, forward_y
    )
    
    # Normalize and scale
    length = math.hypot(radar_dir_x, radar_dir_y)
    if length > 0:
        radar_dir_x /= length
        radar_dir_y /= length
        
        arrow_length = 15
        end_x = x + int(radar_dir_x * arrow_length)
        end_y = y + int(radar_dir_y * arrow_length)
        
        # Draw arrow line
        pygame.draw.line(screen, color, (x, y), (end_x, end_y), 2)
        
        # Draw arrowhead
        draw_arrowhead(end_x, end_y, radar_dir_x, radar_dir_y, color)
```

## Performance Considerations

### Memory Reading Optimization

**Challenge**: Reading 100+ entities at 60 FPS requires ~6000 memory reads/second.

**Optimizations**:

1. **Field-level caching**: Only read fields that exist
   ```python
   if not pointer or pointer < 0x10000:
       return None  # Skip invalid pointers early
   ```

2. **Batch validation**: Filter entities before full parsing
   ```python
   # Quick position check before reading all fields
   x = read_float(addr + 0x6C8)
   if abs(x) > 1_000_000:
       return None  # Invalid entity
   ```

3. **Try-except optimization**: Catch memory errors without stack traces
   ```python
   try:
       value = pm.read_float(address)
   except (MemoryReadError, WinAPIError):
       return None  # Fast path for invalid reads
   ```

### Rendering Optimization

```python
# Only draw entities within radar range
if distance > radar_range:
    continue

# Cull entities outside screen bounds
if not is_on_screen(screen_x, screen_y):
    continue

# Use integer coordinates for drawing
screen_x = int(screen_x)
screen_y = int(screen_y)
```

### Frame Rate Management

```python
# Cap at 60 FPS to prevent excessive CPU usage
clock.tick(60)

# Consider reducing FPS if performance is an issue
RADAR_CONFIG["fps"] = 30  # Still smooth, half the CPU usage
```

## Extending the Radar

### Adding New Entity Fields

To track additional entity properties:

1. **Find memory offset** (using Cheat Engine or similar):
   ```
   Scan for value → Modify in game → Rescan → Find static address
   ```

2. **Add to configuration**:
   ```python
   ENTITY_FIELD_CONFIG = {
       # ... existing fields ...
       "stamina": {"offset": 0xXXX, "type": "float"},
   }
   ```

3. **Update Entity dataclass**:
   ```python
   @dataclass
   class Entity:
       # ... existing fields ...
       stamina: float = 0.0
   ```

4. **Parse in read function**:
   ```python
   entity.stamina = self._read_field(entity_addr, 
                                     ENTITY_FIELD_CONFIG["stamina"])
   ```

### Adding Visual Indicators

```python
def draw_entity(entity, x, y, distance, player_rotation):
    # ... existing drawing code ...
    
    # Add new indicator
    if entity.is_alerted:
        pygame.draw.circle(screen, YELLOW, (x, y), 12, 2)  # Alert ring
```

### Multi-Game Support

To support different game versions:

```python
GAME_VERSIONS = {
    "steam": {
        "exe_name": "EvilWithin.exe",
        "entity_list_offset": 0x01E7AF20,
    },
    "gog": {
        "exe_name": "EvilWithin_GOG.exe",
        "entity_list_offset": 0x01E7B000,  # Different offset
    }
}

# Auto-detect version
def detect_game_version():
    for version, config in GAME_VERSIONS.items():
        try:
            pm = pymem.Pymem(config["exe_name"])
            return version, config
        except ProcessNotFound:
            continue
    raise GameNotFoundError("No supported game version running")
```

### Recording Entity Positions

For route planning or analysis:

```python
class EntityRecorder:
    def __init__(self):
        self.recordings = []
    
    def record_frame(self, entities):
        frame_data = {
            "timestamp": time.time(),
            "entities": [
                {
                    "type": e.entity_type.value,
                    "position": (e.position.x, e.position.y, e.position.z),
                    "health": e.health,
                }
                for e in entities
            ]
        }
        self.recordings.append(frame_data)
    
    def save(self, filename):
        with open(filename, 'w') as f:
            json.dump(self.recordings, f, indent=2)
```

## Debugging Tools

### Memory Dump Function

```python
def dump_entity_memory(entity_address, size=0x1000):
    """Dump raw memory for analysis"""
    data = pm.read_bytes(entity_address, size)
    
    # Print in hex viewer format
    for i in range(0, len(data), 16):
        hex_data = ' '.join(f'{b:02X}' for b in data[i:i+16])
        ascii_data = ''.join(chr(b) if 32 <= b < 127 else '.' 
                            for b in data[i:i+16])
        print(f'{entity_address + i:08X}: {hex_data:<48} {ascii_data}')
```

### Live Entity Inspector

```python
def inspect_entity(entity):
    """Print detailed entity information"""
    print(f"Entity at 0x{entity.address:X}")
    print(f"  Type: {entity.entity_type.value}")
    print(f"  Position: ({entity.position.x:.2f}, "
          f"{entity.position.y:.2f}, {entity.position.z:.2f})")
    print(f"  Health: {entity.health:.2f}")
    print(f"  Class: {entity.class_name}")
    print(f"  Instance: {entity.instance_name}")
    if entity.rotation:
        print(f"  Facing: {entity.rotation.angle_degrees:.1f}°")
```

## Known Issues and Workarounds

### Issue: Entity positions jump on load

**Cause**: Memory not fully initialized when level loads.

**Workaround**: 
```python
# Wait for stable positions
if abs(entity.position.x - prev_position.x) > 1000:
    continue  # Skip this frame
```

### Issue: Some entities not detected

**Cause**: They may use different memory structures or be culled by the game.

**Investigation**: Increase `MAX_ENTITIES` and log all found pointers.

## Performance Metrics

Typical performance on modern hardware:
- **CPU Usage**: 1-2% (single core)
- **Memory Usage**: ~50 MB
- **Frame Time**: ~1.5 ms per frame
- **Memory Reads**: ~100-200 per frame

## Further Reading

- **pymem Documentation**: [https://pymem.readthedocs.io/](https://pymem.readthedocs.io/)
- **pygame Documentation**: [https://www.pygame.org/docs/](https://www.pygame.org/docs/)
- **Reverse Engineering**: Study Cheat Engine tutorials for finding game structures
- **Rotation Matrices**: [https://en.wikipedia.org/wiki/Rotation_matrix](https://en.wikipedia.org/wiki/Rotation_matrix)

---

For questions about technical implementation, open an issue on GitHub with the `technical` label.
