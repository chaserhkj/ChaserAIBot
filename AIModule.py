from telethon import TelegramClient, events
from AIConfig import AIConfig
from wrapt import decorator

class AIModule(object):
    '''Abstract class representing a module for AI Bot
        Subclass this class to create AI Bot modules
    '''
    def __init__(self, name: str, bot: TelegramClient, config: AIConfig):
        '''Constructor for AIModule
        
        name: str, name for the module as printed in the help text
        bot: telethon.TelegramClient, client object for the bot
        config: AIConfig.AIConfig, configuration for the bot
        '''
        self._name = name
        self._bot = bot
        self._config = config

    def on(self):
        '''Abstract method for registering all handlers associated with the module,
        getting ready for main event loop to be run.
        
        Needs to be implemented on subclasses.
        '''
        raise NotImplementedError

    def help(self):
        '''Returns a str to be used in help text for this module
        For this abstract class, only the name of the module is returned in format:
        
        Help for module <name>:
        '''
        return f"Help for module {self._name}"

class AICmdModule(object):
    '''Class representing a command module for AI Bot
        Provides a self.command decorator to decorate the command handlers
        
        For example, to implement a /start command:
        
        class CoreModule(AIModule):
            @self.command
            def start(self, event):
                # Do stuff here
    '''
    class _command(object):
        '''Class decorator to decorate a AICmdModule method, registering it as a command handler,
        for later registeration with the TelegramClient'''
        def __init__(self, module: AICmdModule):
            '''Constructor for the decorator
            
            module: AICmdModule, the module to associate this decorator with
            '''
            self._module = module
        
        @decorator
        def __call__(self, f, instance, args, kwargs):
            '''Register decorated function f with associated AICmdModule by AICmdModule.add_cmd'''
            self._module.add_cmd(f)
            return f(*args, **kwargs)
            
    def __init__(self, *args, **kwargs):
        '''Constructor for AICmdModule
        Calls the base class constructor'''
        super().__init__(*args, **kwargs)
        self.command = AICmdModule._command(self)
        self._cmd_funcs = set()
    
    def add_cmd(self, func):
        '''Register `func` with the module, adding it to list of command functions.
        
        func: function, the command handler function to be added
        '''
        self._cmd_funcs.add(func)
    
    def on(self):
        '''Register all added functions with TelegramClient'''
        for func in self._cmd_funcs:
            self._bot.on(events.NewMessage(pattern=rf"^/{func.__name__}$"))(func)

