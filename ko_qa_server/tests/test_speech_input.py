import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from ko_qa_server import create_app
from vue_api.kdzn_hciqa.speech_recognition.speech_to_text import get_asr_settings
from vue_api.kdzn_hciqa.speech_recognition.xfyun_asr_client import XfyunSpeedAsrClient


MODULE = 'vue_api.kdzn_hciqa.speech_recognition.speech_to_text'


class SpeechInputTests(unittest.TestCase):
    def test_legacy_and_current_routes_convert_recognize_and_clean_up(self):
        with tempfile.TemporaryDirectory() as directory:
            def convert(source, destination):
                self.assertEqual(source.read_bytes(), b'browser-audio')
                destination.write_bytes(b'converted-wav')

            with patch(MODULE + '.UPLOAD_DIR', Path(directory)), patch(MODULE + '.convert_to_wav', side_effect=convert), patch(
                MODULE + '.my_asr_api_speed', return_value='请问变压器异响怎么处理？',
            ) as transcribe:
                with TestClient(create_app()) as client:
                    for route in ('/speech-to-text', '/speechToText', '/api/kdzn_qa/speechToText'):
                        with self.subTest(route=route):
                            response = client.post(route, files={'file': ('record.webm', b'browser-audio', 'audio/webm')})
                            self.assertEqual(response.status_code, 200)
                            self.assertEqual(response.json(), {'code': 200, 'text': '请问变压器异响怎么处理？'})
                            self.assertEqual(list(Path(directory).iterdir()), [])
                self.assertEqual(transcribe.call_count, 3)

    def test_conversion_failure_is_visible_and_temporary_audio_is_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch(MODULE + '.UPLOAD_DIR', Path(directory)), patch(MODULE + '.convert_to_wav', side_effect=RuntimeError('未找到 FFmpeg')), patch(
                MODULE + '.my_asr_api_speed',
            ) as transcribe:
                with TestClient(create_app()) as client:
                    response = client.post('/speech-to-text', files={'file': ('record.webm', b'audio', 'audio/webm')})
                self.assertEqual(response.status_code, 500)
                self.assertIn('FFmpeg', response.json()['msg'])
                self.assertEqual(response.json()['stage'], '音频转码')
                self.assertTrue(response.json()['request_id'])
                self.assertEqual(list(Path(directory).iterdir()), [])
                transcribe.assert_not_called()

    def test_provider_failure_logs_the_stage_and_preserves_the_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch(MODULE + '.UPLOAD_DIR', Path(directory)), patch(MODULE + '.convert_to_wav'), patch(
                MODULE + '.my_asr_api_speed', side_effect=RuntimeError('讯飞拒绝创建任务（11200）'),
            ), self.assertLogs(MODULE, level='ERROR') as logs:
                with TestClient(create_app()) as client:
                    response = client.post('/api/kdzn_qa/speechToText', files={'file': ('record.webm', b'audio', 'audio/webm')})
            self.assertEqual(response.status_code, 500)
            self.assertIn('11200', response.json()['msg'])
            self.assertEqual(response.json()['stage'], '讯飞语音识别')
            self.assertIn('讯飞语音识别', logs.output[0])
            self.assertIn('11200', logs.output[0])

    def test_empty_audio_is_rejected_before_conversion(self):
        with patch(MODULE + '.convert_to_wav') as convert:
            with TestClient(create_app()) as client:
                response = client.post('/speech-to-text', files={'file': ('empty.webm', b'', 'audio/webm')})
        self.assertEqual(response.status_code, 400)
        convert.assert_not_called()

    def test_dedicated_asr_credentials_and_environment_override_chat_credentials(self):
        config = {
            'speech_recognition': {'app_id': 'asr-app', 'api_key': 'asr-key', 'api_secret': 'asr-secret', 'ffmpeg_path': 'local-ffmpeg'},
            'qa_models': {'spark': {'appid': 'chat-app', 'api_keys': 'chat-key', 'api_secret': 'chat-secret'}},
        }
        with patch(MODULE + '.load_config', return_value=config), patch.dict(os.environ, {}, clear=True):
            settings = get_asr_settings()
            self.assertEqual(settings['app_id'], 'asr-app')
            self.assertEqual(settings['api_key'], 'asr-key')
            self.assertEqual(settings['api_secret'], 'asr-secret')
            self.assertEqual(settings['ffmpeg_path'], 'local-ffmpeg')
            with patch.dict(os.environ, {'XF_APP_ID': 'environment-app', 'FFMPEG_PATH': 'environment-ffmpeg'}):
                self.assertEqual(get_asr_settings()['app_id'], 'environment-app')
                self.assertEqual(get_asr_settings()['ffmpeg_path'], 'environment-ffmpeg')

    def test_provider_transcripts_support_json_strings_without_duplicate_text(self):
        content = {'ws': [{'cw': [{'w': '变压器'}]}, {'cw': [{'w': '异响'}]}]}
        for value in (content, json.dumps(content)):
            payload = {'data': {'result': {'lattice2': [{'json_1best': value}], 'lattice': [{'json_1best': content}]}}}
            self.assertEqual(XfyunSpeedAsrClient._extract_text(payload), '变压器异响')

    def test_provider_http_500_license_error_has_an_actionable_message(self):
        response = Mock(status_code=500)
        response.json.return_value = {'code': 11200, 'message': 'licc failed'}
        with self.assertRaisesRegex(RuntimeError, '暂时无法创建转写任务.*11200.*录音文件转写极速版'):
            XfyunSpeedAsrClient._response_json(response, '创建转写任务')

    def test_temporary_rejection_retries_the_same_request_then_recovers(self):
        rejected = Mock(status_code=500)
        rejected.json.return_value = {'code': 11200, 'message': 'licc failed'}
        accepted = Mock(status_code=200)
        accepted.json.return_value = {'code': 0, 'data': {'task_id': 'recovered-task'}}
        client = XfyunSpeedAsrClient('test-app', 'test-key', 'test-secret')
        with patch('os.path.getsize', return_value=16000), patch(
            'vue_api.kdzn_hciqa.speech_recognition.xfyun_asr_client.requests.post', side_effect=[rejected, accepted],
        ) as post, patch('vue_api.kdzn_hciqa.speech_recognition.xfyun_asr_client.time.sleep') as sleep:
            self.assertEqual(client._create_task('https://test.invalid/record.wav', 'record.wav'), 'recovered-task')
        self.assertEqual(post.call_args_list[0].kwargs['data'], post.call_args_list[1].kwargs['data'])
        sleep.assert_called_once_with(1)

    def test_permanent_rejections_stop_after_two_retries(self):
        rejected = Mock(status_code=500)
        rejected.json.return_value = {'code': 11200, 'message': 'licc failed'}
        client = XfyunSpeedAsrClient('test-app', 'test-key', 'test-secret')
        with patch('os.path.getsize', return_value=16000), patch(
            'vue_api.kdzn_hciqa.speech_recognition.xfyun_asr_client.requests.post', return_value=rejected,
        ) as post, patch('vue_api.kdzn_hciqa.speech_recognition.xfyun_asr_client.time.sleep'):
            with self.assertRaisesRegex(RuntimeError, '11200'):
                client._create_task('https://test.invalid/record.wav', 'record.wav')
        self.assertEqual(post.call_count, 3)


if __name__ == '__main__':
    unittest.main()
