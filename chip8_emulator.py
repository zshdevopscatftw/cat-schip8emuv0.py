#!/usr/bin/env python3
"""
Cat's Chip-8 Emulator
A complete CHIP-8 emulator with Tkinter GUI and Bluetooth controller support.
Author: Team Flames / Samsoft
"""

import tkinter as tk
from tkinter import messagebox
import threading
import time
import random
import pickle
import os
import sys
from typing import Optional, Callable
from dataclasses import dataclass, field

# Try to import pygame for controller support
try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False
    print("Warning: pygame not available. Controller support disabled.")

# Constants
MEMORY_SIZE = 4096
DISPLAY_WIDTH = 64
DISPLAY_HEIGHT = 32
STACK_SIZE = 16
NUM_REGISTERS = 16
NUM_KEYS = 16
PROGRAM_START = 0x200
FONT_START = 0x50

WINDOW_WIDTH = 600
WINDOW_HEIGHT = 400
DISPLAY_AREA_HEIGHT = 350
STATUS_BAR_HEIGHT = 50

PIXEL_COLOR = "#C0C0C0"
BG_COLOR = "#1A1A1A"
STATUS_BG = "#2A2A2A"
STATUS_FG = "#888888"

CPU_FREQUENCY = 500
TIMER_FREQUENCY = 60
TARGET_FPS = 60

# CHIP-8 Font sprites (0-F)
FONTSET = [
    0xF0, 0x90, 0x90, 0x90, 0xF0,  # 0
    0x20, 0x60, 0x20, 0x20, 0x70,  # 1
    0xF0, 0x10, 0xF0, 0x80, 0xF0,  # 2
    0xF0, 0x10, 0xF0, 0x10, 0xF0,  # 3
    0x90, 0x90, 0xF0, 0x10, 0x10,  # 4
    0xF0, 0x80, 0xF0, 0x10, 0xF0,  # 5
    0xF0, 0x80, 0xF0, 0x90, 0xF0,  # 6
    0xF0, 0x10, 0x20, 0x40, 0x40,  # 7
    0xF0, 0x90, 0xF0, 0x90, 0xF0,  # 8
    0xF0, 0x90, 0xF0, 0x10, 0xF0,  # 9
    0xF0, 0x90, 0xF0, 0x90, 0x90,  # A
    0xE0, 0x90, 0xE0, 0x90, 0xE0,  # B
    0xF0, 0x80, 0x80, 0x80, 0xF0,  # C
    0xE0, 0x90, 0x90, 0x90, 0xE0,  # D
    0xF0, 0x80, 0xF0, 0x80, 0xF0,  # E
    0xF0, 0x80, 0xF0, 0x80, 0x80,  # F
]

# Keyboard mapping (CHIP-8 key -> keyboard key)
KEYBOARD_MAP = {
    '1': 0x1, '2': 0x2, '3': 0x3, '4': 0xC,
    'q': 0x4, 'w': 0x5, 'e': 0x6, 'r': 0xD,
    'a': 0x7, 's': 0x8, 'd': 0x9, 'f': 0xE,
    'z': 0xA, 'x': 0x0, 'c': 0xB, 'v': 0xF,
}


@dataclass
class EmulatorState:
    """Complete emulator state for save/load"""
    memory: bytearray
    v: list
    i: int
    pc: int
    stack: list
    sp: int
    delay_timer: int
    sound_timer: int
    display: list
    keys: list


class Chip8Audio:
    """Audio system for CHIP-8 sound timer beeps"""
    
    def __init__(self):
        self.is_beeping = False
        self._beep_thread: Optional[threading.Thread] = None
        
    def start_beep(self):
        """Start the beep sound"""
        if not self.is_beeping:
            self.is_beeping = True
            # Use system bell as fallback
            print('\a', end='', flush=True)
    
    def stop_beep(self):
        """Stop the beep sound"""
        self.is_beeping = False
    
    def update(self, sound_timer: int):
        """Update audio based on sound timer"""
        if sound_timer > 0 and not self.is_beeping:
            self.start_beep()
        elif sound_timer == 0 and self.is_beeping:
            self.stop_beep()


class Chip8Controller:
    """Controller input handler with Bluetooth support"""
    
    # Controller button mappings for PS5/Atari style
    BUTTON_CIRCLE = 1
    BUTTON_SQUARE = 0
    BUTTON_TRIANGLE = 3
    BUTTON_CROSS = 2
    BUTTON_L1 = 4
    BUTTON_R1 = 5
    BUTTON_L2 = 6
    BUTTON_R2 = 7
    BUTTON_SHARE = 8
    BUTTON_OPTIONS = 9
    BUTTON_PS = 12
    BUTTON_TOUCHPAD = 13
    
    # D-Pad (as hat)
    HAT_UP = (0, 1)
    HAT_DOWN = (0, -1)
    HAT_LEFT = (-1, 0)
    HAT_RIGHT = (1, 0)
    
    def __init__(self, on_key_change: Callable[[int, bool], None]):
        self.on_key_change = on_key_change
        self.joystick: Optional[pygame.joystick.JoystickType] = None
        self.connected = False
        self.connection_type = "None"
        self.battery_level = -1
        self.running = False
        self._thread: Optional[threading.Thread] = None
        
        # Special action callbacks
        self.on_reset: Optional[Callable] = None
        self.on_pause_toggle: Optional[Callable] = None
        self.on_save_state: Optional[Callable] = None
        self.on_load_state: Optional[Callable] = None
        self.on_speed_increase: Optional[Callable] = None
        self.on_speed_decrease: Optional[Callable] = None
        self.on_toggle_scanlines: Optional[Callable] = None
        
        # Debug overlay tracking
        self._debug_hold_start = 0
        self._l1_held = False
        self._l2_held = False
        self._touchpad_held = False
        self.on_debug_toggle: Optional[Callable] = None
        
        if PYGAME_AVAILABLE:
            pygame.init()
            pygame.joystick.init()
    
    def start(self):
        """Start controller polling thread"""
        if not PYGAME_AVAILABLE:
            return
        self.running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
    
    def stop(self):
        """Stop controller polling"""
        self.running = False
        if self._thread:
            self._thread.join(timeout=1.0)
    
    def _poll_loop(self):
        """Main controller polling loop"""
        while self.running:
            self._check_connection()
            if self.connected:
                self._process_input()
            time.sleep(1/120)  # 120Hz polling
    
    def _check_connection(self):
        """Check for controller connection/disconnection"""
        pygame.event.pump()
        
        joystick_count = pygame.joystick.get_count()
        
        if joystick_count > 0 and not self.connected:
            # Connect to first available controller
            self.joystick = pygame.joystick.Joystick(0)
            self.joystick.init()
            self.connected = True
            
            # Determine connection type (heuristic)
            name = self.joystick.get_name().lower()
            if "wireless" in name or "bluetooth" in name or "dualsense" in name:
                self.connection_type = "Bluetooth"
            else:
                self.connection_type = "USB"
            
            # Try to get battery level (may not be available)
            try:
                power = self.joystick.get_power_level()
                power_map = {"empty": 0, "low": 25, "medium": 50, "full": 100}
                self.battery_level = power_map.get(power, -1)
            except:
                self.battery_level = -1
                
        elif joystick_count == 0 and self.connected:
            # Controller disconnected
            self.connected = False
            self.connection_type = "None"
            self.joystick = None
            self.battery_level = -1
    
    def _process_input(self):
        """Process controller input and map to CHIP-8 keys"""
        if not self.joystick:
            return
            
        for event in pygame.event.get():
            if event.type == pygame.JOYBUTTONDOWN:
                self._handle_button_down(event.button)
            elif event.type == pygame.JOYBUTTONUP:
                self._handle_button_up(event.button)
            elif event.type == pygame.JOYHATMOTION:
                self._handle_hat(event.value)
    
    def _handle_button_down(self, button: int):
        """Handle button press"""
        # Map controller buttons to CHIP-8 keys
        button_to_key = {
            self.BUTTON_CIRCLE: 0x1,
            self.BUTTON_SQUARE: 0x2,
            self.BUTTON_TRIANGLE: 0x3,
            self.BUTTON_CROSS: 0xC,
            self.BUTTON_L1: 0x4,
            self.BUTTON_R1: 0x5,
            self.BUTTON_L2: 0xD,
            self.BUTTON_R2: 0xE,
            self.BUTTON_SHARE: 0x7,
            self.BUTTON_OPTIONS: 0x8,
            self.BUTTON_PS: 0x9,
            self.BUTTON_TOUCHPAD: 0xA,
        }
        
        # Handle special actions
        if button == self.BUTTON_CIRCLE:
            if self.on_reset:
                self.on_reset()
        elif button == self.BUTTON_CROSS:
            if self.on_pause_toggle:
                self.on_pause_toggle()
        elif button == self.BUTTON_SQUARE:
            if self.on_save_state:
                self.on_save_state()
        elif button == self.BUTTON_TRIANGLE:
            if self.on_load_state:
                self.on_load_state()
        elif button == self.BUTTON_L1:
            self._l1_held = True
            if self.on_speed_increase:
                self.on_speed_increase()
        elif button == self.BUTTON_L2:
            self._l2_held = True
            if self.on_speed_decrease:
                self.on_speed_decrease()
        elif button == self.BUTTON_TOUCHPAD:
            self._touchpad_held = True
            if self.on_toggle_scanlines:
                self.on_toggle_scanlines()
        
        # Check debug combo
        self._check_debug_combo()
        
        # Also set CHIP-8 key
        if button in button_to_key:
            self.on_key_change(button_to_key[button], True)
    
    def _handle_button_up(self, button: int):
        """Handle button release"""
        button_to_key = {
            self.BUTTON_CIRCLE: 0x1,
            self.BUTTON_SQUARE: 0x2,
            self.BUTTON_TRIANGLE: 0x3,
            self.BUTTON_CROSS: 0xC,
            self.BUTTON_L1: 0x4,
            self.BUTTON_R1: 0x5,
            self.BUTTON_L2: 0xD,
            self.BUTTON_R2: 0xE,
            self.BUTTON_SHARE: 0x7,
            self.BUTTON_OPTIONS: 0x8,
            self.BUTTON_PS: 0x9,
            self.BUTTON_TOUCHPAD: 0xA,
        }
        
        if button == self.BUTTON_L1:
            self._l1_held = False
        elif button == self.BUTTON_L2:
            self._l2_held = False
        elif button == self.BUTTON_TOUCHPAD:
            self._touchpad_held = False
        
        # Reset debug hold
        self._debug_hold_start = 0
        
        if button in button_to_key:
            self.on_key_change(button_to_key[button], False)
    
    def _handle_hat(self, value: tuple):
        """Handle D-pad input"""
        # D-pad to CHIP-8 keys (2=down, 4=left, 6=right, 8=up)
        if value == self.HAT_UP:
            self.on_key_change(0x8, True)
        elif value == self.HAT_DOWN:
            self.on_key_change(0x2, True)
        elif value == self.HAT_LEFT:
            self.on_key_change(0x4, True)
        elif value == self.HAT_RIGHT:
            self.on_key_change(0x6, True)
        elif value == (0, 0):
            # Released
            self.on_key_change(0x2, False)
            self.on_key_change(0x4, False)
            self.on_key_change(0x6, False)
            self.on_key_change(0x8, False)
    
    def _check_debug_combo(self):
        """Check for L1+L2+Touchpad held for 2 seconds"""
        if self._l1_held and self._l2_held and self._touchpad_held:
            if self._debug_hold_start == 0:
                self._debug_hold_start = time.time()
            elif time.time() - self._debug_hold_start >= 2.0:
                if self.on_debug_toggle:
                    self.on_debug_toggle()
                self._debug_hold_start = 0
        else:
            self._debug_hold_start = 0


class Chip8CPU:
    """CHIP-8 CPU core with all 35 opcodes"""
    
    def __init__(self):
        self.reset()
    
    def reset(self):
        """Reset CPU to initial state"""
        # Memory
        self.memory = bytearray(MEMORY_SIZE)
        
        # Load font into memory
        for i, byte in enumerate(FONTSET):
            self.memory[FONT_START + i] = byte
        
        # Registers
        self.v = [0] * NUM_REGISTERS  # V0-VF
        self.i = 0  # Index register
        self.pc = PROGRAM_START  # Program counter
        
        # Stack
        self.stack = [0] * STACK_SIZE
        self.sp = 0  # Stack pointer
        
        # Timers
        self.delay_timer = 0
        self.sound_timer = 0
        
        # Display (64x32 pixels)
        self.display = [[0] * DISPLAY_WIDTH for _ in range(DISPLAY_HEIGHT)]
        
        # Input
        self.keys = [False] * NUM_KEYS
        
        # State flags
        self.draw_flag = False
        self.waiting_for_key = False
        self.key_register = 0
        
        # ROM info
        self.rom_loaded = False
        self.rom_name = ""
    
    def load_rom(self, data: bytes, name: str = ""):
        """Load ROM data into memory"""
        self.reset()
        for i, byte in enumerate(data):
            if PROGRAM_START + i < MEMORY_SIZE:
                self.memory[PROGRAM_START + i] = byte
        self.rom_loaded = True
        self.rom_name = name or "Unknown"
    
    def cycle(self):
        """Execute one CPU cycle"""
        if self.waiting_for_key:
            return
        
        # Fetch opcode (2 bytes)
        opcode = (self.memory[self.pc] << 8) | self.memory[self.pc + 1]
        
        # Decode and execute
        self._execute(opcode)
    
    def _execute(self, opcode: int):
        """Decode and execute opcode"""
        # Extract common parts
        nnn = opcode & 0x0FFF  # 12-bit address
        nn = opcode & 0x00FF   # 8-bit constant
        n = opcode & 0x000F    # 4-bit constant
        x = (opcode >> 8) & 0x0F  # Register X
        y = (opcode >> 4) & 0x0F  # Register Y
        
        first = opcode >> 12
        
        if opcode == 0x00E0:
            # 00E0: Clear screen
            self.display = [[0] * DISPLAY_WIDTH for _ in range(DISPLAY_HEIGHT)]
            self.draw_flag = True
            self.pc += 2
            
        elif opcode == 0x00EE:
            # 00EE: Return from subroutine
            self.sp -= 1
            self.pc = self.stack[self.sp]
            self.pc += 2
            
        elif first == 0x1:
            # 1NNN: Jump to NNN
            self.pc = nnn
            
        elif first == 0x2:
            # 2NNN: Call subroutine at NNN
            self.stack[self.sp] = self.pc
            self.sp += 1
            self.pc = nnn
            
        elif first == 0x3:
            # 3XNN: Skip if VX == NN
            self.pc += 4 if self.v[x] == nn else 2
            
        elif first == 0x4:
            # 4XNN: Skip if VX != NN
            self.pc += 4 if self.v[x] != nn else 2
            
        elif first == 0x5 and n == 0:
            # 5XY0: Skip if VX == VY
            self.pc += 4 if self.v[x] == self.v[y] else 2
            
        elif first == 0x6:
            # 6XNN: VX = NN
            self.v[x] = nn
            self.pc += 2
            
        elif first == 0x7:
            # 7XNN: VX += NN (no carry)
            self.v[x] = (self.v[x] + nn) & 0xFF
            self.pc += 2
            
        elif first == 0x8:
            self._execute_8xxx(opcode, x, y, n)
            
        elif first == 0x9 and n == 0:
            # 9XY0: Skip if VX != VY
            self.pc += 4 if self.v[x] != self.v[y] else 2
            
        elif first == 0xA:
            # ANNN: I = NNN
            self.i = nnn
            self.pc += 2
            
        elif first == 0xB:
            # BNNN: Jump to NNN + V0
            self.pc = nnn + self.v[0]
            
        elif first == 0xC:
            # CXNN: VX = random & NN
            self.v[x] = random.randint(0, 255) & nn
            self.pc += 2
            
        elif first == 0xD:
            # DXYN: Draw sprite
            self._draw_sprite(x, y, n)
            self.pc += 2
            
        elif first == 0xE:
            if nn == 0x9E:
                # EX9E: Skip if key VX pressed
                self.pc += 4 if self.keys[self.v[x] & 0xF] else 2
            elif nn == 0xA1:
                # EXA1: Skip if key VX not pressed
                self.pc += 4 if not self.keys[self.v[x] & 0xF] else 2
            else:
                self.pc += 2
                
        elif first == 0xF:
            self._execute_fxxx(opcode, x, nn)
            
        else:
            # Unknown opcode, skip
            self.pc += 2
    
    def _execute_8xxx(self, opcode: int, x: int, y: int, n: int):
        """Execute 8xxx opcodes (ALU operations)"""
        if n == 0x0:
            # 8XY0: VX = VY
            self.v[x] = self.v[y]
        elif n == 0x1:
            # 8XY1: VX |= VY
            self.v[x] |= self.v[y]
            self.v[0xF] = 0  # Quirk: VF reset
        elif n == 0x2:
            # 8XY2: VX &= VY
            self.v[x] &= self.v[y]
            self.v[0xF] = 0  # Quirk: VF reset
        elif n == 0x3:
            # 8XY3: VX ^= VY
            self.v[x] ^= self.v[y]
            self.v[0xF] = 0  # Quirk: VF reset
        elif n == 0x4:
            # 8XY4: VX += VY with carry
            result = self.v[x] + self.v[y]
            self.v[x] = result & 0xFF
            self.v[0xF] = 1 if result > 255 else 0
        elif n == 0x5:
            # 8XY5: VX -= VY with borrow
            borrow = 1 if self.v[x] >= self.v[y] else 0
            self.v[x] = (self.v[x] - self.v[y]) & 0xFF
            self.v[0xF] = borrow
        elif n == 0x6:
            # 8XY6: VX >>= 1
            lsb = self.v[x] & 1
            self.v[x] = self.v[x] >> 1
            self.v[0xF] = lsb
        elif n == 0x7:
            # 8XY7: VX = VY - VX with borrow
            borrow = 1 if self.v[y] >= self.v[x] else 0
            self.v[x] = (self.v[y] - self.v[x]) & 0xFF
            self.v[0xF] = borrow
        elif n == 0xE:
            # 8XYE: VX <<= 1
            msb = (self.v[x] >> 7) & 1
            self.v[x] = (self.v[x] << 1) & 0xFF
            self.v[0xF] = msb
        
        self.pc += 2
    
    def _execute_fxxx(self, opcode: int, x: int, nn: int):
        """Execute Fxxx opcodes"""
        if nn == 0x07:
            # FX07: VX = delay timer
            self.v[x] = self.delay_timer
        elif nn == 0x0A:
            # FX0A: Wait for key press
            self.waiting_for_key = True
            self.key_register = x
            return  # Don't increment PC yet
        elif nn == 0x15:
            # FX15: delay timer = VX
            self.delay_timer = self.v[x]
        elif nn == 0x18:
            # FX18: sound timer = VX
            self.sound_timer = self.v[x]
        elif nn == 0x1E:
            # FX1E: I += VX
            self.i = (self.i + self.v[x]) & 0xFFFF
        elif nn == 0x29:
            # FX29: I = font sprite for VX
            self.i = FONT_START + (self.v[x] & 0xF) * 5
        elif nn == 0x33:
            # FX33: Store BCD of VX at I, I+1, I+2
            value = self.v[x]
            self.memory[self.i] = value // 100
            self.memory[self.i + 1] = (value // 10) % 10
            self.memory[self.i + 2] = value % 10
        elif nn == 0x55:
            # FX55: Store V0-VX at I
            for i in range(x + 1):
                self.memory[self.i + i] = self.v[i]
        elif nn == 0x65:
            # FX65: Load V0-VX from I
            for i in range(x + 1):
                self.v[i] = self.memory[self.i + i]
        
        self.pc += 2
    
    def _draw_sprite(self, x: int, y: int, n: int):
        """Draw sprite at (VX, VY) with height N"""
        px = self.v[x] % DISPLAY_WIDTH
        py = self.v[y] % DISPLAY_HEIGHT
        self.v[0xF] = 0
        
        for row in range(n):
            if py + row >= DISPLAY_HEIGHT:
                break
            sprite_byte = self.memory[self.i + row]
            
            for col in range(8):
                if px + col >= DISPLAY_WIDTH:
                    break
                if sprite_byte & (0x80 >> col):
                    dx = px + col
                    dy = py + row
                    if self.display[dy][dx] == 1:
                        self.v[0xF] = 1  # Collision
                    self.display[dy][dx] ^= 1
        
        self.draw_flag = True
    
    def key_pressed(self, key: int):
        """Handle key press"""
        if self.waiting_for_key:
            self.v[self.key_register] = key
            self.waiting_for_key = False
            self.pc += 2
    
    def update_timers(self):
        """Update delay and sound timers (call at 60Hz)"""
        if self.delay_timer > 0:
            self.delay_timer -= 1
        if self.sound_timer > 0:
            self.sound_timer -= 1
    
    def get_state(self) -> EmulatorState:
        """Get current state for save"""
        return EmulatorState(
            memory=bytearray(self.memory),
            v=list(self.v),
            i=self.i,
            pc=self.pc,
            stack=list(self.stack),
            sp=self.sp,
            delay_timer=self.delay_timer,
            sound_timer=self.sound_timer,
            display=[row[:] for row in self.display],
            keys=list(self.keys)
        )
    
    def load_state(self, state: EmulatorState):
        """Load state from save"""
        self.memory = bytearray(state.memory)
        self.v = list(state.v)
        self.i = state.i
        self.pc = state.pc
        self.stack = list(state.stack)
        self.sp = state.sp
        self.delay_timer = state.delay_timer
        self.sound_timer = state.sound_timer
        self.display = [row[:] for row in state.display]
        self.keys = list(state.keys)
        self.draw_flag = True


class Chip8Display:
    """Tkinter display renderer"""
    
    def __init__(self, canvas: tk.Canvas):
        self.canvas = canvas
        self.scale_x = WINDOW_WIDTH / DISPLAY_WIDTH
        self.scale_y = DISPLAY_AREA_HEIGHT / DISPLAY_HEIGHT
        self.scanlines_enabled = False
        self.pixel_rects = {}
        
        # Pre-create pixel rectangles for efficiency
        self._create_pixels()
    
    def _create_pixels(self):
        """Pre-create all pixel rectangles"""
        self.canvas.delete("all")
        self.pixel_rects = {}
        
        for y in range(DISPLAY_HEIGHT):
            for x in range(DISPLAY_WIDTH):
                x1 = x * self.scale_x
                y1 = y * self.scale_y
                x2 = x1 + self.scale_x
                y2 = y1 + self.scale_y
                
                rect = self.canvas.create_rectangle(
                    x1, y1, x2, y2,
                    fill=BG_COLOR, outline=""
                )
                self.pixel_rects[(x, y)] = rect
        
        # Create scanline overlay (initially hidden)
        self.scanline_rects = []
        if self.scanlines_enabled:
            self._create_scanlines()
    
    def _create_scanlines(self):
        """Create scanline overlay"""
        for rect in self.scanline_rects:
            self.canvas.delete(rect)
        self.scanline_rects = []
        
        if self.scanlines_enabled:
            for y in range(0, DISPLAY_AREA_HEIGHT, int(self.scale_y * 2)):
                rect = self.canvas.create_rectangle(
                    0, y + self.scale_y,
                    WINDOW_WIDTH, y + self.scale_y * 2,
                    fill="#000000", stipple="gray50", outline=""
                )
                self.scanline_rects.append(rect)
    
    def toggle_scanlines(self):
        """Toggle scanline effect"""
        self.scanlines_enabled = not self.scanlines_enabled
        self._create_scanlines()
    
    def render(self, display: list):
        """Render CHIP-8 display to canvas"""
        for y in range(DISPLAY_HEIGHT):
            for x in range(DISPLAY_WIDTH):
                color = PIXEL_COLOR if display[y][x] else BG_COLOR
                rect = self.pixel_rects.get((x, y))
                if rect:
                    self.canvas.itemconfig(rect, fill=color)


class Chip8GUI:
    """Main application GUI"""
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Cat's Chip-8 Emulator")
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.root.resizable(False, False)
        self.root.configure(bg=BG_COLOR)
        
        # Components
        self.cpu = Chip8CPU()
        self.audio = Chip8Audio()
        
        # State
        self.running = False
        self.paused = False
        self.speed_multiplier = 1
        self.fps = 0
        self.frame_count = 0
        self.last_fps_time = time.time()
        self.show_debug = False
        
        # Create UI
        self._create_ui()
        
        # Create display renderer
        self.display_renderer = Chip8Display(self.canvas)
        
        # Create controller
        self.controller = Chip8Controller(self._on_controller_key)
        self._setup_controller_callbacks()
        
        # Bind keyboard
        self._bind_keys()
        
        # Enable drag and drop
        self._setup_drag_drop()
        
        # Start controller polling
        self.controller.start()
        
        # Emulation thread
        self._emu_thread: Optional[threading.Thread] = None
        self._emu_running = False
        
        # Timer thread
        self._timer_thread: Optional[threading.Thread] = None
    
    def _create_ui(self):
        """Create UI components"""
        # Main canvas for display
        self.canvas = tk.Canvas(
            self.root,
            width=WINDOW_WIDTH,
            height=DISPLAY_AREA_HEIGHT,
            bg=BG_COLOR,
            highlightthickness=0
        )
        self.canvas.pack(side=tk.TOP)
        
        # Status bar
        self.status_frame = tk.Frame(
            self.root,
            height=STATUS_BAR_HEIGHT,
            bg=STATUS_BG
        )
        self.status_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_frame.pack_propagate(False)
        
        # Status labels
        self.rom_label = tk.Label(
            self.status_frame,
            text="No ROM",
            fg=STATUS_FG,
            bg=STATUS_BG,
            font=("Courier", 10)
        )
        self.rom_label.pack(side=tk.LEFT, padx=10)
        
        self.fps_label = tk.Label(
            self.status_frame,
            text="FPS: 0",
            fg=STATUS_FG,
            bg=STATUS_BG,
            font=("Courier", 10)
        )
        self.fps_label.pack(side=tk.LEFT, padx=10)
        
        self.controller_label = tk.Label(
            self.status_frame,
            text="Controller: None",
            fg=STATUS_FG,
            bg=STATUS_BG,
            font=("Courier", 10)
        )
        self.controller_label.pack(side=tk.LEFT, padx=10)
        
        self.state_label = tk.Label(
            self.status_frame,
            text="Stopped",
            fg=STATUS_FG,
            bg=STATUS_BG,
            font=("Courier", 10)
        )
        self.state_label.pack(side=tk.RIGHT, padx=10)
        
        self.speed_label = tk.Label(
            self.status_frame,
            text="1×",
            fg=STATUS_FG,
            bg=STATUS_BG,
            font=("Courier", 10)
        )
        self.speed_label.pack(side=tk.RIGHT, padx=10)
    
    def _bind_keys(self):
        """Bind keyboard events"""
        self.root.bind("<KeyPress>", self._on_key_down)
        self.root.bind("<KeyRelease>", self._on_key_up)
        
        # Control keys
        self.root.bind("<Control-r>", lambda e: self._reset())
        self.root.bind("<space>", lambda e: self._toggle_pause())
        self.root.bind("<F5>", lambda e: self._save_state())
        self.root.bind("<F7>", lambda e: self._load_state())
        self.root.bind("<F1>", lambda e: self._decrease_speed())
        self.root.bind("<F2>", lambda e: self._increase_speed())
        self.root.bind("<F3>", lambda e: self._toggle_scanlines())
    
    def _on_key_down(self, event):
        """Handle key press"""
        key = event.keysym.lower()
        if key in KEYBOARD_MAP:
            chip8_key = KEYBOARD_MAP[key]
            self.cpu.keys[chip8_key] = True
            self.cpu.key_pressed(chip8_key)
    
    def _on_key_up(self, event):
        """Handle key release"""
        key = event.keysym.lower()
        if key in KEYBOARD_MAP:
            chip8_key = KEYBOARD_MAP[key]
            self.cpu.keys[chip8_key] = False
    
    def _on_controller_key(self, key: int, pressed: bool):
        """Handle controller key change"""
        self.cpu.keys[key] = pressed
        if pressed:
            self.cpu.key_pressed(key)
    
    def _setup_controller_callbacks(self):
        """Setup controller action callbacks"""
        self.controller.on_reset = self._reset
        self.controller.on_pause_toggle = self._toggle_pause
        self.controller.on_save_state = self._save_state
        self.controller.on_load_state = self._load_state
        self.controller.on_speed_increase = self._increase_speed
        self.controller.on_speed_decrease = self._decrease_speed
        self.controller.on_toggle_scanlines = self._toggle_scanlines
        self.controller.on_debug_toggle = self._toggle_debug
    
    def _setup_drag_drop(self):
        """Setup drag and drop for ROM loading"""
        # Tkinter doesn't have native drag-drop, so we'll use a file dialog fallback
        self.root.bind("<Button-1>", self._on_click)
        
        # Try to enable TkDnD if available
        try:
            self.root.tk.call('package', 'require', 'tkdnd')
            self.root.tk.call('tkdnd::drop_target', 'register', self.canvas, '*')
            self.canvas.bind('<<Drop>>', self._on_drop)
        except:
            pass  # TkDnD not available
    
    def _on_click(self, event):
        """Handle click - show file dialog if no ROM loaded"""
        if not self.cpu.rom_loaded:
            self._open_file_dialog()
    
    def _on_drop(self, event):
        """Handle file drop"""
        filepath = event.data
        if filepath.endswith('.ch8'):
            self._load_rom(filepath)
    
    def _open_file_dialog(self):
        """Open file dialog to select ROM"""
        from tkinter import filedialog
        filepath = filedialog.askopenfilename(
            title="Select CHIP-8 ROM",
            filetypes=[("CHIP-8 ROM", "*.ch8"), ("All files", "*.*")]
        )
        if filepath:
            self._load_rom(filepath)
    
    def _load_rom(self, filepath: str):
        """Load ROM from file"""
        try:
            with open(filepath, 'rb') as f:
                data = f.read()
            name = os.path.basename(filepath)
            self.cpu.load_rom(data, name)
            self.rom_label.config(text=f"ROM: {name}")
            self._start_emulation()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load ROM: {e}")
    
    def _start_emulation(self):
        """Start emulation threads"""
        if self._emu_running:
            return
        
        self._emu_running = True
        self.running = True
        self.paused = False
        self._update_status()
        
        # CPU thread
        self._emu_thread = threading.Thread(target=self._emulation_loop, daemon=True)
        self._emu_thread.start()
        
        # Timer thread
        self._timer_thread = threading.Thread(target=self._timer_loop, daemon=True)
        self._timer_thread.start()
        
        # Start render loop
        self._render_loop()
    
    def _emulation_loop(self):
        """Main emulation loop running at CPU_FREQUENCY"""
        cycles_per_frame = (CPU_FREQUENCY * self.speed_multiplier) // TARGET_FPS
        
        while self._emu_running:
            if not self.paused:
                try:
                    for _ in range(cycles_per_frame):
                        self.cpu.cycle()
                except Exception as e:
                    print(f"CPU Error: {e}")
                    # Auto-reset after crash
                    time.sleep(2)
                    self._reset()
            
            # Sleep to maintain timing
            time.sleep(1 / TARGET_FPS)
    
    def _timer_loop(self):
        """Timer update loop at 60Hz"""
        while self._emu_running:
            if not self.paused:
                self.cpu.update_timers()
                self.audio.update(self.cpu.sound_timer)
            time.sleep(1 / TIMER_FREQUENCY)
    
    def _render_loop(self):
        """Render loop for display updates"""
        if not self._emu_running:
            return
        
        # Render if draw flag set
        if self.cpu.draw_flag:
            self.display_renderer.render(self.cpu.display)
            self.cpu.draw_flag = False
        
        # Update FPS counter
        self.frame_count += 1
        now = time.time()
        if now - self.last_fps_time >= 1.0:
            self.fps = self.frame_count
            self.frame_count = 0
            self.last_fps_time = now
            self.fps_label.config(text=f"FPS: {self.fps}")
        
        # Update controller status
        self._update_controller_status()
        
        # Schedule next render
        self.root.after(1000 // TARGET_FPS, self._render_loop)
    
    def _update_controller_status(self):
        """Update controller status in UI"""
        if self.controller.connected:
            battery_str = ""
            if self.controller.battery_level >= 0:
                battery_str = f" ({self.controller.battery_level}%)"
            self.controller_label.config(
                text=f"Controller: {self.controller.connection_type}{battery_str}"
            )
        else:
            self.controller_label.config(text="Controller: None")
    
    def _update_status(self):
        """Update status display"""
        if self.paused:
            self.state_label.config(text="Paused")
        elif self.running:
            self.state_label.config(text="Running")
        else:
            self.state_label.config(text="Stopped")
        
        self.speed_label.config(text=f"{self.speed_multiplier}×")
    
    def _reset(self):
        """Reset emulator"""
        if self.cpu.rom_loaded:
            # Reload current ROM
            rom_data = bytes(self.cpu.memory[PROGRAM_START:])
            name = self.cpu.rom_name
            self.cpu.load_rom(rom_data, name)
            self.display_renderer.render(self.cpu.display)
    
    def _toggle_pause(self):
        """Toggle pause state"""
        self.paused = not self.paused
        self._update_status()
    
    def _save_state(self):
        """Save current state to slot 0"""
        if not self.cpu.rom_loaded:
            return
        
        state = self.cpu.get_state()
        save_path = f"{self.cpu.rom_name}.sav"
        try:
            with open(save_path, 'wb') as f:
                pickle.dump(state, f)
        except Exception as e:
            print(f"Save failed: {e}")
    
    def _load_state(self):
        """Load state from slot 0"""
        if not self.cpu.rom_loaded:
            return
        
        save_path = f"{self.cpu.rom_name}.sav"
        try:
            with open(save_path, 'rb') as f:
                state = pickle.load(f)
            self.cpu.load_state(state)
            self.display_renderer.render(self.cpu.display)
        except FileNotFoundError:
            pass  # No save file
        except Exception as e:
            print(f"Load failed: {e}")
    
    def _increase_speed(self):
        """Increase emulation speed"""
        if self.speed_multiplier < 8:
            self.speed_multiplier *= 2
            self._update_status()
    
    def _decrease_speed(self):
        """Decrease emulation speed"""
        if self.speed_multiplier > 1:
            self.speed_multiplier //= 2
            self._update_status()
    
    def _toggle_scanlines(self):
        """Toggle scanline effect"""
        self.display_renderer.toggle_scanlines()
    
    def _toggle_debug(self):
        """Toggle debug overlay"""
        self.show_debug = not self.show_debug
        # Debug overlay would show registers, memory, etc.
        # For now, just print to console
        if self.show_debug:
            print(f"PC: {self.cpu.pc:04X}")
            print(f"I: {self.cpu.i:04X}")
            print(f"V: {[f'{v:02X}' for v in self.cpu.v]}")
    
    def run(self):
        """Run the application"""
        # Handle window close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        
        # Start main loop
        self.root.mainloop()
    
    def _on_close(self):
        """Handle window close"""
        self._emu_running = False
        self.controller.stop()
        self.audio.stop_beep()
        self.root.destroy()


def main():
    """Main entry point"""
    app = Chip8GUI()
    
    # Check for command line ROM argument
    if len(sys.argv) > 1:
        rom_path = sys.argv[1]
        if os.path.exists(rom_path):
            app._load_rom(rom_path)
    
    app.run()


if __name__ == "__main__":
    main()
