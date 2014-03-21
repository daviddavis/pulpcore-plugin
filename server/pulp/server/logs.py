# -*- coding: utf-8 -*-
#
# Copyright © 2010-2014 Red Hat, Inc.
#
# This software is licensed to you under the GNU General Public
# License as published by the Free Software Foundation; either version
# 2 of the License (GPLv2) or (at your option) any later version.
# There is NO WARRANTY for this software, express or implied,
# including the implied warranties of MERCHANTABILITY,
# NON-INFRINGEMENT, or FITNESS FOR A PARTICULAR PURPOSE. You should
# have received a copy of GPLv2 along with this software; if not, see
# http://www.gnu.org/licenses/old-licenses/gpl-2.0.txt.
"""
This module defines and configures Pulp's logging system.
"""
import ConfigParser
import logging.handlers
import os

from pulp.server import config


DEFAULT_LOG_LEVEL = logging.INFO
LOG_FORMAT_STRING = 'pulp: %(name)s:%(levelname)s: %(message)s'


def start_logging():
    """
    Configure Pulp's syslog handler for the configured log level.
    """
    # Get and set up the root logger with our configured log level
    try:
        log_level = config.config.get('server', 'log_level')
        log_level = getattr(logging, log_level.upper())
    except (ConfigParser.NoOptionError, AttributeError):
        # If the user didn't provide a log level, or if they provided an invalid one, let's use the
        # default log level
        log_level = DEFAULT_LOG_LEVEL
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Set up our handler and add it to the root logger
    handler = CompliantSysLogHandler(address=os.path.join('/', 'dev', 'log'),
                                     facility=CompliantSysLogHandler.LOG_DAEMON)
    formatter = logging.Formatter(LOG_FORMAT_STRING)
    handler.setFormatter(formatter)
    root_logger.handlers = []
    root_logger.addHandler(handler)

    # Some of our libraries and code have already gotten loggers before we started logging. We need
    # to iterate over all the loggers. For each child logger we need to configure it to propagate
    # to its parent. For each parent, we will need to configure it to our our handler.
    parent_logger_names = set()
    for logger_name in root_logger.manager.loggerDict.keys():
        if '.' in logger_name:
            # This is a "child" logger. We should set it to propagate all of its messages to its
            # parent for handling.
            logger = logging.getLogger(logger_name)
            logger.propagate = 1
            logger.level = logging.NOTSET
            logger.handlers = []
            # Add this child's parent logger to our set of known parents.
            parent_logger_name = logger_name.split('.')[0]
            parent_logger_names.add(parent_logger_name)
        else:
            # This is a parent logger. Let's add it to the set of known parent loggers and
            # continue. We'll deal with the parents in the next block.
            parent_logger_names.add(logger_name)

    # Now let's configure all parent loggers to use our handler
    for logger_name in parent_logger_names:
        logger = logging.getLogger(logger_name)
        # Since this is the parent, we don't want its logs to propagate any further
        logger.propagate = 0
        logger.level = log_level
        # Let's remove any handlers that may have been on this logger, so that it's just ours.
        # If we didn't do this, some log messages could be duplicated in the syslog (such as
        # the Celery logs).
        logger.handlers = []
        logger.addHandler(handler)


def stop_logging():
    """
    Stop Pulp's logging.
    """
    # remove all the existing handlers and loggers from the logging module
    logging.shutdown()


class CompliantSysLogHandler(logging.handlers.SysLogHandler):
    """
    RFC 5426[0] recommends that we limit the length of our log messages. RFC 3164[1] requires that
    we only include visible characters and spaces in our log messages. Though RFC 3164 is obsoleted
    by 5424[2], Pulp wishes to support older syslog receivers that do not handle newline characters
    gracefully. The tracebacks that Pulp generates can cause problems both due to their length and
    their newlines. This log handler will split messages into multiple messages by newline
    characters (since newline characters aren't handled well) and further by message length. RFC
    5426 doesn't make any specific demands about message length but it appears that our
    target operating systems allow approximately 2041 characters, so we will split there. RFC 5424
    requires that all strings be encoded with UTF-8. Therefore, this
    log handler only accepts unicode strings, or UTF-8 encoded strings.

    [0] https://tools.ietf.org/html/rfc5426#section-3.2
    [1] https://tools.ietf.org/html/rfc3164#section-4.1.3
    [2] https://tools.ietf.org/html/rfc5424#section-6.4
    """
    MAX_MSG_LENGTH = 2041

    def emit(self, record):
        """
        This gets called whenever a log message needs to get sent to the syslog. This method will
        inspect the record, and if it contains newlines, it will break the record into multiple
        records. For each of those records, it will also verify that they are no longer than
        MAX_MSG_LENGTH octets. If they are, it will break them up at that boundary as well.

        :param record: The record to be logged via syslog
        :type  record: logging.LogRecord
        """
        if record.exc_info:
            if not isinstance(record.msg, basestring):
                record.msg = unicode(record.msg)
            record.msg += u'\n'
            record.msg += self.formatter.formatException(record.exc_info)
            record.exc_info = None
        formatter_buffer = self._calculate_formatter_buffer(record)
        for line in record.getMessage().split('\n'):
            for message_chunk in CompliantSysLogHandler._cut_message(line, formatter_buffer):
                # We need to use the attributes from record to generate a new record that has
                # mostly the same attributes, but the shorter message. We need to set the args to
                # the empty tuple so that breaking the message up doesn't mess up formatting. This
                # is OK, since record.getMessage() will apply the args to msg for us. exc_info is
                # set to None, as we have already turned any Exceptions into the message
                # that we are now splitting, and we don't want tracebacks to make it past our
                # splitter here because the superclass will transmit newline characters.
                new_record = logging.LogRecord(
                    name=record.name, level=record.levelno, pathname=record.pathname,
                    lineno=record.lineno, msg=message_chunk, args=tuple(),
                    exc_info=None, func=record.funcName)
                super(CompliantSysLogHandler, self).emit(new_record)

    def _calculate_formatter_buffer(self, record):
        """
        Given a record with no exc_info, determine how many bytes the formatter will add to it so
        that we know how much room to leave when trimming messages.

        :param record: An example record that can be used to find the formatter buffer
        :type  record: logging.LogRecord
        :return:       The difference between the rendered record length and the message length.
        :rtype:        int
        """
        formatted_record = self.format(record)
        if isinstance(formatted_record, unicode):
            formatted_record = formatted_record.encode('utf8')
        raw_record = record.getMessage()
        if isinstance(raw_record, unicode):
            raw_record = raw_record.encode('utf8')
        return len(formatted_record) - len(raw_record)

    @staticmethod
    def _cut_message(message, formatter_buffer):
        """
        Return a generator of strings made from message cut at every
        MAX_MSG_LENGTH - formatter_buffer octets, with the exception that it will not cut
        multi-byte characters apart. This method also encodes unicode objects with UTF-8 as a side
        effect, because length limits are specified in octets, not characters.

        :param message:          A message that needs to be broken up if it's too long
        :type  message:          basestring
        :param formatter_buffer: How many octets of room to leave on each message to account for
                                 extra data that the formatter will add to this message
        :type  formatter_buffer: int
        :return:                 A generator of str objects, each of which is no longer than
                                 MAX_MSG_LENGTH - formatter_buffer octets.
        :rtype:                  generator
        """
        max_length = CompliantSysLogHandler.MAX_MSG_LENGTH - formatter_buffer
        if isinstance(message, unicode):
            message = message.encode('utf8')

        i = 0
        while i < len(message):
            relative_ending_index = min(max_length, len(message[i:]))
            if len(message) > i + relative_ending_index:
                # Let's peek one character ahead and see if we are in the middle of a multi-byte
                # character.
                while (ord(message[i + relative_ending_index]) >> 6) == 2:
                    # Any byte of the form 10xxxxxx is a non-leading part of a multi-byte character
                    # in UTF-8. Therefore, we must seek backwards a bit to make sure we don't cut
                    # any multi-byte characters in half.
                    relative_ending_index -= 1
            yield message[i:i + relative_ending_index]
            i += relative_ending_index

        if i == 0:
            # If i is still 0, we must have been passed the empty string
            yield ''
