#! /usr/bin/env python
# -*- coding: utf-8 -*-
####################
# http://www.indigodomo.com

import indigo
import time
import re
import subprocess
import urlparse
from urllib import pathname2url
try:
    from shlex import quote as cmd_quote
except ImportError:
    from pipes import quote as cmd_quote

# Note the "indigo" module is automatically imported and made available inside
# our global name space by the host process.

###############################################################################
# globals

k_diskStatusImage   = ( indigo.kStateImageSel.SensorOff, indigo.kStateImageSel.SensorOn )

k_localMountCmd     = "/usr/sbin/diskutil mount {filesystem}".format
k_localUnmountCmd   = "/usr/sbin/diskutil umount {force} {filesystem}".format
k_networkMountCmd   = "/bin/mkdir {mountpoint} 2>/dev/null; /sbin/mount -t {urlscheme} {volumeurl} {mountpoint}".format
k_networkUnmountCmd = "/sbin/umount {force} {filesystem}".format

k_dfGetDataCmd      = "/bin/df -mn"
k_dfInfoGroupsKeys  =           (       'size',   'used',   'free',  'percent'    )
k_dfInfoGroupsRegex = re.compile(r".+? ([0-9]+) +([0-9]+) +([0-9]+) +([0-9]+)% .+")
k_dfSearchExp       = "^{filesystem} .*$".format

k_getFilesystemCmd  = "/usr/sbin/diskutil list | grep {expression}".format
k_getFilesystemExp  = " {volumename}  ".format

k_touchDiskCmd      = "/usr/bin/touch {mountpoint}/.preventsleep".format

k_returnFalseCmd    = "echo {message}; false".format

k_urlSchemes        = {'smb':'smbfs', 'nfs':'nfs', 'afp':'afp', 'ftp':'ftp', 'webdav':'webdav'}

################################################################################
class Plugin(indigo.PluginBase):
    ########################################
    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)
    
    def __del__(self):
        indigo.PluginBase.__del__(self)

    ########################################
    # Start, Stop and Config changes
    ########################################
    def startup(self):
        
        self.stateLoopFreq  = int(self.pluginPrefs.get('stateLoopFreq','10'))
        self.refreshFSFreq  = int(self.pluginPrefs.get('refreshFSFreq','10'))*60
        self.touchDiskFreq  = int(self.pluginPrefs.get('touchDiskFreq','10'))*60
        self.debug          = self.pluginPrefs.get('showDebugInfo',False)
        self.logger.debug("startup")
        if self.debug:
            self.logger.debug("Debug logging enabled")
        
        self.deviceDict = dict()
        self._dfData = ""
        self._dfTime = 0
        self.df_refresh = True

    ########################################
    def shutdown(self):
        self.logger.debug("shutdown")
        self.pluginPrefs["showDebugInfo"] = self.debug

    ########################################
    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        self.logger.debug("closedPrefsConfigUi")
        if not userCancelled:
            self.stateLoopFreq  = int(valuesDict['stateLoopFreq'])
            self.refreshFSFreq  = int(valuesDict['refreshFSFreq'])*60
            self.touchDiskFreq  = int(valuesDict['touchDiskFreq'])*60
            self.debug          =     valuesDict['showDebugInfo']
            if self.debug:
                self.logger.debug("Debug logging enabled")

    ########################################
    def validatePrefsConfigUi(self, valuesDict):
        self.logger.debug("validatePrefsConfigUi")
        errorsDict = indigo.Dict()
                
        if len(errorsDict) > 0:
            self.logger.debug('validate prefs config error: \n{0}'.format(str(errorsDict)))
            return (False, valuesDict, errorsDict)
        return (True, valuesDict)
    
    ########################################
    def runConcurrentThread(self):
        lastRefreshFS = lastTouchDisk = 0
        self.sleep(self.stateLoopFreq)
        try:
            while True:
                loopStart = time.time()
                
                doRefreshFS = loopStart >= lastRefreshFS  + self.refreshFSFreq
                doTouchDisk = loopStart >= lastTouchDisk  + self.touchDiskFreq
                
                self.df_refresh = True
                for devId, dev in self.deviceDict.items():
                    dev.update(doRefreshFS, doTouchDisk)
                
                lastRefreshFS = [lastRefreshFS, loopStart][doRefreshFS]
                lastTouchDisk = [lastTouchDisk, loopStart][doTouchDisk]
                
                self.sleep( loopStart + self.stateLoopFreq - time.time() )
        except self.StopThread:
            pass    # Optionally catch the StopThread exception and do any needed cleanup.
    
    ########################################
    @property
    def dfResults(self):
        if self.df_refresh:
            success, data = do_shell_script(k_dfGetDataCmd)
            if success:
                self._dfData = data
                self._dfTime = time.time()
                self.df_refresh = False
        return self._dfData, self._dfTime
    
    ########################################
    # Device Methods
    ########################################
    def deviceStartComm(self, dev):
        self.logger.debug("deviceStartComm: "+dev.name)
        if dev.version != self.pluginVersion:
            self.updateDeviceVersion(dev)
        if dev.configured:
            self.deviceDict[dev.id] = self.DiskDevice(dev, self)
            self.deviceDict[dev.id].update(True)
    
    ########################################
    def deviceStopComm(self, dev):
        self.logger.debug("deviceStopComm: "+dev.name)
        if dev.id in self.deviceDict:
            del self.deviceDict[dev.id]
    
    ########################################
    def validateDeviceConfigUi(self, valuesDict, deviceTypeId, devId, runtime=False):
        self.logger.debug("validateDeviceConfigUi: " + deviceTypeId)
        errorsDict = indigo.Dict()
        
        if not valuesDict.get('volumeName',''):
            errorsDict['volumeName'] = "Required"
        else:
            valuesDict['mountPoint'] = "/Volumes/"+valuesDict['volumeName']
        
        if deviceTypeId == 'networkDisk':
            if not valuesDict.get('volumeURL',''):
                errorsDict['volumeURL'] = "Required"
            elif not is_valid_url(valuesDict['volumeURL']):
                errorsDict['volumeURL'] = "Not valid URL"
            else:
                try:
                    parsed = urlparse.urlsplit(valuesDict['volumeURL'])
                    valuesDict['urlScheme'] = k_urlSchemes[parsed.scheme]
                except:
                    errorsDict['volumeURL'] = "Not supported filesystem type"
        
        if len(errorsDict) > 0:
            self.logger.debug('validate device config error: \n{0}'.format(str(errorsDict)))
            return (False, valuesDict, errorsDict)
        else:
            return (True, valuesDict)
    
    ########################################
    def updateDeviceVersion(self, dev):
        theProps = dev.pluginProps
        # update states
        dev.stateListOrDisplayStateIdChanged()
        # check for props
        
        # push to server
        theProps["version"] = self.pluginVersion
        dev.replacePluginPropsOnServer(theProps)
    
    
    ########################################
    # Action Methods
    ########################################
    def actionControlDimmerRelay(self, action, dev):
        self.logger.debug("actionControlDimmerRelay: "+dev.name)
        disk = self.deviceDict[dev.id]
        # TURN ON
        if action.deviceAction == indigo.kDimmerRelayAction.TurnOn:
            disk.onState = True
        # TURN OFF
        elif action.deviceAction == indigo.kDimmerRelayAction.TurnOff:
            disk.onState = False
        # TOGGLE
        elif action.deviceAction == indigo.kDimmerRelayAction.Toggle:
            disk.onState = not app.onState
        # STATUS REQUEST
        elif action.deviceAction == indigo.kUniversalAction.RequestStatus:
            self.logger.info('"{0}" status update'.format(dev.name))
            self.df_refresh = True
            disk.update(True)
        # UNKNOWN
        else:
            self.logger.debug('"{0}" {1} request ignored'.format(dev.name, str(action.deviceAction)))
    
    ########################################
    # Menu Methods
    ########################################
    def toggleDebug(self):
        if self.debug:
            self.logger.debug("Debug logging disabled")
            self.debug = False
        else:
            self.debug = True
            self.logger.debug("Debug logging enabled")
    
    
    
    ########################################
    # Classes
    ########################################
    ########################################
    class DiskDevice(object):
        ########################################
        def __init__(self, instance, plugin):
            self.dev        = instance
            self.name       = self.dev.name
            self.type       = self.dev.deviceTypeId
            self.props      = self.dev.pluginProps
            self.states     = self.dev.states
            
            self.plugin     = plugin
            self.logger     = plugin.logger
            
            self.touchCmd   = k_touchDiskCmd( mountpoint = cmd_quote(self.props['mountPoint']) )
            
            self._dfInfo    = ""
            self._dfTime    = 0
            self._dfRegex = re.compile( "^$" )
            self.dfRegex_refresh  = True
        

        ########################################
        def update(self, doRefreshFS=False, doTouchDisk=False):
            self.states['onOffState'] = self.onOffFilesystem(doRefreshFS)
            
            if self.onState:
                diskStats = regextract(self.dfInfo, k_dfInfoGroupsRegex, k_dfInfoGroupsKeys)
                self.states['megs_total']   = int(diskStats['size'])
                self.states['megs_used']    = int(diskStats['used'])
                self.states['megs_free']    = int(diskStats['free'])
                self.states['percent_used'] = int(diskStats['percent'])
                self.states['percent_free'] = 100-int(diskStats['percent'])
                self.states['size_total']   = mb_to_string(int(diskStats['size']))
                self.states['size_used']    = mb_to_string(int(diskStats['used']))
                self.states['size_free']    = mb_to_string(int(diskStats['free']))
                
                if doTouchDisk:
                    self.touch()
            
            newStates = []
            for key, value in self.states.iteritems():
                if self.states[key] != self.dev.states[key]:
                    if key in ['percent_free','percent_used']:
                        newStates.append({'key':key,'value':value, 'uiValue': '{0}%'.format(value)})
                    elif key in ['megs_free','megs_used','megs_total']:
                        newStates.append({'key':key,'value':value, 'uiValue': '{0} MB'.format(value)})
                    else:
                        newStates.append({'key':key,'value':value})
                    
                    if key == 'onOffState':
                        self.logger.info('"{0}" {1}'.format(self.name, ['off','on'][value]))
                        self.dev.updateStateImageOnServer(k_diskStatusImage[value])
                
            if len(newStates) > 0:
                if self.plugin.debug: # don't fill up plugin log unless actively debugging
                    self.logger.debug('updating states on device "{0}":'.format(self.name))
                    for item in newStates:
                        self.logger.debug('{:>16}: {}'.format(item['key'],item['value']))
                self.dev.updateStatesOnServer(newStates)
                self.states = self.dev.states
        
        def touch(self):
            if self.props['preventSleep'] and self.onState:
                self.logger.debug('touching file on volume "{0}"'.format(self.props['volumeName']))
                success, response = do_shell_script(self.touchCmd)
                if success:
                    self.states['last_touch'] = time.strftime('%Y-%m-%d %T')
                else:
                    self.logger.error('touch disk "{0}" failed'.format(self.props['volumeName']))
                    self.logger.debug(response)
        
        ########################################
        def onOffFilesystem(self, force=False):
            if self.type == 'localDisk':
                if not self.states['filesystem'] or force:
                    self.logger.debug('getting filesystem for volume "{0}"'.format(self.props['volumeName']))
                    if self.type == 'localDisk':
                        self.states['filesystem'] = ''
                        exp = k_getFilesystemExp( volumename=self.props['volumeName'] )
                        cmd = k_getFilesystemCmd( expression=cmd_quote(exp) )
                        success, data = do_shell_script(cmd)
                        if success:
                            for line in data.splitlines()[::-1]:
                                disk_type  = line[6:32].strip()
                                filesystem = '/dev/' + line[68:].strip()
                                if disk_type != 'Apple_CoreStorage':
                                    self.states['disk_type']  = disk_type
                                    self.states['filesystem'] = filesystem
                                    self.dfRegex_refresh = True
                                    break
            elif self.type == 'networkDisk':
                if not self.states['filesystem']:
                    parsed     = urlparse.urlsplit(self.props['volumeURL'])
                    self.states['disk_type']  = parsed.scheme
                    self.states['filesystem'] = '//'
                    if parsed.username: self.states['filesystem'] += pathname2url(parsed.username) + '@'
                    if parsed.hostname: self.states['filesystem'] += parsed.hostname
                    if parsed.port:     self.states['filesystem'] += ':' + parsed.port
                    if parsed.path:     self.states['filesystem'] += pathname2url(parsed.path)
                    self.dfRegex_refresh = True
            return bool(self.dfInfo)
        
        
        ########################################
        # Class Properties
        ########################################
        def onStateGet(self):
            return self.states['onOffState']
        
        def onStateSet(self,newState):
            if newState != self.onState:
                success, response = do_shell_script(self.onOffCmds[newState])
                if success:
                    self.logger.info('{0} volume "{1}"'.format(['unmounting','mounting'][newState], self.props['volumeName']))
                    self.plugin.psRefresh = True
                    self.dfRegex_refresh = True
                    self.plugin.sleep(0.25)
                    self.update(True)
                else:
                    self.logger.error('failed to {0} volume "{1}"'.format(['unmount','mount'][newState], self.props['volumeName']))
                    self.logger.debug(response)
        
        onState = property(onStateGet, onStateSet)
        
        ########################################
        @property
        def onOffCmds(self):
            onCmd = offCmd = k_returnFalseCmd( message = "not available" )
            if self.type == 'localDisk':
                if self.states['filesystem']:
                    onCmd  = k_localMountCmd(   filesystem  = cmd_quote(self.states['filesystem']))
                    offCmd = k_localUnmountCmd( filesystem  = cmd_quote(self.states['filesystem']),
                                                force       = ['','force'][self.props['forceUnmount']] )
            elif self.type == 'networkDisk':
                onCmd = k_networkMountCmd(      mountpoint  = cmd_quote(self.props['mountPoint']),
                                                volumeurl   = cmd_quote(self.props['volumeURL']),
                                                urlscheme   = self.props['urlScheme'] )
                if self.states['filesystem']:
                    offCmd = k_networkUnmountCmd(   filesystem  = cmd_quote(self.states['filesystem']),
                                                    mountpoint  = cmd_quote(self.props['mountPoint']),
                                                    force       = ['','-f'][self.props['forceUnmount']] )
            
            return (offCmd,onCmd)
        
        ########################################
        @property
        def dfInfo(self):
            dfData, dfTime = self.plugin.dfResults
            if dfTime > self._dfTime:
                match = self.dfRegex.search(dfData)
                if match:
                    self._dfInfo = match.group(0)
                else:
                    self._dfInfo = False
                self._dfTime = dfTime
            return self._dfInfo
    
        @property
        def dfRegex(self):
            if self.dfRegex_refresh:
                if self.states['filesystem']:
                    exp = k_dfSearchExp( filesystem = self.states['filesystem'] )
                    self._dfRegex = re.compile( exp, re.MULTILINE )
                    self.dfRegex_refresh = False
                else:
                    self._dfRegex = re.compile( "^$" )
            return self._dfRegex
        
    
    
    
########################################
# Utilities
########################################
def do_shell_script (cmd):
    p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out, err = p.communicate()
    return (not bool(p.returncode)), out.rstrip()

########################################
def regextract (source, rule, keys):
    results = {}
    for key, value in zip(keys,rule.match(source).groups()):
        results[key] = value.strip()
    return results
        
########################################
# http://stackoverflow.com/questions/7160737/python-how-to-validate-a-url-in-python-malformed-or-not#7160819
def is_valid_url(url, qualifying=None):
    min_attributes = ('scheme', 'netloc')
    qualifying = min_attributes if qualifying is None else qualifying
    token = urlparse.urlparse(url)
    return all([getattr(token, qualifying_attr)
                for qualifying_attr in qualifying])

########################################
# http://stackoverflow.com/questions/12523586/python-format-size-application-converting-b-to-kb-mb-gb-tb#12523683
def mb_to_string(unitCount, precision=2):
    if unitCount < 0:
        raise ValueError("!!! unitCount can't be less than 0 !!!")
    step_to_greater_unit = 1024.
    unitCount = float(unitCount)
    unit = 'MB'
    if (unitCount / step_to_greater_unit) >= 1:
        unitCount /= step_to_greater_unit
        unit = 'GB'
    if (unitCount / step_to_greater_unit) >= 1:
        unitCount /= step_to_greater_unit
        unit = 'TB'
    return str(round(unitCount, precision)) + ' ' + unit