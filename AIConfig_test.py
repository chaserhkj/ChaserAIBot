from pyfakefs.fake_filesystem_unittest import TestCase
from AIConfig import AIConfig

class AIConfigTest(TestCase):
    def setUp(self):
        self.setUpPyfakefs()
        self.fs.create_file("config.yaml", contents='''
apikey: 'TGKey'
tenorkey: 'TenorKey'
owner: 1000
groups:
    -1000:
        group_key: 'group_field'
        ''')
        self.ai_config = AIConfig("config.yaml")
    
    def test_read_apikey(self):
        self.assertEqual(self.ai_config.apikey(), 'TGKey')
    
    def test_read_tenorkey(self):
        self.assertEqual(self.ai_config.tenorkey(), 'TenorKey')
    
    def test_read_owner(self):
        self.assertEqual(self.ai_config.owner(), 1000)
    
    def test_read_group_config(self):
        self.assertIsNotNone(self.ai_config.group(-1000))
        self.assertEqual(self.ai_config.group(-1000).get('group_key'), 'group_field')

if __name__ == '__main__':
    __import__("unittest").main()