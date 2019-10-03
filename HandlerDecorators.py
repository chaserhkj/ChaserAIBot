from AIConifg import AIConfig
from telethon import events

class GroupHandler(object):
    '''Decorator for wrapping telethon NewMessage handlers as group message handlers
        Making group configuration avaliable inside the handlers

        Example Usage:
        @bot.on(events.NewMessage
        @GroupHandler(ai_config)
        def handler(event, gid, config):
            # gid would be the group id associated with the incoming message
            # config would be the group config associated with the group
    '''
    def __init__(self, ai_config: AIConfig):
        '''Initializes the decorator with AIConfig object `ai_config`
        
            ai_config: AIConfig, the configuration object to pull group config from
        '''
        self._config = ai_config
    
    def __call__(self, f):
        '''Decorates function `f`'''
        async def func(event: events.NewMessage):
            if not event.is_group:
                return None
            gid = event.chat_id
            g_config = self._config.group(gid)
            if g_config is None:
                return None
            return await f(event, gid, g_config)
        return func