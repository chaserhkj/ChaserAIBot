import yaml

class AIConfig(object):
    '''Config class for AI Bot'''
    def __init__(self, filename: str):
        '''Initializes the config class

            filename: str, path to the yaml config file
        '''
        with open(filename, "r") as f:
            self._config = yaml.load(f)
        self._apikey = self._config['apikey']
        self._tenorkey = self._config['tenorkey']
        self._owner = self._config['owner']
    
    def apikey(self):
        '''Returns the telegram bot apikey configured'''
        return self._apikey
    
    def tenorkey(self):
        '''Returns the Tenor apikey configured'''
        return self._tenorkey
    
    def owner(self):
        '''Returns the telegram owner ID configured'''
        return self._owner
    
    def group(self, group_id: int):
        '''Returns the configuration dictionary associated with `group_id`
            Returns None if the configuration does not exist for the group
        
            group_id: int, the telegram group id to query configuration for
        '''
        return self._config['groups'].get(group_id, None)

