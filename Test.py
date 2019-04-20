'''
run this with
python -m unittest -v Test
'''
import os
import unittest

import CherryPyApp

class TestInstantiation(unittest.TestCase):
    def setUp(self):
        CherryPyApp.CHERRYPY_CONFIG = os.path.join(
            os.path.dirname(os.path.abspath (__file__)),
            'test.conf'
        )

    def test_main(self):
        CherryPyApp.main()
