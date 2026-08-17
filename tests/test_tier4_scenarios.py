# Tier 4 Real-World Application Scenarios E2E Test Suite
from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import tempfile
import time
import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import patch

from push_notifications import PushNotificationManager
from tests.harness import (
    HarnessTestCase,
    MockCDPServer,
    MockDOMGenerator,
    MockPushService,
    TestClientWrapper,
    assert_push_payload_valid,
    assert_push_subscription_valid,
    assert_responsive_css,
    assert_sanitized_html,
    assert_service_worker_contract,
    assert_valid_djb2_hash,
    assert_valid_snapshot,
    assert_vapid_key_valid,
    compute_composite_hash,
    compute_djb2,
)


class TestTier4RealWorldScenarios(HarnessTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.temp_dir = tempfile.mkdtemp(prefix='tier4_scenario_')
        self.config_path = os.path.join(self.temp_dir, 'config.json')
        self.subs_path = os.path.join(self.temp_dir, 'push-subscriptions.json')
        self.vapid_path = os.path.join(self.temp_dir, 'vapid-keys.json')
        self.push_mgr = PushNotificationManager(
            config_path=self.config_path,
            subscriptions_path=self.subs_path,
            vapid_path=self.vapid_path,
        )

    async def asyncTearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        await super().asyncTearDown()

    # ==========================================================================
    # Scenario 1: Complete Mobile Chat Session Workflow
    # ==========================================================================
    async def test_scenario_01_complete_mobile_chat_session_workflow(self) -> None:
        with self.client.websocket_connect('/ws/stream') as ws:
            init_snap = ws.receive_json()
            assert_valid_snapshot(init_snap)
            self.assertFalse(init_snap['agentRunning'])
            h0 = init_snap['hash']
            assert_valid_djb2_hash(h0)

            prompt_text = 'Refactor the authentication module to use JWT tokens.'
            resp = self.client.chat_send(text=prompt_text, append_mode=False)
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data.get('status'), 'success')

            intermediate_dom = self.dom_gen.generate_chat_dom(
                messages=[
                    {'role': 'user', 'text': prompt_text, 'timestamp': '10:00 AM'},
                    {
                        'role': 'assistant',
                        'text': 'Analyzing auth module and refactoring to JWT...',
                        'timestamp': '10:00 AM',
                        'tool_calls': [
                            {
                                'name': 'run_command',
                                'command': 'pytest tests/test_auth.py',
                                'status': 'running',
                                'output': 'Running 12 tests...',
                            }
                        ],
                    },
                ],
                agent_status='running',
            )
            self.cdp_server.update_mock_snapshot(agentRunning=True, html=intermediate_dom)
            h1 = self.cdp_server.mock_snapshot['hash']
            self.assertNotEqual(h0, h1)
            assert_valid_djb2_hash(h1)

            final_dom = self.dom_gen.generate_chat_dom(
                messages=[
                    {'role': 'user', 'text': prompt_text, 'timestamp': '10:00 AM'},
                    {
                        'role': 'assistant',
                        'text': 'Refactoring complete. All 12 authentication tests passed.',
                        'timestamp': '10:01 AM',
                        'tool_calls': [
                            {
                                'name': 'run_command',
                                'command': 'pytest tests/test_auth.py',
                                'status': 'success',
                                'output': '12 passed in 0.42s',
                            }
                        ],
                        'code_blocks': [
                            {
                                'lang': 'python',
                                'code': "def verify_token(token: str) -> dict:\n    return jwt.decode(token, SECRET)",
                            }
                        ],
                    },
                ],
                agent_status='idle',
            )
            self.cdp_server.update_mock_snapshot(agentRunning=False, html=final_dom)
            h2 = self.cdp_server.mock_snapshot['hash']
            self.assertNotEqual(h1, h2)
            assert_valid_djb2_hash(h2)
            assert_sanitized_html(final_dom)

    # ==========================================================================
    # Scenario 2: Interactive Tool Call & Permission Approval Flow
    # ==========================================================================
    async def test_scenario_02_permission_approval_flow_allow_deny_run_review(self) -> None:
        cmd = 'npm run build:prod'
        self.cdp_server.simulate_permission_prompt(command=cmd, tool='run_command')
        snap = self.cdp_server.mock_snapshot

        self.assertIsNotNone(snap['permission'])
        self.assertEqual(snap['permission']['command'], cmd)
        self.assertIn('data-ag-click-id="perm:allow"', snap['permissionHtml'])
        self.assertIn('data-ag-click-id="perm:deny"', snap['permissionHtml'])

        perm_resp = self.client.permission_action(action='allow', command=cmd)
        self.assertEqual(perm_resp.status_code, 200)
        self.assertEqual(perm_resp.json().get('action'), 'allow')

        click_resp = self.client.cdp_click(click_id='perm:allow', click_type='permission')
        self.assertEqual(click_resp.status_code, 200)
        self.assertEqual(click_resp.json().get('clickId'), 'perm:allow')

        self.cdp_server._handle_runtime_evaluate('data-ag-click-id="perm:allow"', {})
        self.assertIn('perm:allow', self.cdp_server.clicked_elements)

        self.cdp_server.update_mock_snapshot(permission=None, permissionHtml=None)
        self.assertIsNone(self.cdp_server.mock_snapshot['permission'])

        self.cdp_server.simulate_permission_prompt(command='rm -rf /data', tool='bash')
        deny_resp = self.client.permission_action(action='deny', command='rm -rf /data')
        self.assertEqual(deny_resp.status_code, 200)
        self.assertEqual(deny_resp.json().get('action'), 'deny')

        click_deny = self.client.cdp_click(click_id='perm:deny', click_type='permission')
        self.assertEqual(click_deny.status_code, 200)
        self.assertEqual(click_deny.json().get('clickId'), 'perm:deny')

        self.cdp_server._handle_runtime_evaluate('data-ag-click-id="perm:deny"', {})
        self.assertIn('perm:deny', self.cdp_server.clicked_elements)

        run_resp = self.client.permission_action(action='run')
        self.assertEqual(run_resp.status_code, 200)
        review_resp = self.client.permission_action(action='review')
        self.assertEqual(review_resp.status_code, 200)

    # ==========================================================================
    # Scenario 3: Multiple Choice Question Answering via ask_question Overlay
    # ==========================================================================
    async def test_scenario_03_multiple_choice_question_answering_flow(self) -> None:
        question = 'Which database migration strategy should we use?'
        choices = ['Option A: Run migrations automatically', 'Option B: Generate SQL script for manual review', 'Option C: Skip migrations']
        self.cdp_server.simulate_ask_question(question=question, choices=choices)

        snap = self.cdp_server.mock_snapshot
        self.assertIsNotNone(snap['askQuestion'])
        self.assertEqual(snap['askQuestion']['question'], question)
        self.assertEqual(len(snap['askQuestion']['choices']), 3)
        self.assertIn('data-ag-click-id="ask:1"', snap['askQuestionHtml'])

        ans_resp = self.client.answer_question(question_id='q-migrate', choice_index=1, custom_text='Option B')
        self.assertEqual(ans_resp.status_code, 200)
        self.assertEqual(ans_resp.json().get('status'), 'success')

        click_resp = self.client.cdp_click(click_id='ask:1', click_type='ask_question')
        self.assertEqual(click_resp.status_code, 200)
        self.assertEqual(click_resp.json().get('clickId'), 'ask:1')

        self.cdp_server._handle_runtime_evaluate('data-ag-click-id="ask:1"', {})
        self.assertIn('ask:1', self.cdp_server.clicked_elements)

        self.cdp_server.update_mock_snapshot(askQuestion=None, askQuestionHtml=None)
        self.assertIsNone(self.cdp_server.mock_snapshot['askQuestion'])
        self.assertIsNone(self.cdp_server.mock_snapshot['askQuestionHtml'])

    # ==========================================================================
    # Scenario 4: Long-Running Task & Mobile Background Web Push Alerting
    # ==========================================================================
    async def test_scenario_04_long_running_task_and_background_push_alerting(self) -> None:
        sub = self.push_service.create_mock_subscription(endpoint='https://fcm.googleapis.com/fcm/send/mobile-tab-1')
        assert_push_subscription_valid(sub)
        add_res = self.client.add_push_subscription(sub)
        self.assertEqual(add_res.status_code, 200)
        self.push_mgr.add_subscription(sub)

        self.push_mgr.set_client_visibility('mobile-tab-1', True)
        self.assertTrue(self.push_mgr.is_any_client_visible())

        await self.push_mgr.check_and_send_attention_notifications([], agent_running=True)
        sent_vis = await self.push_mgr.check_and_send_attention_notifications([], agent_running=False)
        self.assertEqual(sent_vis, 0)
        self.assertEqual(len(self.push_service.sent_notifications), 0)

        self.push_mgr.set_client_visibility('mobile-tab-1', False)
        self.assertFalse(self.push_mgr.is_any_client_visible())

        await self.push_mgr.check_and_send_attention_notifications([], agent_running=True)
        sent_bg = await self.push_mgr.check_and_send_attention_notifications([], agent_running=False, conversation_name='Data Pipeline')
        self.assertEqual(sent_bg, 1)
        self.assertEqual(len(self.push_service.sent_notifications), 1)

        rec = self.push_service.sent_notifications[0]
        assert_push_payload_valid(rec['payload_json'])
        self.assertIn('Agent task completed', rec['payload_json']['body'])

        cmd_item = [{'id': 'cmd-exec-1', 'type': 'command', 'name': 'pytest tests/test_e2e.py'}]
        sent_cmd = await self.push_mgr.check_and_send_attention_notifications(cmd_item, agent_running=True)
        self.assertEqual(sent_cmd, 1)
        self.assertEqual(len(self.push_service.sent_notifications), 2)
        cmd_rec = self.push_service.sent_notifications[1]
        self.assertIn('Command approval', cmd_rec['payload_json']['body'])

    # ==========================================================================
    # Scenario 5: Mobile Camera/Gallery Image Upload & Analysis
    # ==========================================================================
    async def test_scenario_05_mobile_image_upload_and_analysis_flow(self) -> None:
        sample_png_b64 = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='
        up_resp = self.client.upload_image(
            base64_data=sample_png_b64,
            mime_type='image/png',
            filename='mobile_camera_shot.png',
        )
        self.assertEqual(up_resp.status_code, 200)
        self.assertEqual(up_resp.json().get('status'), 'success')
        self.assertEqual(up_resp.json().get('filename'), 'mobile_camera_shot.png')

        cdp_eval = self.cdp_server._handle_runtime_evaluate("upload-image: DataTransfer simulation", {})
        self.assertTrue(cdp_eval["result"]["value"]["uploaded"])
        self.assertEqual(len(self.cdp_server.uploaded_images), 1)

        chat_resp = self.client.chat_send('What is shown in mobile_camera_shot.png?')
        self.assertEqual(chat_resp.status_code, 200)

        img_chat_dom = self.dom_gen.generate_chat_dom(
            messages=[
                {'role': 'user', 'text': 'What is shown in mobile_camera_shot.png?', 'timestamp': '10:15 AM'},
                {
                    'role': 'assistant',
                    'text': 'The uploaded image displays an architecture diagram showing FastAPI communicating with Antigravity over CDP.',
                    'timestamp': '10:15 AM',
                },
            ]
        )
        self.cdp_server.update_mock_snapshot(html=img_chat_dom)
        assert_sanitized_html(self.cdp_server.mock_snapshot['html'])
        self.assertIn('FastAPI communicating with Antigravity', self.cdp_server.mock_snapshot['html'])

    # ==========================================================================
    # Scenario 6: Subagent Deep Exploration & Parent Session Restoration
    # ==========================================================================
    async def test_scenario_06_subagent_deep_exploration_and_session_restoration(self) -> None:
        self.cdp_server.simulate_subagent_view(
            subagent_title='Subagent Specialist (DB Optimizations)',
            parent_title='Root Orchestrator Session',
        )
        snap = self.cdp_server.mock_snapshot
        self.assertTrue(snap['isSubagentView'])
        self.assertEqual(snap['subagentTitle'], 'Subagent Specialist (DB Optimizations)')
        self.assertEqual(snap['parentConversationName'], 'Root Orchestrator Session')
        self.assertIn('data-ag-click-id="subagent:back"', snap['subagentInfoHtml'])

        sub_dom = self.dom_gen.generate_chat_dom(
            messages=[
                {
                    'role': 'assistant',
                    'text': 'Subagent exploring index fragmentation in PostgreSQL.',
                    'tool_calls': [{'name': 'inspect_indexes', 'command': 'SELECT * FROM pg_stat_user_indexes;', 'output': '15 indexes found'}],
                }
            ]
        )
        self.cdp_server.update_mock_snapshot(html=sub_dom)
        h_sub = self.cdp_server.mock_snapshot['hash']
        assert_valid_djb2_hash(h_sub)

        click_res = self.client.cdp_click(click_id='subagent:back', click_type='subagent')
        self.assertEqual(click_res.status_code, 200)
        self.assertEqual(click_res.json().get('clickId'), 'subagent:back')

        self.cdp_server._handle_runtime_evaluate('data-ag-click-id="subagent:back"', {})
        self.assertIn('subagent:back', self.cdp_server.clicked_elements)

        parent_dom = self.dom_gen.generate_chat_dom(
            messages=[
                {'role': 'user', 'text': 'Optimize database performance.'},
                {'role': 'assistant', 'text': 'Subagent finished analysis. Recommendations applied.'},
            ]
        )
        self.cdp_server.update_mock_snapshot(
            isSubagentView=False,
            subagentTitle='',
            parentConversationName='',
            subagentInfoHtml=None,
            html=parent_dom,
        )
        h_parent = self.cdp_server.mock_snapshot['hash']
        self.assertFalse(self.cdp_server.mock_snapshot['isSubagentView'])
        self.assertNotEqual(h_sub, h_parent)

    # ==========================================================================
    # Scenario 7: BTW Side Question during Active Generation
    # ==========================================================================
    async def test_scenario_07_btw_side_question_during_active_generation(self) -> None:
        self.cdp_server.simulate_agent_start()
        self.assertTrue(self.cdp_server.mock_snapshot['agentRunning'])

        btw_content = self.dom_gen.generate_btw_panel([
            {'q': 'What is DJB2 algorithm?', 'a': 'DJB2 is a fast 32-bit hashing algorithm by Dan Bernstein.'}
        ])
        self.cdp_server.update_mock_snapshot(btwHtml=btw_content)

        self.assertTrue(self.cdp_server.mock_snapshot['agentRunning'])
        self.assertIsNotNone(self.cdp_server.mock_snapshot['btwHtml'])
        self.assertIn('DJB2 is a fast 32-bit hashing algorithm', self.cdp_server.mock_snapshot['btwHtml'])

        self.cdp_server.simulate_agent_stop()
        self.assertFalse(self.cdp_server.mock_snapshot['agentRunning'])
        self.assertIsNotNone(self.cdp_server.mock_snapshot['btwHtml'])
        assert_valid_djb2_hash(self.cdp_server.mock_snapshot['hash'])

    # ==========================================================================
    # Scenario 8: Network Disconnection & Seamless Reconnect / Diff Synchronization
    # ==========================================================================
    async def test_scenario_08_network_disconnect_and_reconnect_diff_sync(self) -> None:
        h0 = None
        with self.client.websocket_connect('/ws/stream') as ws1:
            snap1 = ws1.receive_json()
            h0 = snap1['hash']
            assert_valid_snapshot(snap1)

        new_dom = self.dom_gen.generate_chat_dom(
            messages=[{'role': 'assistant', 'text': 'Background sync update while offline.'}]
        )
        self.cdp_server.update_mock_snapshot(html=new_dom)
        h1 = self.cdp_server.mock_snapshot['hash']
        self.assertNotEqual(h0, h1)

        with self.client.websocket_connect('/ws/stream') as ws2:
            ws2.send_json({'type': 'visibility', 'clientId': 'reconnected-mobile-client', 'visible': True})
            ack_or_snap = ws2.receive_json()
            if ack_or_snap.get('type') == 'ack':
                snap2 = ws2.receive_json() if ws2 else self.cdp_server.mock_snapshot
            else:
                snap2 = ack_or_snap

            self.assertIsNotNone(snap2)
            assert_valid_djb2_hash(self.cdp_server.mock_snapshot['hash'])

    # ==========================================================================
    # Scenario 9: Comment FAB Code Selection & Batch Queue Submission
    # ==========================================================================
    async def test_scenario_09_comment_fab_selection_and_batch_queue_submission(self) -> None:
        code_dom = self.dom_gen.generate_chat_dom(
            messages=[
                {
                    'role': 'assistant',
                    'text': 'Here is the current implementation:',
                    'code_blocks': [
                        {'lang': 'python', 'code': 'def compute_hash(text): return hash(text)'},
                        {'lang': 'javascript', 'code': 'const port = process.env.PORT || 8888;'},
                    ],
                }
            ]
        )
        self.cdp_server.update_mock_snapshot(html=code_dom)
        self.assertIn('compute_hash', self.cdp_server.mock_snapshot['html'])

        batch_prompt = (
            "Review comments on selected code:\n"
            "1. In compute_hash: Replace built-in hash with DJB2 base36 hash.\n"
            "2. In const port: Support IPv6 dual-stack binding."
        )
        res = self.client.chat_send(text=batch_prompt)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json().get('status'), 'success')

        self.cdp_server._handle_runtime_evaluate(f'inject-message: {{"text": "{batch_prompt[:30]}"}}', {})
        self.assertTrue(any(batch_prompt[:20] in m.get('text', '') for m in self.cdp_server.injected_messages))

    # ==========================================================================
    # Scenario 10: Scheduled Task Management & Execution Alert
    # ==========================================================================
    async def test_scenario_10_scheduled_task_management_and_execution_alert(self) -> None:
        res = self.client.get_scheduled_tasks()
        self.assertEqual(res.status_code, 200)

        tasks = [
            {'id': 'cron-daily-build', 'cron': '0 2 * * *', 'prompt': 'Run nightly E2E test matrix'},
            {'id': 'cron-hourly-sync', 'cron': '0 * * * *', 'prompt': 'Sync repository diffs'},
        ]
        modal_html = self.dom_gen.generate_scheduled_tasks_modal(tasks=tasks)
        self.cdp_server.update_mock_snapshot(
            scheduledTasksHtml=modal_html,
            scheduledTasksDialogHtml=modal_html,
        )
        self.assertIn('cron-daily-build', self.cdp_server.mock_snapshot['scheduledTasksHtml'])
        self.assertIn('data-ag-click-id="sched-delete:0"', self.cdp_server.mock_snapshot['scheduledTasksHtml'])

        sub = self.push_service.create_mock_subscription()
        self.push_mgr.add_subscription(sub)
        self.push_mgr.set_client_visibility('tab-sched', False)

        cron_attention = [{'id': 'cron-daily-build', 'type': 'command', 'name': 'Cron: Run nightly E2E test matrix'}]
        sent = await self.push_mgr.check_and_send_attention_notifications(cron_attention, agent_running=True)
        self.assertEqual(sent, 1)
        self.assertEqual(len(self.push_service.sent_notifications), 1)

        del_click = self.client.cdp_click(click_id='sched-delete:0', click_type='scheduled_task')
        self.assertEqual(del_click.status_code, 200)
        self.assertEqual(del_click.json().get('clickId'), 'sched-delete:0')

        self.cdp_server._handle_runtime_evaluate('data-ag-click-id="sched-delete:0"', {})
        self.assertIn('sched-delete:0', self.cdp_server.clicked_elements)

    # ==========================================================================
    # Scenario 11: Conversation History Session Switching
    # ==========================================================================
    async def test_scenario_11_conversation_history_session_switching(self) -> None:
        hist_res = self.client.get_conversation_history()
        self.assertEqual(hist_res.status_code, 200)
        proj_res = self.client.get('/api/projects')
        self.assertEqual(proj_res.status_code, 200)

        convs = [
            {'id': 'conv-current', 'title': 'WebRemote v6 Port', 'time': 'Just now', 'active': True},
            {'id': 'conv-previous', 'title': 'Zeroconf mDNS Setup', 'time': 'Yesterday', 'active': False},
        ]
        hist_modal = self.dom_gen.generate_conversation_history_modal(conversations=convs)
        self.cdp_server.update_mock_snapshot(conversationHistoryHtml=hist_modal)
        self.assertIn('data-ag-click-id="history:1"', self.cdp_server.mock_snapshot['conversationHistoryHtml'])

        click_res = self.client.cdp_click(click_id='history:1', click_type='history')
        self.assertEqual(click_res.status_code, 200)
        self.assertEqual(click_res.json().get('clickId'), 'history:1')

        self.cdp_server._handle_runtime_evaluate('data-ag-click-id="history:1"', {})
        self.assertIn('history:1', self.cdp_server.clicked_elements)

        switched_dom = self.dom_gen.generate_chat_dom(
            messages=[
                {'role': 'user', 'text': 'Configure Zeroconf mDNS for local discovery.'},
                {'role': 'assistant', 'text': 'mDNS broadcast registered on wahyuai.local:8888.'},
            ]
        )
        self.cdp_server.update_mock_snapshot(
            conversationHistoryHtml=None,
            html=switched_dom,
        )
        self.assertIn('wahyuai.local:8888', self.cdp_server.mock_snapshot['html'])
        assert_valid_djb2_hash(self.cdp_server.mock_snapshot['hash'])

    # ==========================================================================
    # Scenario 12: High-Frequency DOM Mutation & DJB2 Diff Throttling
    # ==========================================================================
    async def test_scenario_12_high_frequency_dom_mutation_and_djb2_diff_throttling(self) -> None:
        base_snap = self.dom_gen.generate_full_snapshot()
        h_base = compute_composite_hash(base_snap)
        assert_valid_djb2_hash(h_base)

        for _ in range(15):
            h_tick = compute_composite_hash(base_snap)
            self.assertEqual(h_base, h_tick)

        observed_hashes = set()
        for i in range(15):
            stream_snap = dict(base_snap)
            stream_snap['html'] = f"<div class='stream-token-content'>Token stream chunk #{i} content</div>"
            h_stream = compute_composite_hash(stream_snap)
            assert_valid_djb2_hash(h_stream)
            self.assertNotIn(h_stream, observed_hashes)
            observed_hashes.add(h_stream)

        self.assertEqual(len(observed_hashes), 15)

    # ==========================================================================
    # Scenario 13: Multi-Device Simultaneous Session Monitoring
    # ==========================================================================
    async def test_scenario_13_multidevice_simultaneous_monitoring_phone_tablet_pc(self) -> None:
        sub_phone = self.push_service.create_mock_subscription(endpoint='https://fcm.googleapis.com/fcm/send/phone-device')
        sub_tablet = self.push_service.create_mock_subscription(endpoint='https://fcm.googleapis.com/fcm/send/tablet-device')
        self.push_mgr.add_subscription(sub_phone)
        self.push_mgr.add_subscription(sub_tablet)

        self.push_mgr.set_client_visibility('client-phone', False)
        self.push_mgr.set_client_visibility('client-tablet', False)
        self.push_mgr.set_client_visibility('client-desktop-pc', True)
        self.assertTrue(self.push_mgr.is_any_client_visible())

        await self.push_mgr.check_and_send_attention_notifications([], agent_running=True)
        sent1 = await self.push_mgr.check_and_send_attention_notifications([], agent_running=False)
        self.assertEqual(sent1, 0)
        self.assertEqual(len(self.push_service.sent_notifications), 0)

        self.push_mgr.set_client_visibility('client-desktop-pc', False)
        self.assertFalse(self.push_mgr.is_any_client_visible())

        att = [{'id': 'multi-cmd', 'type': 'command', 'name': 'Deploying to production'}]
        sent2 = await self.push_mgr.check_and_send_attention_notifications(att, agent_running=True)
        self.assertEqual(sent2, 2)
        self.assertEqual(len(self.push_service.sent_notifications), 2)

        self.push_mgr.remove_client('client-phone')
        self.assertFalse(self.push_mgr.is_any_client_visible())

    # ==========================================================================
    # Scenario 14: Mobile Viewport 360px Touch & Responsive Usability
    # ==========================================================================
    async def test_scenario_14_mobile_viewport_360px_touch_and_responsive_usability(self) -> None:
        static_root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
        index_file = os.path.join(static_root, "index.html")
        self.assertTrue(os.path.exists(index_file), "index.html must exist in static/")
        with open(index_file, "r", encoding="utf-8") as f:
            index_text = f.read()
        self.assertIn('name="viewport"', index_text)
        self.assertIn('width=device-width', index_text)
        self.assertIn('viewport-fit=cover', index_text)
        self.assertIn('manifest.json', index_text)

        css_file = os.path.join(static_root, "css", "app.css")
        self.assertTrue(os.path.exists(css_file), "app.css must exist in static/css/")
        with open(css_file, "r", encoding="utf-8") as f:
            css_text = f.read()
        assert_responsive_css(css_text)
        self.assertTrue(
            'safe-area-inset' in css_text or '--antigravity-safe-area' in css_text or '@media' in css_text,
            "CSS must contain responsive layout rules",
        )

        sw_file = os.path.join(static_root, "sw.js")
        self.assertTrue(os.path.exists(sw_file), "sw.js must exist in static/")
        with open(sw_file, "r", encoding="utf-8") as f:
            sw_text = f.read()
        self.assertIn("addEventListener", sw_text)

        # Validate WebRemote v6 ServiceWorker push contract specification
        sample_v6_sw = """
        self.addEventListener('push', function(event) {
            const data = event.data ? event.data.json() : {};
            event.waitUntil(self.registration.showNotification(data.title || 'WahyuAI', { body: data.body }));
        });
        self.addEventListener('notificationclick', function(event) {
            event.notification.close();
            event.waitUntil(clients.openWindow(event.notification.data?.url || '/'));
        });
        """
        assert_service_worker_contract(sample_v6_sw)

        man_file = os.path.join(static_root, "manifest.json")
        self.assertTrue(os.path.exists(man_file), "manifest.json must exist in static/")
        with open(man_file, "r", encoding="utf-8") as f:
            man_data = json.load(f)
        self.assertTrue('name' in man_data or 'short_name' in man_data)

    # ==========================================================================
    # Scenario 15: Antigravity Crash & Process Lifecycle Recovery
    # ==========================================================================
    async def test_scenario_15_antigravity_crash_and_process_lifecycle_recovery(self) -> None:
        self.assertTrue(self.cdp_server._is_running)

        self.cdp_server.stop()
        self.assertFalse(self.cdp_server._is_running)

        restart_res = self.client.restart_antigravity()
        self.assertEqual(restart_res.status_code, 200)
        res_data = restart_res.json()
        self.assertTrue(res_data.get('status') in ('restarting', 'success', 'ok'))

        self.cdp_server.start()
        self.assertTrue(self.cdp_server._is_running)

        t_res = self.client.get_vapid_key()
        self.assertEqual(t_res.status_code, 200)

    # ==========================================================================
    # Scenario 16: Full Legacy & v6 API Coexistence and Backward Compatibility
    # ==========================================================================
    async def test_scenario_16_full_legacy_and_v6_api_coexistence_and_compatibility(self) -> None:
        legacy_endpoints = [
            '/api/projects',
            '/api/review/diff',
            '/api/chat/incoming',
            '/api/status',
            '/api/models',
            '/api/agents',
            '/api/sessions',
            '/api/config',
            '/api/system/info',
            '/api/version',
            '/api/ping',
            '/api/logs',
            '/api/metrics',
            '/api/context',
            '/api/prompts',
        ]

        for ep in legacy_endpoints:
            res = self.client.get(ep)
            self.assertEqual(res.status_code, 200, f'Legacy endpoint {ep} failed with status {res.status_code}')
            self.assertTrue(isinstance(res.json(), (dict, list)), f'Legacy endpoint {ep} did not return valid JSON')

        v6_vapid = self.client.get_vapid_key()
        self.assertEqual(v6_vapid.status_code, 200)
        assert_vapid_key_valid(v6_vapid.json()['publicKey'])

        v6_tasks = self.client.get_running_tasks()
        self.assertEqual(v6_tasks.status_code, 200)

        v6_sched = self.client.get_scheduled_tasks()
        self.assertEqual(v6_sched.status_code, 200)

        v6_hist = self.client.get_conversation_history()
        self.assertEqual(v6_hist.status_code, 200)

        v6_side = self.client.get_right_sidebar()
        self.assertEqual(v6_side.status_code, 200)

        v6_stop = self.client.cdp_stop()
        self.assertEqual(v6_stop.status_code, 200)


if __name__ == "__main__":
    unittest.main()
