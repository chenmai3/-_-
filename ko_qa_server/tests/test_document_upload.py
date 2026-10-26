import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from ko_qa_server import create_app


class DocumentUploadTests(unittest.TestCase):
    def test_both_upload_routes_save_and_index_the_user_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bot = Mock()
            with patch('vue_api.kdzn_hciqa.document_upload.user_file_vector_store.get_kochatbot', return_value=bot), patch(
                'vue_api.kdzn_hciqa.document_upload.user_file_vector_store.UPLOAD_FILE_ROOT', root / 'uploads',
            ), patch('vue_api.kdzn_hciqa.document_upload.user_file_vector_store.USER_VECTOR_STORES_ROOT', root / 'vectors'):
                with TestClient(create_app()) as client:
                    for route in ('/upload', '/api/kdzn_qa/upload'):
                        with self.subTest(route=route):
                            response = client.post(route, data={'userId': 'test-user', 'scene_choose': '家谱问答'},
                                                   files={'file': ('资料.txt', '测试内容'.encode('utf-8'), 'text/plain')})
                            self.assertEqual(response.status_code, 200)
                            self.assertEqual(response.json(), {'msg': '文件接收成功'})
                            saved = root / 'uploads' / 'test-user' / '资料.txt'
                            self.assertEqual(saved.read_text(encoding='utf-8'), '测试内容')
                            bot.update_vector_stores.assert_called_with(str(saved), '资料.txt', 'test-user', 'TXT')

    def test_indexing_errors_remain_visible_on_the_legacy_gateway_route(self):
        with patch('vue_api.kdzn_hciqa.document_upload.user_file_vector_store.get_kochatbot', side_effect=RuntimeError('Embedding 服务调用失败：账号不可用')):
            with TestClient(create_app()) as client:
                response = client.post('/upload', data={'userId': 'test-user', 'scene_choose': '家谱问答'},
                                       files={'file': ('check.txt', b'check', 'text/plain')})
        self.assertEqual(response.status_code, 500)
        self.assertIn('账号不可用', response.json()['msg'])


if __name__ == '__main__':
    unittest.main()
