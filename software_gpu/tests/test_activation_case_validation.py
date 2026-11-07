"""Regression: Android UDS activation types obey the dispatcher's case-insensitive contract."""
import unittest

from software_gpu.network.security import RequestRejected, SecurityLimits, validate_request


class ActivationCaseValidationTest(unittest.TestCase):
    """Keep input validation aligned with the actual activation dispatcher."""

    def test_supported_activation_names_are_case_insensitive(self):
        for kind in ("relu", "RELU", "ReLu", "gelu", "GELU", "GeLu"):
            with self.subTest(kind=kind):
                validate_request("activation", {"x": [-2.0, 0.5], "type": kind}, SecurityLimits())

    def test_unsupported_or_nonstring_activation_is_rejected(self):
        for kind in ("relu2", "gelu_random", 1, True, [], None):
            with self.subTest(kind=repr(kind)):
                with self.assertRaises(RequestRejected):
                    validate_request("activation", {"x": [-2.0, 0.5], "type": kind}, SecurityLimits())


if __name__ == "__main__":
    unittest.main()
