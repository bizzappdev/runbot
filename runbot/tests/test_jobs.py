# -*- coding: utf-8 -*-
import datetime
from time import localtime
from unittest.mock import patch
from odoo.tools.misc import DEFAULT_SERVER_DATETIME_FORMAT
from odoo.tests import common


class Test_Jobs(common.TransactionCase):

    def setUp(self):
        super(Test_Jobs, self).setUp()
        self.Repo = self.env['runbot.repo']
        self.repo = self.Repo.create({'name': 'bla@example.com:foo/bar', 'token': 'xxx'})
        self.Branch = self.env['runbot.branch']
        self.branch_master = self.Branch.create({
            'repo_id': self.repo.id,
            'name': 'refs/heads/master',
        })
        self.Build = self.env['runbot.build']

    @patch('odoo.addons.runbot.models.repo.runbot_repo._github')
    @patch('odoo.addons.runbot.models.build.runbot_build._cmd')
    @patch('odoo.addons.runbot.models.build.os.path.getmtime')
    @patch('odoo.addons.runbot.models.build.time.localtime')
    @patch('odoo.addons.runbot.models.build.runbot_build._spawn')
    @patch('odoo.addons.runbot.models.build.grep')
    def test_job_30_failed(self, mock_grep, mock_spawn, mock_localtime, mock_getmtime, mock_cmd, mock_github):
        a_time = datetime.datetime.now().strftime(DEFAULT_SERVER_DATETIME_FORMAT)
        mock_grep.return_value = False
        mock_spawn.return_value = 2
        now = localtime()
        mock_localtime.return_value = now
        mock_getmtime.return_value = None
        mock_cmd.return_value = ([], [])
        build = self.Build.create({
            'branch_id': self.branch_master.id,
            'name': 'd0d0caca0000ffffffffffffffffffffffffffff',
            'port' : '1234',
            'state': 'done',
            'job_start': a_time,
            'job_end': a_time
        })
        self.assertFalse(build.result)
        self.Build._job_30_run(build, '/tmp/x.lock', '/tmp/x.log')
        self.assertEqual(build.result, 'ko')
        print(mock_github.call_count)
