import unittest
from unittest.mock import patch

from vue_api.kdzn_hciqa.engine_dependencies.prompt_builders import (
    get_domain_desc,
    get_prompt_config,
)


class PromptBuilderTests(unittest.TestCase):
    def test_domain_description_uses_prompt_repository(self):
        with patch(
            "vue_api.kdzn_hciqa.engine_dependencies.prompt_builders.get_prompt_config",
            return_value={"chitchat_domain_desc": "轨交设备诊断"},
        ):
            self.assertEqual(get_domain_desc("轨交诊断"), "轨交设备诊断")

    def test_prompt_config_handles_database_unavailable(self):
        with patch(
            "vue_api.kdzn_hciqa.engine_dependencies.prompt_builders.connect_to_db",
            return_value=None,
        ):
            self.assertEqual(get_prompt_config("missing"), {})


if __name__ == "__main__":
    unittest.main()
