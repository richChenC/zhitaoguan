import os
import unittest
from unittest.mock import patch

from src.backend import server


class DesktopServiceHealthTests(unittest.TestCase):
    def test_instance_identifier_is_returned_for_desktop_service(self):
        with patch.dict(os.environ, {"THIMBLE_DESKTOP_INSTANCE": "instance-for-test"}):
            self.assertEqual(server.health_status()["desktop_instance"], "instance-for-test")

    def test_standalone_service_has_no_desktop_instance(self):
        environment = {key: value for key, value in os.environ.items()
                       if key != "THIMBLE_DESKTOP_INSTANCE"}
        with patch.dict(os.environ, environment, clear=True):
            self.assertNotIn("desktop_instance", server.health_status())
