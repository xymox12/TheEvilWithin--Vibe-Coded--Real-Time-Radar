import pymem
import pymem.process
import logging
import time
from typing import Any, Dict, Optional, List, Tuple
from dataclasses import dataclass
from enum import Enum
import pygame
import math

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# ============================================================================
# CONSTANTS & CONFIGURATION
# ============================================================================

GAME_EXE = "EvilWithin.exe"
ENTITY_LIST_BASE_OFFSET = 0x01E7AF20
POINTER_SPACING = 0x18
MAX_ENTITIES = 100  # Increased to catch more entities

# Radar configuration
RADAR_CONFIG = {
    "default_range": 1000,
    "min_range": 100,
    "max_range": 5000,
    "range_step": 100,
    "fps": 60,
    "width": 800,
    "height": 800,
    "show_info_panel": False,  # Set to False to hide text overlay
}

# Colors
COLORS = {
    "background": (20, 20, 30),
    "grid": (40, 40, 50),
    "player": (0, 150, 255),
    "enemy": (255, 100, 0),  # Orange for idle enemies (caution)
    "enemy_alerted": (255, 50, 50),  # Red for alerted enemies (danger!)
    "partner": (0, 255, 100),  # Bright green for friendly NPCs
    "npc": (255, 200, 50),
    "object": (100, 100, 100),
    "text": (200, 200, 200),
    "alert_ring": (255, 200, 0),  # Yellow ring around alerted enemies
}

ENTITY_FIELD_CONFIG = {
    "class_name": {"pointer_offset": 0x18, "value_offset": 0xA4, "type": "string"},
    "instance_name": {"pointer_offset": 0x08, "value_offset": 0x00, "type": "string"},
    "health": {"offset": 0x8C4, "type": "float"},
    "x": {"offset": 0x6C8, "type": "float"},
    "y": {"offset": 0x6CC, "type": "float"},
    "z": {"offset": 0x6D0, "type": "float"},
    "rot_c": {"offset": 0x6D4, "type": "float"},
    "rot_s": {"offset": 0x6E0, "type": "float"},
    "alertness": {"offset": 0xF44, "type": "short"},
}


# ============================================================================
# DATA STRUCTURES
# ============================================================================

class EntityType(Enum):
    PLAYER = "player"
    ENEMY = "enemy"
    PARTNER = "partner"  # Friendly NPCs (Joseph, Kidman, etc.)
    NPC = "npc"  # Neutral NPCs (corpses, animals, etc.)
    OBJECT = "object"


@dataclass
class Position:
    x: float
    y: float
    z: float = 0.0

    def distance_to(self, other: 'Position') -> float:
        return math.hypot(self.x - other.x, self.y - other.y)


@dataclass
class Rotation:
    cos_theta: float
    sin_theta: float

    @property
    def angle_degrees(self) -> float:
        return math.degrees(math.atan2(self.sin_theta, self.cos_theta))

    @property
    def forward_vector(self) -> Tuple[float, float]:
        """
        Get the forward direction vector in world space.
        Since we use Method 2 for position transform (which negates Y),
        we need to use the non-negated Method 5 for directions.
        """
        return (self.cos_theta, -self.sin_theta)

    def to_radar_space(self, world_x: float, world_y: float) -> Tuple[float, float]:
        """
        Transform world coordinates to radar space (player-relative).

        The game's rotation matrix is:
        [cos θ  -sin θ]
        [sin θ   cos θ]

        We want radar coordinates where:
        - Player always faces UP (negative Y)
        - X increases to the right
        - Y increases downward (screen coordinates)

        Method 2 (empirically verified):
        - radar_x = -local_y
        - radar_y = -local_x (negated compared to original)
        """
        # Apply rotation matrix (world -> player local space)
        local_x = self.cos_theta * world_x - self.sin_theta * world_y
        local_y = self.sin_theta * world_x + self.cos_theta * world_y

        # Transform to radar coordinates (Method 2 - correct!)
        radar_x = -local_y
        radar_y = -local_x  # Negated to fix north/south inversion

        return radar_x, radar_y

    def transform_direction_to_radar(self, world_dir_x: float, world_dir_y: float) -> Tuple[float, float]:
        """
        Transform a direction vector from world space to radar space.
        This is the same transformation as to_radar_space but for direction vectors.
        """
        return self.to_radar_space(world_dir_x, world_dir_y)


@dataclass
class Entity:
    address: int
    position: Position
    entity_type: EntityType
    health: float = 0.0
    class_name: str = ""
    instance_name: str = ""
    rotation: Optional[Rotation] = None
    alertness: Optional[int] = None  # -1 = not alerted, 0 = alerted

    def is_valid_position(self) -> bool:
        """Check if entity has reasonable world coordinates"""
        return (abs(self.position.x) < 1_000_000 and
                abs(self.position.y) < 1_000_000 and
                abs(self.position.z) < 1_000_000)

    def is_alerted(self) -> bool:
        """Check if enemy is alerted to player"""
        return self.alertness is not None and self.alertness == 0


# ============================================================================
# MEMORY READING
# ============================================================================

class MemoryReadError(Exception):
    """Custom exception for memory reading failures"""
    pass


class GameMemoryReader:
    def __init__(self, game_exe: str):
        self.pm = self._attach_to_process(game_exe)
        self.module_base = self._get_module_base(game_exe)
        self.entity_list_pointer = self.module_base + ENTITY_LIST_BASE_OFFSET
        logging.info(f"Entity list pointer: 0x{self.entity_list_pointer:X}")

    def _attach_to_process(self, game_exe: str) -> pymem.Pymem:
        try:
            pm = pymem.Pymem(game_exe)
            logging.info(f"Attached to {game_exe} (PID: {pm.process_id})")
            return pm
        except pymem.exception.ProcessNotFound:
            raise MemoryReadError(f"Game process '{game_exe}' not found")
        except Exception as e:
            raise MemoryReadError(f"Failed to attach to process: {e}")

    def _get_module_base(self, game_exe: str) -> int:
        try:
            module = pymem.process.module_from_name(self.pm.process_handle, game_exe)
            return module.lpBaseOfDll
        except Exception as e:
            raise MemoryReadError(f"Failed to get module base: {e}")

    def _read_field(self, entity_address: int, config: dict) -> Optional[Any]:
        """Read a single field from entity memory"""
        try:
            # Handle pointer-based fields
            if "pointer_offset" in config:
                pointer_addr = self.pm.read_longlong(entity_address + config["pointer_offset"])
                if not pointer_addr or pointer_addr < 0x10000:  # Basic validation
                    return None
                value_address = pointer_addr + config["value_offset"]
            else:
                value_address = entity_address + config["offset"]

            # Read based on type
            field_type = config["type"]
            if field_type == "string":
                return self.pm.read_string(value_address, byte=50)  # Limit string length
            elif field_type == "float":
                return self.pm.read_float(value_address)
            elif field_type == "short":
                return self.pm.read_short(value_address)
            return None

        except (pymem.exception.MemoryReadError, pymem.exception.WinAPIError):
            return None
        except Exception as e:
            logging.debug(f"Unexpected error reading field: {e}")
            return None

    def _classify_entity(self, class_name: str, instance_name: str, health: float) -> EntityType:
        """
        Determine entity type from its properties.
        
        The Evil Within uses these class name patterns:
        - idPlayer: Player character
        - idPartner: Friendly NPCs (Joseph, Kidman)
        - idNpcEnemy: Hostile enemies
        - idNpcCorpse, idNpcAnimal_*: Neutral NPCs
        - Other: Static objects
        """
        class_lower = class_name.lower()
        instance_lower = instance_name.lower()

        # Check for player
        if "idplayer" in class_lower or "player" in instance_lower:
            return EntityType.PLAYER
        
        # Check for partners (friendly NPCs)
        if "idpartner" in class_lower:
            return EntityType.PARTNER
        
        # Check for enemies - but only if alive!
        # Dead enemies (health <= 0) should show as NPC (yellow corpses)
        if "idnpcenemy" in class_lower or ("enemy" in class_lower):
            if health and health > 0:
                return EntityType.ENEMY
            else:
                return EntityType.NPC  # Dead enemies show as yellow
        
        # Check for neutral NPCs (corpses, animals, etc.)
        if "idnpc" in class_lower or "npc" in class_lower or "civilian" in class_lower:
            return EntityType.NPC
        
        # Everything else is an object
        return EntityType.OBJECT

    def read_entity(self, base_address: int, index: int) -> Optional[Entity]:
        """Read a single entity from memory"""
        try:
            pointer_address = base_address + (index * POINTER_SPACING)
            entity_address = self.pm.read_longlong(pointer_address)

            # Validate pointer
            if not entity_address or entity_address < 0x10000:
                return None

            # Read all fields
            fields = {}
            for field_name, config in ENTITY_FIELD_CONFIG.items():
                fields[field_name] = self._read_field(entity_address, config)

            # Validate required fields
            if fields["x"] is None or fields["y"] is None:
                return None

            # Create entity object
            position = Position(
                x=fields["x"],
                y=fields["y"],
                z=fields.get("z", 0.0) or 0.0
            )

            rotation = None
            if fields["rot_c"] is not None and fields["rot_s"] is not None:
                rotation = Rotation(
                    cos_theta=fields["rot_c"],
                    sin_theta=fields["rot_s"]
                )

            class_name = fields.get("class_name") or ""
            instance_name = fields.get("instance_name") or ""
            health = fields.get("health") or 0.0
            alertness = fields.get("alertness")

            entity_type = self._classify_entity(class_name, instance_name, health)

            entity = Entity(
                address=entity_address,
                position=position,
                entity_type=entity_type,
                health=health,
                class_name=class_name,
                instance_name=instance_name,
                rotation=rotation,
                alertness=alertness
            )

            return entity if entity.is_valid_position() else None

        except (pymem.exception.MemoryReadError, pymem.exception.WinAPIError):
            return None
        except Exception as e:
            logging.debug(f"Error reading entity {index}: {e}")
            return None

    def read_all_entities(self) -> List[Entity]:
        """Read all entities from the game"""
        try:
            base_address = self.pm.read_longlong(self.entity_list_pointer)
            if not base_address:
                return []
        except Exception as e:
            logging.debug(f"Failed to read entity list base: {e}")
            return []

        entities = []
        for i in range(MAX_ENTITIES):
            entity = self.read_entity(base_address, i)
            if entity is None:
                # First None usually means end of list
                if i > 10:  # Only break if we've read a reasonable number
                    break
                continue
            entities.append(entity)

        return entities


# ============================================================================
# RADAR DISPLAY
# ============================================================================

class RadarDisplay:
    def __init__(self, config: dict):
        pygame.init()
        self.width = config["width"]
        self.height = config["height"]
        self.screen = pygame.display.set_mode((self.width, self.height))
        pygame.display.set_caption('Evil Within Radar - Improved')
        self.clock = pygame.time.Clock()
        self.font = pygame.font.Font(None, 20)
        self.font_small = pygame.font.Font(None, 16)

        self.radar_range = config["default_range"]
        self.min_range = config["min_range"]
        self.max_range = config["max_range"]
        self.range_step = config["range_step"]
        self.fps = config["fps"]
        self.show_info_panel = config.get("show_info_panel", True)  # Default to True

        self.center = (self.width // 2, self.height // 2)

    @property
    def scale(self) -> float:
        """Current pixels per game unit"""
        return self.width / (2 * self.radar_range)

    def handle_events(self) -> bool:
        """Handle pygame events. Returns False if should quit."""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return False
                elif event.key == pygame.K_MINUS or event.key == pygame.K_UNDERSCORE:
                    self.radar_range = min(self.max_range, self.radar_range + self.range_step)
                elif event.key in (pygame.K_PLUS, pygame.K_EQUALS):
                    self.radar_range = max(self.min_range, self.radar_range - self.range_step)
        return True

    def draw_background(self):
        """Draw radar background and grid"""
        self.screen.fill(COLORS["background"])

        # Center crosshair
        pygame.draw.line(self.screen, COLORS["grid"],
                         (self.center[0], 0), (self.center[0], self.height), 1)
        pygame.draw.line(self.screen, COLORS["grid"],
                         (0, self.center[1]), (self.width, self.center[1]), 1)

        # Range circle
        pygame.draw.circle(self.screen, COLORS["grid"],
                           self.center, int(self.radar_range * self.scale), 5)

        # Additional range rings
        num_rings = 8  # Change this number
        for i in range(1, num_rings + 1):
            fraction = i / (num_rings + 1)
            pygame.draw.circle(self.screen, COLORS["grid"],
                               self.center, int(self.radar_range * self.scale * fraction), 1)

    def world_to_screen(self, radar_x: float, radar_y: float) -> Tuple[int, int]:
        """Convert radar coordinates to screen coordinates"""
        screen_x = int(self.center[0] + radar_x * self.scale)
        screen_y = int(self.center[1] + radar_y * self.scale)  # radar_y already accounts for up direction
        return screen_x, screen_y

    def is_on_screen(self, screen_x: int, screen_y: int) -> bool:
        """Check if screen coordinates are visible"""
        return 0 <= screen_x < self.width and 0 <= screen_y < self.height

    def draw_player(self, screen_x: int, screen_y: int):
        """Draw player triangle (facing up)"""
        size = 10
        points = [
            (screen_x, screen_y - size),  # Top point (facing up)
            (screen_x - size, screen_y + size),  # Bottom left
            (screen_x + size, screen_y + size),  # Bottom right
        ]
        pygame.draw.polygon(self.screen, COLORS["player"], points)

    def draw_entity(self, entity: Entity, screen_x: int, screen_y: int, distance: float,
                    player_rotation: Optional[Rotation] = None):
        """Draw an entity on the radar"""
        if entity.entity_type == EntityType.PLAYER:
            self.draw_player(screen_x, screen_y)
        elif entity.entity_type == EntityType.ENEMY:
            # Determine enemy color based on alert status
            is_alerted = entity.is_alerted()
            enemy_color = COLORS["enemy_alerted"] if is_alerted else COLORS["enemy"]
            
            # Draw alert ring for alerted enemies (pulsing effect)
            if is_alerted:
                import time
                pulse = abs(math.sin(time.time() * 3))  # Pulse between 0 and 1
                ring_radius = 8 + int(pulse * 4)  # Pulse from 8 to 12 pixels
                pygame.draw.circle(self.screen, COLORS["alert_ring"], (screen_x, screen_y), ring_radius, 2)
            
            # Draw main enemy circle
            pygame.draw.circle(self.screen, enemy_color, (screen_x, screen_y), 8)
            
            # Draw health bar for enemies
            if entity.health > 0:
                self._draw_health_bar(screen_x, screen_y, entity.health)
            
            # Draw direction indicator if rotation data available
            if entity.rotation and player_rotation:
                self._draw_direction_indicator(screen_x, screen_y, entity.rotation,
                                               player_rotation, enemy_color)
        elif entity.entity_type == EntityType.PARTNER:
            # Draw partners as diamonds (friendly NPCs like Joseph, Kidman)
            size = 8
            points = [
                (screen_x, screen_y - size),      # Top
                (screen_x + size, screen_y),      # Right
                (screen_x, screen_y + size),      # Bottom
                (screen_x - size, screen_y),      # Left
            ]
            pygame.draw.polygon(self.screen, COLORS["partner"], points)
            # Draw direction indicator for partners
            if entity.rotation and player_rotation:
                self._draw_direction_indicator(screen_x, screen_y, entity.rotation,
                                               player_rotation, COLORS["partner"])
        elif entity.entity_type == EntityType.NPC:
            pygame.draw.circle(self.screen, COLORS["npc"], (screen_x, screen_y), 7)
            # Draw direction indicator for NPCs too
            if entity.rotation and player_rotation:
                self._draw_direction_indicator(screen_x, screen_y, entity.rotation,
                                               player_rotation, COLORS["npc"])
        else:
            pygame.draw.circle(self.screen, COLORS["object"], (screen_x, screen_y), 5)

        # Draw distance for non-player entities
        if entity.entity_type != EntityType.PLAYER and distance > 10:
            dist_text = self.font_small.render(f"{int(distance)}", True, COLORS["text"])
            self.screen.blit(dist_text, (screen_x + 10, screen_y - 5))

    def _draw_direction_indicator(self, x: int, y: int, entity_rotation: Rotation,
                                  player_rotation: Rotation, color: Tuple[int, int, int]):
        """Draw a line showing which direction an entity is facing"""
        # Get entity's forward direction in world space
        forward_x, forward_y = entity_rotation.forward_vector

        # Transform to radar space
        radar_dir_x, radar_dir_y = player_rotation.transform_direction_to_radar(forward_x, forward_y)

        # Normalize and scale for display
        length = math.hypot(radar_dir_x, radar_dir_y)
        if length > 0:
            radar_dir_x /= length
            radar_dir_y /= length

            # Arrow length in pixels
            arrow_length = 15

            # End point of direction line
            end_x = x + int(radar_dir_x * arrow_length)
            end_y = y + int(radar_dir_y * arrow_length)

            # Draw main direction line
            pygame.draw.line(self.screen, color, (x, y), (end_x, end_y), 2)

            # Draw arrowhead
            # Calculate perpendicular vector for arrowhead wings
            perp_x = -radar_dir_y
            perp_y = radar_dir_x

            # Arrowhead dimensions
            head_length = 6
            head_width = 4

            # Arrowhead points
            arrow_base_x = end_x - int(radar_dir_x * head_length)
            arrow_base_y = end_y - int(radar_dir_y * head_length)

            left_wing_x = arrow_base_x + int(perp_x * head_width)
            left_wing_y = arrow_base_y + int(perp_y * head_width)

            right_wing_x = arrow_base_x - int(perp_x * head_width)
            right_wing_y = arrow_base_y - int(perp_y * head_width)

            # Draw filled arrowhead
            pygame.draw.polygon(self.screen, color, [
                (end_x, end_y),
                (left_wing_x, left_wing_y),
                (right_wing_x, right_wing_y)
            ])

    def _draw_health_bar(self, x: int, y: int, health: float):
        """Draw a small health bar above entity"""
        bar_width = 20
        bar_height = 3
        health_pct = min(1.0, max(0.0, health / 100.0))  # Assuming 100 max health

        # Background
        pygame.draw.rect(self.screen, (60, 60, 60),
                         (x - bar_width // 2, y - 15, bar_width, bar_height))
        # Health
        health_color = (0, 255, 0) if health_pct > 0.5 else (255, 255, 0) if health_pct > 0.25 else (255, 0, 0)
        pygame.draw.rect(self.screen, health_color,
                         (x - bar_width // 2, y - 15, int(bar_width * health_pct), bar_height))

    def draw_info_panel(self, entity_count: int, player_found: bool,
                        player_rotation: Optional[Rotation] = None, alerted_count: int = 0):
        """Draw information overlay"""
        info_lines = [
            f"Entities: {entity_count} | Range: {self.radar_range}",
            f"Player: {'FOUND' if player_found else 'NOT FOUND'}",
            f"FPS: {int(self.clock.get_fps())}",
            "",
            f"Legend:",
            "▲ = Player (blue)",
            "♦ = Partner (green)",
            "● = Enemy (red/orange)",
            f"  └─ {alerted_count} ALERTED! (pulsing)",
            "",
            "Controls:",
            "+/= : Zoom in",
            "- : Zoom out",
            "ESC : Exit"
        ]

        if player_rotation:
            info_lines.insert(2, f"Facing: {player_rotation.angle_degrees:6.1f}°")

        for i, line in enumerate(info_lines):
            text = self.font.render(line, True, COLORS["text"])
            self.screen.blit(text, (10, 10 + i * 22))

    def flip(self):
        """Update display"""
        pygame.display.flip()
        self.clock.tick(self.fps)

    def quit(self):
        """Clean up pygame"""
        pygame.quit()


# ============================================================================
# MAIN APPLICATION
# ============================================================================

class RadarApp:
    def __init__(self):
        self.memory_reader = GameMemoryReader(GAME_EXE)
        self.display = RadarDisplay(RADAR_CONFIG)

    def run(self):
        """Main application loop"""
        running = True

        try:
            while running:
                # Handle input
                running = self.display.handle_events()
                if not running:
                    break

                # Read game state
                entities = self.memory_reader.read_all_entities()

                # Find player
                player = next((e for e in entities if e.entity_type == EntityType.PLAYER), None)

                # Count alerted enemies
                alerted_count = sum(1 for e in entities 
                                   if e.entity_type == EntityType.ENEMY and e.is_alerted())

                # Draw
                self.display.draw_background()

                if player and player.rotation:
                    # Draw all entities relative to player
                    for entity in entities:
                        # Get world-space offset
                        rel_x = entity.position.x - player.position.x
                        rel_y = entity.position.y - player.position.y

                        # Transform to radar space
                        radar_x, radar_y = player.rotation.to_radar_space(rel_x, rel_y)

                        # Convert to screen coordinates
                        screen_x, screen_y = self.display.world_to_screen(radar_x, radar_y)

                        # Draw if on screen
                        if self.display.is_on_screen(screen_x, screen_y):
                            distance = entity.position.distance_to(player.position)
                            self.display.draw_entity(entity, screen_x, screen_y, distance, player.rotation)

                # Draw UI
                if self.display.show_info_panel:
                    self.display.draw_info_panel(
                        len(entities),
                        player is not None,
                        player.rotation if player else None,
                        alerted_count
                    )

                self.display.flip()

        except KeyboardInterrupt:
            logging.info("Interrupted by user")
        except MemoryReadError as e:
            logging.error(f"Memory error: {e}")
        except Exception as e:
            logging.error(f"Unexpected error: {e}", exc_info=True)
        finally:
            self.display.quit()


# ============================================================================
# ENTRY POINT
# ============================================================================

def main():
    try:
        app = RadarApp()
        app.run()
    except MemoryReadError as e:
        logging.error(f"Failed to initialize: {e}")
    except Exception as e:
        logging.error(f"Fatal error: {e}", exc_info=True)


if __name__ == "__main__":
    main()