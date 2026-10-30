import unittest
from unittest.mock import MagicMock, patch
from dragonpong.controls import ControllerInput


class ControlsTests(unittest.TestCase):
    def controller(self):
        control = ControllerInput.__new__(ControllerInput)
        control.backend = MagicMock()
        control.backend.error = RuntimeError
        control.devices, control.buttons, control.next_move = {}, {}, 0
        device = control.backend.joystick.Joystick.return_value
        control.backend.joystick.get_count.return_value = 1
        device.get_instance_id.return_value = 7
        device.get_numbuttons.return_value = 1
        device.get_button.return_value = 1
        device.get_numaxes.return_value = 1
        device.get_axis.return_value = .8
        device.get_numhats.return_value = 0
        return control

    def test_button_edge_and_stick_repeat_limit(self):
        control = self.controller()
        with patch('dragonpong.controls.time.monotonic', return_value=1):
            self.assertEqual(control.poll(True), ['Up', 'Right'])
            self.assertEqual(control.poll(True), [])
        with patch('dragonpong.controls.time.monotonic', return_value=1.064):
            self.assertEqual(control.poll(True), ['Right'])

    def test_unfocused_controller_does_not_control_game(self):
        control = self.controller()
        self.assertEqual(control.poll(False), [])
