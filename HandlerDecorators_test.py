from unittest import TestCase, main
from unittest.mock import MagicMock
from telethon import events
from AIConfig import AIConfig
import HandlerDecorators
import asyncio

class GroupHandlerTest(TestCase):
    def setUp(self):
        self.event = MagicMock(spec=events.NewMessage)
        self.config = MagicMock(spec=AIConfig)
        self.config.group = MagicMock()
    
    def test_not_group_message_returns_none(self):
        self.event.is_group = False

        @HandlerDecorators.GroupHandler(self.config)
        async def _handler(event, gid, g_config):
            pass

        result = asyncio.run(_handler(self.event))

        self.assertIsNone(result)
        self.config.group.assert_not_called()
    
    def test_no_group_config_returns_none(self):
        self.event.is_group = True
        self.event.chat_id = -1000
        self.config.group.return_value = None

        @HandlerDecorators.GroupHandler(self.config)
        async def _handler(event, gid, g_config):
            pass

        result = asyncio.run(_handler(self.event))

        self.assertIsNone(result)
        self.config.group.assert_called_with(-1000)

    def test_group_message_calls_inner_handler(self):
        self.event.is_group = True
        self.event.chat_id = -1000

        self.g_config_object = object()
        self.result_object = object()

        self.group_call_dict = {-1000: self.g_config_object}
        self.config.group.side_effect = lambda key: self.group_call_dict.get(key, None)

        @HandlerDecorators.GroupHandler(self.config)
        async def _handler(event, gid, g_config):
            self.assertEqual(gid, -1000)
            self.assertIs(g_config, self.g_config_object)
            return self.result_object

        result = asyncio.run(_handler(self.event))

        self.assertIs(result, self.result_object)
        self.config.group.assert_called_with(-1000)
    
    def test_group_message_calls_inner_class_method_handler(self):
        self.event.is_group = True
        self.event.chat_id = -1000

        self.g_config_object = object()
        self.result_object = object()

        self.group_call_dict = {-1000: self.g_config_object}
        self.config.group.side_effect = lambda key: self.group_call_dict.get(key, None)

        class _handler_class(object):
            def __init__(self, testcase):
                self.testcase = testcase

            @HandlerDecorators.GroupHandler(self.config)
            async def handler(self, event, gid, g_config):
                self.testcase.assertEqual(gid, -1000)
                self.testcase.assertIs(g_config, self.testcase.g_config_object)
                return self.testcase.result_object

        self.handler_class_instance = _handler_class(self)
        result = asyncio.run(self.handler_class_instance.handler(self.event))

        self.assertIs(result, self.result_object)
        self.config.group.assert_called_with(-1000)


if __name__ == "__main__":
    main()