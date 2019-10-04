from AIConfig import AIConfig
from telethon import events
from wrapt import decorator

class GroupHandler(object):
    ''' Decorator for wrapping async telethon NewMessage handlers as group message handlers
        Making group configuration avaliable inside the handlers

        Example Usage:
        @bot.on(events.NewMessage(...))
        @GroupHandler(ai_config)
        async def handler(event, gid, config):
            # gid would be the group id associated with the incoming message
            # config would be the group config associated with the group
    '''
    def __init__(self, ai_config: AIConfig):
        '''Initializes the decorator with AIConfig object `ai_config`
        
            ai_config: AIConfig, the configuration object to pull group config from
        '''
        self._config = ai_config

    @decorator
    async def __call__(self, f, instance, args, kwargs):
        '''Decorates function `f`'''
        # Getting the first argument event to the wrapped call
        event = kwargs.get("event")
        if event is None:
            event = args[0]
        assert isinstance(event, events.NewMessage), "Incorrect event type"

        # Group handler only handles group messages
        if not event.is_group:
            return None
        gid = event.chat_id
        g_config = self._config.group(gid)
        # Group handler only handles messages from configured groups
        if g_config is None:
            return None
        
        # Proxy call to inner method
        if instance:
            return await instance.f(event, gid, g_config)
        # Proxy call to inner function
        return await f(event, gid, g_config)