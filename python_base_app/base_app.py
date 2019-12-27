# -*- coding: utf-8 -*-

#    Copyright (C) 2019  Marcus Rickert
#
#    See https://github.com/marcus67/python_base_app
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License along
#    with this program; if not, write to the Free Software Foundation, Inc.,
#    51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

import argparse
import datetime
import heapq
import os
import signal
import time

from python_base_app import configuration
from python_base_app import daemon
from python_base_app import exceptions
from python_base_app import log_handling
from python_base_app import tools

DEFAULT_DEBUG_MODE = False

DEFAULT_LOG_LEVEL = 'INFO'

DEFAULT_SPOOL_BASE_DIR = "/var/spool"

TIME_SLACK = 0.1  # seconds
ETERNITY = 24 * 3600  # seconds
DEFAULT_TASK_INTERVAL = 10  # seconds
DEFAULT_MAXIMUM_TIMER_SLACK = 5  # second
DEFAULT_MINIMUM_DOWNTIME_DURATION = 20  # seconds


class BaseAppConfigModel(configuration.ConfigModel):

    def __init__(self, p_section_name="BaseApp"):
        super().__init__(p_section_name=p_section_name)

        self.debug_mode = DEFAULT_DEBUG_MODE
        self.log_level = configuration.NONE_STRING
        self.spool_dir = configuration.NONE_STRING
        self.minimum_downtime_duration = DEFAULT_MINIMUM_DOWNTIME_DURATION
        self.maximum_timer_slack = DEFAULT_MAXIMUM_TIMER_SLACK


class RecurringTask(object):

    def __init__(self, p_name, p_handler_method, p_interval=DEFAULT_TASK_INTERVAL, p_fixed_schedule=False):

        self.name = p_name
        self.handler_method = p_handler_method
        self.interval = p_interval
        self.next_execution = None
        self.fixed_schedule = p_fixed_schedule

    def __lt__(self, p_other):
        return self.next_execution < p_other

    def __gt__(self, p_other):
        return self.next_execution > p_other

    def __sub__(self, p_other):
        if isinstance(p_other, RecurringTask):
            return self.next_execution - p_other.next_execution

        else:
            return self.next_execution - p_other

    def __rsub__(self, p_other):
        if isinstance(p_other, RecurringTask):
            return p_other.next_execution - self.next_execution

        else:
            return p_other - self.next_execution

    def get_heap_entry(self):

        # return (self, self)
        return self

    def compute_next_execution_time(self):

        if self.next_execution is None:
            self.next_execution = datetime.datetime.utcnow()

        elif self.fixed_schedule:
            self.next_execution = self.next_execution + datetime.timedelta(seconds=self.interval)

        else:
            self.next_execution = datetime.datetime.utcnow() + datetime.timedelta(seconds=self.interval)

    def adapt_to_delay(self, p_delay):

        if self.next_execution is not None:
            self.next_execution = self.next_execution + datetime.timedelta(seconds=p_delay)


class BaseApp(daemon.Daemon):

    def __init__(self, p_app_name, p_pid_file, p_arguments, p_dir_name):

        super().__init__(pidfile=p_pid_file)

        self._app_name = p_app_name
        self._dir_name = p_dir_name
        self._arguments = p_arguments
        self._logger = log_handling.get_logger(self.__class__.__name__)
        self._config = None
        self._recurring_tasks = []
        self._downtime = 0

        # Only temporary until the app has been initialized completely!
        self._app_config = BaseAppConfigModel()

    @property
    def down_time(self):
        return self._downtime

    def reset_down_time(self):
        self._downtime = 0

    def add_recurring_task(self, p_recurring_task):

        p_recurring_task.compute_next_execution_time()
        heapq.heappush(self._recurring_tasks, p_recurring_task.get_heap_entry())

    def configuration_factory(self):
        return configuration.Configuration()

    def load_configuration(self, p_configuration):

        self._app_config = p_configuration[self._app_name]

        for afile in self._arguments.configurations:
            p_configuration.read_config_file(afile)

        p_configuration.read_environment_parameters(p_environment_dict=os.environ)
        p_configuration.read_command_line_parameters(p_parameters=self._arguments.cmd_line_options)

        if self._app_config.log_level is not None:
            log_handling.set_level(self._app_config.log_level)

        if self._app_config.spool_dir is None:
            self._app_config.spool_dir = os.path.join(DEFAULT_SPOOL_BASE_DIR, self._dir_name)

        return p_configuration

    def check_configuration(self):

        logger = log_handling.get_logger()

        self.load_configuration(self.configuration_factory())

        fmt = "%d configuration files are Ok!" % len(self._arguments.configurations)
        logger.info(fmt)

    def handle_sighup(self, p_signum, p_stackframe):

        fmt = "Received signal %d" % p_signum
        _ = p_stackframe
        self._logger.info(fmt)

        raise exceptions.SignalHangUp()

    def install_handlers(self):

        signal.signal(signal.SIGTERM, self.handle_sighup)
        signal.signal(signal.SIGHUP, self.handle_sighup)
        signal.signal(signal.SIGINT, self.handle_sighup)  # CTRL-C
        signal.pthread_sigmask(signal.SIG_UNBLOCK, [signal.SIGTERM, signal.SIGHUP, signal.SIGINT])

    def prepare_services(self, p_full_startup=True):

        pass

    def start_services(self):

        pass

    def adapt_active_recurring_tasks(self, p_delay):

        # for (_next_execution, task) in self._recurring_tasks:
        #    task.adapt_to_delay(p_delay=p_delay)
        for task in self._recurring_tasks:
            task.adapt_to_delay(p_delay=p_delay)

        heapq.heapify(self._recurring_tasks)

    def event_queue(self):

        done = False
        last_run = None

        while not done:

            try:
                now = datetime.datetime.utcnow()

                if len(self._recurring_tasks) > 0:
                    task = self._recurring_tasks[0]
                    wait_in_seconds = (task - now).total_seconds()

                else:
                    task = None
                    wait_in_seconds = ETERNITY

                if wait_in_seconds > 0:
                    try:

                        fmt = "Sleeping for {seconds} seconds (or until next signal)"
                        self._logger.debug(fmt.format(seconds=wait_in_seconds))

                        signal.pthread_sigmask(signal.SIG_UNBLOCK, [signal.SIGTERM, signal.SIGHUP])
                        time.sleep(wait_in_seconds)

                    except exceptions.SignalHangUp as e:
                        raise e

                    except Exception as e:

                        if self._app_config.debug_mode:
                            fmt = "Propagating exception due to debug_mode=True"
                            self._logger.warn(fmt)
                            raise e

                        fmt = "Exception %s while waiting for signal" % str(e)
                        self._logger.error(fmt)

                    fmt = "Woken by signal"
                    self._logger.debug(fmt)

                    if task is not None:
                        now = datetime.datetime.utcnow()
                        overslept_in_seconds = (now - task).total_seconds()

                        if overslept_in_seconds > self._app_config.maximum_timer_slack:
                            self.track_downtime(p_downtime=overslept_in_seconds)

                if len(self._recurring_tasks) > 0:

                    task_executed = True

                    while task_executed:
                        task = self._recurring_tasks[0]

                        now = datetime.datetime.utcnow()

                        if now > task:

                            delay = (now - task).total_seconds()

                            task = heapq.heappop(self._recurring_tasks)
                            self.add_recurring_task(p_recurring_task=task)

                            fmt = "Executing task {task} {secs:.3f} [s] behind schedule... *** START ***"
                            self._logger.debug(fmt.format(task=task.name, secs=delay))
                            task.handler_method()
                            fmt = "Executing task {task} {secs:.3f} [s] behind schedule... *** END ***"
                            self._logger.debug(fmt.format(task=task.name, secs=delay))

                            if delay > self._app_config.minimum_downtime_duration:
                                self.track_downtime(p_downtime=delay)

                        else:
                            task_executed = False

                    if self._downtime > 0:
                        self.handle_downtime(p_downtime=int(self._downtime))
                        self.reset_down_time()


            except exceptions.SignalHangUp:
                fmt = "Event queue interrupted by signal"
                self._logger.info(fmt)

                done = True

            except Exception as e:
                if self._app_config.debug_mode:
                    fmt = "Propagating exception due to debug_mode=True"
                    self._logger.warn(fmt)
                    raise e

                fmt = "Exception %s in event queue" % str(e)
                self._logger.error(fmt)
                tools.log_stack_trace(p_logger=self._logger)

            if self._arguments.single_run:
                done = True

    def track_downtime(self, p_downtime):

        fmt = "Detected delay of {seconds} seconds -> adding to downtime timer"
        self._logger.info(fmt.format(seconds=p_downtime))

        self._downtime += p_downtime
        self.adapt_active_recurring_tasks(p_delay=p_downtime)

    def handle_downtime(self, p_downtime):

        fmt = "Accumulated downtime of {seconds} seconds ignored."
        self._logger.warning(fmt.format(seconds=p_downtime))

    def stop_services(self):

        pass

    def basic_init(self, p_full_startup=True):

        try:
            self._config = self.load_configuration(self.configuration_factory())
            self.prepare_services(p_full_startup=p_full_startup)

        except Exception as e:
            fmt = "Error %s in basic_init()" % str(e)
            self._logger.error(fmt)

            # if self._app_config.debug_mode:
            #     fmt = "Propagating exception due to debug_mode=True"
            #     self._logger.warn(fmt)
            #     raise e

            raise e

    def run(self):

        global process_result

        previous_exception = None

        fmt = "Starting app '%s'" % self._app_name
        self._logger.info(fmt)

        try:
            self.basic_init()
            self.install_handlers()
            self.start_services()
            self.event_queue()

        except Exception as e:
            fmt = "Exception '%s' in run()" % str(e)
            self._logger.error(fmt)

            previous_exception = e

        finally:
            try:
                self.stop_services()

            except Exception as e:
                fmt = "Exception '%s' while stopping services" % str(e)
                self._logger.error(fmt)


        if previous_exception is not None:
            raise previous_exception

        fmt = "Terminating app '%s'" % self._app_name
        self._logger.info(fmt)

    def run_special_commands(self, p_arguments):

        _arguments = p_arguments
        return False


def get_argument_parser(p_app_name):
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', nargs='*', dest='configurations', default=[],
                        help='file names of the configuration files')
    parser.add_argument('--option', nargs='*', dest='cmd_line_options', default=[],
                        help='Additional configuration settings formatted as SECTION.OPTION=VALUE (overriding settings in configuration files)')
    parser.add_argument('--pidfile', dest='pid_file',
                        help='name of the PID file', default='/var/run/%s/%s.pid' % (p_app_name, p_app_name))
    parser.add_argument('--logdir', dest='log_dir', default=None,
                        help='base path for logging files')
    parser.add_argument('--loglevel', dest='log_level', default=DEFAULT_LOG_LEVEL,
                        help='logging level', choices=['WARN', 'INFO', 'DEBUG'])
    parser.add_argument('--application-owner', dest='app_owner', default=None,
                        help='name of user running application')
    parser.add_argument('--daemonize', dest='daemonize', action='store_const', const=True, default=False,
                        help='start app as daemon process')
    parser.add_argument('--check-installation', dest='check_installation', action='store_const', const=True,
                        default=False,
                        help='Tests the existence of required directories and files as well as their access rights')
    parser.add_argument('--check-configuration', dest='check_configuration', action='store_const', const=True,
                        default=False,
                        help='Validates the configurations files')
    parser.add_argument('--kill', dest='kill', action='store_const', const=True, default=False,
                        help='Terminates the running daemon process')
    parser.add_argument('--single-run', dest='single_run', action='store_const', const=True, default=False,
                        help='Executes a single run of the application and exists')

    return parser


def check_installation(p_arguments):
    pid_file_directory = os.path.dirname(p_arguments.pid_file)

    if p_arguments.log_dir is not None:
        tools.test_mode(p_arguments.log_dir, p_app_owner=p_arguments.app_owner, p_is_directory=True, p_executable=True,
                        p_writable=True, p_other_access=False)

    if p_arguments.daemonize:
        tools.test_mode(pid_file_directory, p_app_owner=p_arguments.app_owner, p_is_directory=True, p_executable=True,
                        p_writable=True)

    for config_file in p_arguments.configurations:
        tools.test_mode(config_file, p_app_owner=p_arguments.app_owner, p_other_access=False)

    logger = log_handling.get_logger()
    logger.info("Installation OK!")


def main(p_app_name, p_app_class, p_argument_parser):
    process_result = 0
    logger = log_handling.get_logger()
    arguments = p_argument_parser.parse_args()

    try:
        if arguments.daemonize and arguments.log_dir is None:
            raise configuration.ConfigurationException("Option --daemonize requires option --logdir!")

        default_log_file = '%s.log' % p_app_name

        log_handling.start_logging(p_level=arguments.log_level, p_log_dir=arguments.log_dir,
                                   p_log_file=default_log_file)
        logger = log_handling.get_logger()

        if arguments.check_installation:
            logger.info("Checking installation...")
            check_installation(p_arguments=arguments)

        else:

            app = p_app_class(p_pid_file=arguments.pid_file, p_arguments=arguments, p_app_name=p_app_name)

            if len(arguments.configurations) == 0:
                logger.warning("No configuration files specified")

            if arguments.kill:
                logger.info("Killing active daemon process...")
                app.stop()

            elif arguments.check_configuration:
                logger.info("Checking configuration files...")
                app.check_configuration()

            elif arguments.daemonize:
                logger.info("Starting daemon process...")
                app.start()

            elif not app.run_special_commands(p_arguments=arguments):
                logger.info("Starting as a normal foreground process...")
                app.run()

    except configuration.ConfigurationException as e:
        logger.error(str(e))
        process_result = 3

    except exceptions.InstallationException as e:
        logger.error(str(e))
        process_result = 2


    except Exception as e:

        tools.handle_fatal_exception(p_exception=e, p_logger=logger)
        tools.log_stack_trace(p_logger=logger)
        process_result = 1

    fmt = 'Terminated with exit code %d' % process_result
    logger.info(fmt)

    return process_result
