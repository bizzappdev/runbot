# -*- coding: utf-8 -*-
"""Containerize builds

The docker image used for the build is always tagged like this:
    odoo:runbot_tests
This file contains helpers to containerize builds with Docker.
When testing this file:
    the first parameter should be a directory containing Odoo.
    The second parameter should be the version number.
    The third parameter is the exposed port
"""

import datetime
import logging
import os
import shutil
import subprocess
import sys
import time


_logger = logging.getLogger(__name__)
DOCKERUSER = """
RUN groupadd -g %(group_id)s odoo \\
&& useradd -u %(user_id)s -g odoo -G audio,video odoo \\
&& mkdir /home/odoo \\
&& chown -R odoo:odoo /home/odoo \\
&& echo "odoo ALL= NOPASSWD: /usr/bin/pip" > /etc/sudoers.d/pip \\
&& echo "odoo ALL= NOPASSWD: /usr/bin/pip3" >> /etc/sudoers.d/pip
USER odoo
ENV COVERAGE_FILE /data/build/.coverage
""" % {'group_id': os.getgid(), 'user_id': os.getuid()}

DOCKERSCRIPT = """#!/bin/sh
set -e
cd docker
docker build --tag odoo:runbot_tests .
cd ..
"""

def docker_run(build_dir, log_path, odoo_cmd, container_name, exposed_ports=None, cpu_limit=None, preexec_fn=None):
    """Run tests in a docker container
    :param build_dir: the build directory that contains the Odoo sources to build.
                      This directory is shared as a volume with the container
    :param log_path: path to the logfile that will contain odoo stdout and stderr
    :param odoo_cmd: command that starts odoo
    :param container_name: used to give a name to the container for later reference
    :param exposed_ports: if not None, starting at 8069, ports will be exposed as exposed_ports numbers
    """
    # build cmd
    cmd_chain = []
    cmd_chain.append('cd /data/build')
    cmd_chain.append('head -1 odoo-bin | grep -q python3 && sudo pip3 install -r requirements.txt || sudo pip install -r requirements.txt')
    cmd_chain.append(' '.join(odoo_cmd))
    run_cmd = ' && '.join(cmd_chain)
    _logger.debug('Docker run command: %s', run_cmd)
    logs = open(log_path, 'w')

    # Prepare docker image
    docker_dir = os.path.join(build_dir, 'docker')
    os.makedirs(docker_dir, exist_ok=True)
    shutil.copy(os.path.join(os.path.dirname(__file__), 'data', 'Dockerfile'), docker_dir)
    # synchronise the current user with the odoo user inside the Dockerfile
    with open(os.path.join(docker_dir, 'Dockerfile'), 'a') as df:
        df.write(DOCKERUSER)

    # create start script
    docker_command = [
        'docker', 'run', '--rm',
        '--name', container_name,
        '--volume=/var/run/postgresql:/var/run/postgresql',
        '--volume=%s:/data/build' % build_dir,
    ]
    if exposed_ports:
        for dp,hp in enumerate(exposed_ports, start=8069):
            docker_command.extend(['-p', '127.0.0.1:%s:%s' % (hp, dp)])
    if cpu_limit:
        docker_command.extend(['--ulimit', 'cpu=%s' % cpu_limit])
    docker_command.extend(['odoo:runbot_tests', '/bin/bash', '-c', "'%s'" % run_cmd])
    script_path = os.path.join(build_dir, 'docker_start.sh')
    with open(script_path, 'w') as start_file:
        start_file.write(DOCKERSCRIPT)
        start_file.write(' '.join(docker_command))
    os.chmod(script_path, 0o0744)
    docker_run = subprocess.Popen(script_path, stdout=logs, stderr=logs, preexec_fn=preexec_fn, close_fds=False, cwd=build_dir)
    _logger.info('Started Docker container %s', container_name)
    return docker_run.pid

def docker_stop(container_name):
    """Stops the container named container_name"""
    _logger.info('Stopping container %s', container_name)
    dstop = subprocess.run(['docker', 'stop', container_name], stderr=subprocess.PIPE, check=True)
    
def docker_is_running(container_name):
    """Return True if container is still running"""
    dinspect = subprocess.run(['docker', 'container', 'inspect', container_name], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    return True if dinspect.returncode == 0 else False

if __name__ == '__main__':
    _logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s')
    handler.setFormatter(formatter)
    _logger.addHandler(handler)
    _logger.info('Start container tests')

    if len(sys.argv) < 5:
        _logger.error('Missing arguments: "%s build_dir odoo_version odoo_port db_name"', sys.argv[0])
        sys.exit(1)
    build_dir = sys.argv[1]
    odoo_version = sys.argv[2]
    odoo_port = sys.argv[3]
    db_name = sys.argv[4]
    os.makedirs(os.path.join(build_dir, 'logs'), exist_ok=True)
    os.makedirs(os.path.join(build_dir, 'datadir'), exist_ok=True)

    # Test stopping a non running container
    _logger.info('Test killing an non existing container')
    try:
        docker_stop('xy' * 5)
    except subprocess.CalledProcessError:
        _logger.warning('Expected Docker stop failure')

    # Test testing
    odoo_cmd = ['/data/build/odoo-bin', '-d %s' % db_name, '--addons-path=/data/build/addons', '--data-dir', '/data/build/datadir', '-r %s' % os.getlogin(), '-i', 'web',  '--test-enable', '--stop-after-init', '--max-cron-threads=0']
    logfile = os.path.join(build_dir, 'logs', 'logs-partial.txt')
    container_name = 'odoo-container-test-%s' % datetime.datetime.now().microsecond
    docker_run(build_dir, logfile, odoo_cmd, container_name)

    # Test stopping the container
    _logger.info('Waiting 30 sec before killing the build')
    time.sleep(30)
    docker_stop(container_name)
    time.sleep(3)

    # Test full testing
    logfile = os.path.join(build_dir, 'logs', 'logs-full-test.txt')
    container_name = 'odoo-container-test-%s' % datetime.datetime.now().microsecond
    docker_run(build_dir, logfile, odoo_cmd, container_name)
    time.sleep(1) # give time for the container to start

    while docker_is_running(container_name):
        time.sleep(10)
        _logger.info("Waiting for %s to stop", container_name)

    # Test running
    logfile = os.path.join(build_dir, 'logs', 'logs-running.txt')
    odoo_cmd = ['/data/build/odoo-bin', '-d %s' % db_name,
        '--db-filter', '%s.*$' % db_name, '--addons-path=/data/build/addons',
        '-r %s' % os.getlogin(), '-i', 'web',  '--max-cron-threads=1',
        '--data-dir', '/data/build/datadir', '--workers', '2',
        '--longpolling-port', '8070']
    container_name = 'odoo-container-test-%s' % datetime.datetime.now().microsecond
    docker_run(build_dir, logfile, odoo_cmd, container_name, exposed_ports=[odoo_port, int(odoo_port) + 1], cpu_limit=300)
