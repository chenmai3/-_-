import unittest

from vue_api.kdzn_hciqa.engine_dependencies.graph_rule_queries.rule_template import (
    UnresolvedRulePlaceholderError,
    build_match_info,
    render_cypher,
)


class RuleTemplateTests(unittest.TestCase):
    def test_render_cypher_replaces_rule_entity_placeholders(self):
        info = build_match_info(
            {
                "R1Name": "变压器本体",
                "R2Name": "变压器本体吱吱声",
                "RIName": "接触不良放电",
            }
        )
        template = (
            'MATCH p=(part{name:"{r1name}"})-[]->'
            '(phenomenon{name:"{r2name}"})-[]->(cause{name:"{riname}"}) RETURN p'
        )

        rendered = render_cypher(template, info, "变压器发出吱吱声")

        self.assertNotIn("{r1name}", rendered)
        self.assertNotIn("{r2name}", rendered)
        self.assertNotIn("{riname}", rendered)
        self.assertIn('name:"变压器本体吱吱声"', rendered)

    def test_render_cypher_supports_legacy_aliases_and_escapes_values(self):
        info = build_match_info(
            {"R1Name": '部件"A', "R2Name": "周期", "RIName": "项目"},
            match_span="完整入口实体",
        )
        template = (
            "RETURN '{partname}', '{cyclename}', '{itemname}', '{faultname}', "
            "'{phenomenon}', '{entityname}', '{match_span}', '{query}'"
        )

        rendered = render_cypher(template, info, "用户问题")

        self.assertNotIn("{", rendered)
        self.assertIn('部件\\"A', rendered)
        self.assertIn("完整入口实体", rendered)
        self.assertIn("用户问题", rendered)

    def test_render_cypher_rejects_unknown_placeholder(self):
        with self.assertRaisesRegex(UnresolvedRulePlaceholderError, "unknown_name"):
            render_cypher("MATCH (n{name:'{unknown_name}'}) RETURN n", {})


if __name__ == "__main__":
    unittest.main()
