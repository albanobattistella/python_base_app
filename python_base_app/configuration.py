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

import abc
import configparser
import re

from python_base_app import log_handling

REGEX_CMDLINE_PARAMETER = re.compile("([-a-zA-Z_0-9]+)\.([a-zA-Z_0-9]+)=(.*)")

NONE_BOOLEAN = type(True)
NONE_INTEGER = type(1)
NONE_STRING = type("X")

VALID_BOOLEAN_TRUE_VALUES = ['1', 'TRUE', 'T', 'YES', 'WAHR', 'JA', 'J']
VALID_BOOLEAN_FALSE_VALUES = ['0', 'FALSE', 'F', 'NO', 'FALSCH', 'NEIN', 'N']


class ConfigurationException(Exception):

    def __init__(self, p_text):
        super(ConfigurationException, self).__init__(p_text)


class ConfigurationSectionHandler(object, metaclass=abc.ABCMeta):

    def __init__(self, p_section_prefix):
        self._section_prefix = p_section_prefix
        self._configuration = None

    @property
    def section_prefix(self):
        return self._section_prefix

    @abc.abstractmethod
    def handle_section(self, p_section_name):
        pass

    def set_configuration(self, p_configuration):
        self._configuration = p_configuration

    def scan(self, p_section):
        self._configuration.add_section(p_section=p_section)
        self._configuration._scan_section(p_section_name=p_section.section_name)


NONE_TYPE_PREFIX = "_TYPE_"


class SimpleConfigurationSectionHandler(ConfigurationSectionHandler):

    def __init__(self, p_config_model):
        super().__init__(p_section_prefix=p_config_model._section_name)
        self._config_model = p_config_model

    def handle_section(self, p_section_name):
        self.scan(p_section=self._config_model)


class ConfigModel(object):

    def __init__(self, p_section_name, p_class_name=None):

        self.section_name = p_section_name
        self._options = {}

    def is_active(self):
        raise NotImplementedError("ConfigModel.is_active")

    def get_option_type(self, p_option_name):

        p_effective_name = NONE_TYPE_PREFIX + p_option_name

        value = self.__dict__.get(p_effective_name)

        if value is not None:
            return value.__name__

        else:
            return type(self.__dict__[p_option_name]).__name__

    def has_option(self, p_option_name):

        p_effective_name = NONE_TYPE_PREFIX + p_option_name

        return p_option_name in self.__dict__ or p_effective_name in self.__dict__

    def __getattr__(self, p_option_name):

        p_effective_name = NONE_TYPE_PREFIX + p_option_name

        value = self.__dict__.get(p_effective_name)

        if value is not None:
            return None

        else:
            value = self.__dict__.get(p_option_name)

            if value is not None:
                return value

            else:
                raise AttributeError

    def __setattr__(self, p_option_name, p_value):

        if isinstance(p_value, type):
            p_effective_name = NONE_TYPE_PREFIX + p_option_name
            self.__dict__[p_effective_name] = p_value

        else:
            self.__dict__[p_option_name] = p_value


class Configuration(ConfigModel):

    def __init__(self):

        super().__init__(p_section_name="_Configuration_")

        self._sections = {}
        self._logger = log_handling.get_logger(self.__class__.__name__)
        self._section_handlers = []

    def add_section(self, p_section):

        if p_section.section_name in self._sections:
            fmt = "Overwriting existing section '%s'" % p_section.section_name
            self._logger.warning(fmt)

        self._sections[p_section.section_name] = p_section

    def register_section_handler(self, p_section_handler):

        self._section_handlers.append(p_section_handler)
        p_section_handler.set_configuration(p_configuration=self)

    def __getitem__(self, p_key):

        if not p_key in self._sections:
            raise ConfigurationException("No section '%s' configured in class %s" % (p_key, self.__class__.__name__))

        return self._sections[p_key]

    def set_config_value(self, p_section_name, p_option, p_option_value):

        section = self._sections.get(p_section_name)

        if section is None:
            raise ConfigurationException("Invalid section name '%s'" % p_section_name)

        if not section.has_option(p_option_name=p_option):
            raise ConfigurationException(
                "Configuration file contains invalid setting '%s' in section '%s'" % (p_option, p_section_name))

        option_type = section.get_option_type(p_option_name=p_option)

        upper_value = p_option_value.upper()
        if option_type == 'bool':
            if upper_value in VALID_BOOLEAN_TRUE_VALUES:
                setattr(section, p_option, True)

            elif upper_value in VALID_BOOLEAN_FALSE_VALUES:
                setattr(section, p_option, False)

            else:
                raise ConfigurationException("Invalid Boolean value '%s' in setting '%s' of section '%s'" % (
                p_option_value, p_option, p_section_name))

        elif option_type == 'int':
            try:
                intValue = int(p_option_value)
                setattr(section, p_option, intValue)

            except Exception as e:
                raise ConfigurationException("Invalid numerical value '%s' in setting '%s' of section '%s': %s" % (
                    p_option_value, p_option, p_section_name, str(e)))
        else:
            setattr(section, p_option, p_option_value)

    def _scan_section(self, p_section_name):

        section = self._sections.get(p_section_name)

        fmt = "Scanning settings for section '%s'" % p_section_name
        self._logger.debug(fmt)

        if section is None:
            raise ConfigurationException("Invalid section name '%s'" % p_section_name)

        for option in self.config.options(p_section_name):
            option_value = self.config.get(p_section_name, option)
            self.set_config_value(
                p_section_name=p_section_name,
                p_option=option,
                p_option_value=option_value)

    def handle_section(self, p_section_name, p_ignore_invalid_sections=False, p_warn_about_invalid_sections=False):

        for section_handler in self._section_handlers:
            if p_section_name.startswith(section_handler.section_prefix):
                section_handler.handle_section(p_section_name=p_section_name)
                return

        if p_ignore_invalid_sections:
            if p_warn_about_invalid_sections:
                fmt = "Ignoring invalid section '%s' (not all sections registered?)" % p_section_name
                self._logger.warning(fmt)

        else:
            fmt = "Invalid section '%s'" % p_section_name
            self._logger.error(fmt)
            raise ConfigurationException("Configuration file contains invalid section '%s'" % p_section_name)

    def read_config_file(self, p_filename=None, p_config_string=None,
                         p_ignore_invalid_sections=False, p_warn_about_invalid_sections=False):

        errorMessage = None

        if p_filename is not None:
            fmt = "Reading configuration file from '%s'" % p_filename
            self._logger.info(fmt)

            self.config = configparser.ConfigParser()
            self.config.optionxform = str  # make options case sensitive

            try:
                filesRead = self.config.read([p_filename], encoding="UTF-8")
                if len(filesRead) != 1:
                    errorMessage = "Error while reading configuration file '%s' (file probably does not exist)" % p_filename

            except Exception as e:
                errorMessage = "Exception '%s' while reading configuration file '%s'" % (str(e), p_filename)

        if p_config_string is not None:

            try:
                self.config = configparser.ConfigParser()
                self.config.read_string(p_config_string)

            except Exception as e:
                errorMessage = "Exception '%s' while reading setting" % (str(e))

        if errorMessage is not None:
            raise ConfigurationException(errorMessage)

        for section_name in self.config.sections():

            if section_name in self._sections:

                new_section = self._sections[section_name]
                setattr(self, section_name, new_section)
                self._scan_section(section_name)

            else:

                self.handle_section(p_section_name=section_name,
                                    p_ignore_invalid_sections=p_ignore_invalid_sections,
                                    p_warn_about_invalid_sections=p_warn_about_invalid_sections)

    def read_command_line_parameters(self, p_parameters):

        for par in p_parameters:
            result = REGEX_CMDLINE_PARAMETER.match(par)
            if result:

                section_name = result.group(1)
                option_name = result.group(2)
                value = result.group(3)

                if "PASSW" in option_name.upper() or "KENNW" in option_name.upper():
                    protected_value = "[hidden]"

                else:
                    protected_value = value

                fmt = "Command line setting: set '[%s]%s' to value '%s'" % (
                    section_name, option_name, protected_value)
                self._logger.info(fmt)

                self.set_config_value(
                    p_section_name=section_name,
                    p_option=option_name,
                    p_option_value=value)

            else:
                fmt = "Incorrectly formatted command line setting: %s" % par
                self._logger.warning(fmt)
