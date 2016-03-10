#!/usr/bin/env python2.5
# Filename: indigoPluginUtils.py

import indigo

##########################################################################################
# logger class for Indigo Plugins.  Originally written by berkinet, modified by Travis
#
# Usage:
#
#
#	1. 	Create an instance.  It will check the pluginPrefs for the showDebugInfo1
#		log level setting.
#			self.mylogger = indigoPluginUtils.logger(self)
#
#	2.	Log like so.  The first argument is the log level, second is the log.
#		It will only log the message if the message's log level is <= logLevel.
#		self.mylogger.log(1, "Bla bla")
#
#	3.  To log errors:
#		self.mylogger.logError("Oops, error")
#
#	4.  To read the loggers log level in the plugin:
#		logLevel = self.mylogger.logLevel
#


class logger(object):

	def __init__(self, plugin):
		self.plugin = plugin
		self.logLevel = None
		self.readConfig()

	def readConfig(self):
		kLogLevelList = ['None', 'Normal', 'Verbose', 'Debug', 'Intense Debug']

		# Save current log level
		oldLevel = self.logLevel
		# Get new log level from prefs, default to 1 if not found
		self.logLevel = int(self.plugin.pluginPrefs.get("showDebugInfo1", "1"))

		# Validate log level
		if self.logLevel > 4:
			self.logLevel = 1

		# Enable debugging?
		if self.logLevel > 2:
			self.plugin.debug = True
		else:
			self.plugin.debug = False

		# If this is the first run
		if(oldLevel is None):
			self.log(1, "Log level preferences are set to \"%s\"." % kLogLevelList[self.logLevel])
		# or are we just checking for a change in log level
		elif oldLevel != self.logLevel:
			self.log(1, "Log level preferences changed to \"%s\"." % kLogLevelList[self.logLevel])

	def log(self, level, logMsg):
		if level <= self.logLevel:
			if level < 3:
				indigo.server.log(logMsg)
			else:
				self.plugin.debugLog(logMsg)

	def logError(self, logMsg):
		indigo.server.log(logMsg, isError=True)
