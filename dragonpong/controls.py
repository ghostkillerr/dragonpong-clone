"""Optional SDL joystick controls, translated to ordinary game keys."""
import os
import time


class ControllerInput:
    def __init__(self):
        self.backend = None
        self.devices = {}
        self.buttons = {}
        self.next_move = 0
        try:
            os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')
            import pygame
            pygame.display.init()
            pygame.joystick.init()
            self.backend = pygame
        except (ImportError, RuntimeError):
            pass

    def poll(self, active: bool):
        if not self.backend:
            return []
        keys = []
        try:
            self.backend.event.pump()
            current = {}
            now = time.monotonic()
            for index in range(self.backend.joystick.get_count()):
                device = self.backend.joystick.Joystick(index)
                if not device.get_init():
                    device.init()
                identity = device.get_instance_id()
                current[identity] = device
                pressed = bool(device.get_numbuttons() and device.get_button(0))
                if active and pressed and not self.buttons.get(identity, False):
                    keys.append('Up')
                self.buttons[identity] = pressed
                axis = device.get_axis(0) if device.get_numaxes() else 0
                hat = device.get_hat(0)[0] if device.get_numhats() else 0
                direction = hat or (1 if axis > .5 else -1 if axis < -.5 else 0)
                if active and direction and now >= self.next_move:
                    keys.append('Right' if direction > 0 else 'Left')
                    self.next_move = now + .063
            self.devices = current
        except self.backend.error:
            self.devices.clear()
        return keys

    def close(self):
        if self.backend:
            self.backend.joystick.quit()
