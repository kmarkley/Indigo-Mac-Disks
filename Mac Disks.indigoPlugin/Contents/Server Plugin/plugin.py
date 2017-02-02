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

_localMountCmd     = "/usr/sbin/diskutil mount {device}".format
_localUnmountCmd   = "/usr/sbin/diskutil umount {force} {device}".format
_networkMountCmd   = "/bin/mkdir {mountpoint} 2>/dev/null; /sbin/mount -t {urlscheme} {volumeurl} {mountpoint}".format
_networkUnmountCmd = "/sbin/umount {force} {filesystem}; /bin/rmdir {mountpoint} 2>/dev/null".format

_getStatsCmd       = "/bin/df -mn | grep {expression}".format
_getStatsExp       = "^{filesystem} ".format
_reVolumeData      = re.compile(r".+? ([0-9]+) +([0-9]+) +([0-9]+) +([0-9]+)% .+")

_getFilesystemCmd  = "/usr/sbin/diskutil list | grep {expression}".format
_getFilesystemExp  = " {volumename}  ".format

_touchDiskCmd      = "touch /Volumes/{volumename}/.preventsleep".format

_returnFalseCmd    = "false"

_urlschemes        = {'smb':'smbfs', 'nfs':'nfs', 'afp':'afp', 'ftp':'ftp', 'webdav':'webdav'}

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
        #indigo.devices.subscribeToChanges()

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
        lastRefreshFS = lastTouchDisk = time.time()
        self.sleep(self.stateLoopFreq)
        try:
            while True:
                loopStart = time.time()
                
                doRefreshFS = loopStart >= lastRefreshFS  + self.refreshFSFreq
                doTouchDisk = loopStart >= lastTouchDisk  + self.touchDiskFreq
                
                for devId in self.deviceDict:
                    self.updateDeviceStates(devId, doRefreshFS, doTouchDisk)
                
                lastRefreshFS = [lastRefreshFS, loopStart][doRefreshFS]
                lastTouchDisk = [lastTouchDisk, loopStart][doTouchDisk]
                
                self.sleep( loopStart + self.stateLoopFreq - time.time() )
        except self.StopThread:
            pass    # Optionally catch the StopThread exception and do any needed cleanup.
    
    ########################################
    # Device Methods
    ########################################
    def deviceStartComm(self, dev):
        self.logger.debug("deviceStartComm: "+dev.name)
        if dev.version != self.pluginVersion:
            self.updateDeviceVersion(dev)
        theProps = dev.pluginProps
        
        if dev.deviceTypeId == 'localDisk':
            pass
            
        elif dev.deviceTypeId == 'networkDisk':
            parsed = urlparse.urlsplit(theProps['volumeURL'])
            theProps['urlScheme'] = _urlschemes[parsed.scheme]
            theProps['mountPoint'] = "/Volumes/"+theProps['volumeName']
        
        if theProps != dev.pluginProps:
            dev.replacePluginPropsOnServer(theProps)
        self.deviceDict[dev.id] = { 'dev'      :dev, 
                                    'mountCmd' :self.getMountCmd(dev), 
                                    'statsCmd' :self.getStatsCmd(dev), 
                                    'touchCmd' :self.getTouchCmd(dev),
                                    'locFSCmd' :self.getLocFSCmd(dev) }
        self.updateDeviceStates(dev.id, True)
    
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
        
        if deviceTypeId == 'networkDisk':
            if not valuesDict.get('volumeURL',''):
                errorsDict['volumeURL'] = "Required"
            elif not is_valid_url(valuesDict['volumeURL']):
                errorsDict['volumeURL'] = "Not valid URL"
        
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
    def setDeviceOnOff(self, devId, onOffState):
        dev = self.deviceDict[devId]['dev']
        if dev.states['onOffState'] != onOffState:
            cmd = self.deviceDict[devId]['mountCmd'][onOffState]
            if do_shell_script(cmd)[0]:
                self.logger.info('{0} volume "{1}"'.format(['unmounting','mounting'][onOffState], dev.pluginProps['volumeName']))
                self.updateDeviceStates(devId)
            else:
                self.logger.error('can\'t {0} volume "{1}"'.format(['unmount','mount'][onOffState], dev.pluginProps['volumeName']))
    
    ########################################
    def updateDeviceStates(self, devId, doRefreshFS=False, doTouchDisk=False):
        dev = self.deviceDict[devId]['dev']
        theStates = dev.states
        filesystemChanged = False
        
        if  doRefreshFS or (not theStates['filesystem']):
            self.logger.debug('getting filesystem for volume "{0}"'.format(dev.pluginProps['volumeName']))
            if dev.deviceTypeId == 'localDisk':
                success, data = do_shell_script(self.deviceDict[devId]['locFSCmd'])
                if success:
                    for line in data.splitlines():
                        theStates['diskType']   = line[6:32].strip()
                        theStates['filesystem'] = '/dev/' + line[68:].strip()
                        if theStates['diskType'] != 'Apple_CoreStorage':
                            break
            elif dev.deviceTypeId == 'networkDisk':
                parsed     = urlparse.urlsplit(dev.pluginProps['volumeURL'])
                theStates['diskType']   = parsed.scheme
                theStates['filesystem'] = '//'
                if parsed.username: theStates['filesystem'] += pathname2url(parsed.username) + '@'
                if parsed.hostname: theStates['filesystem'] += parsed.hostname
                if parsed.port:     theStates['filesystem'] += ':' + parsed.port
                if parsed.path:     theStates['filesystem'] += pathname2url(parsed.path)
            if theStates['filesystem'] != dev.states['filesystem']:
                filesystemChanged = True
                
        if not filesystemChanged:
            mounted, result = do_shell_script(self.deviceDict[devId]['statsCmd'])
            if mounted:
                diskStats = regextract(result, _reVolumeData, ['size','used','free','percent'])
                theStates['megsTotal'] = int(diskStats['size'])
                theStates['megsUsed']  = int(diskStats['used'])
                theStates['megsFree']  = int(diskStats['free'])
                theStates['percUsed']  = int(diskStats['percent'])
                theStates['percFree']  = 100-int(diskStats['percent'])
                theStates['sizeTotal'] = mb_to_string(int(diskStats['size']))
                theStates['sizeUsed']  = mb_to_string(int(diskStats['used']))
                theStates['sizeFree']  = mb_to_string(int(diskStats['free']))
            
                if doTouchDisk and dev.pluginProps['preventSleep']:
                    self.logger.debug('touching file on volume "{0}"'.format(dev.pluginProps['volumeName']))
                    if do_shell_script(self.deviceDict[devId]['touchCmd']):
                        theStates['lastTouch'] = time.strftime('%Y-%m-%d %T')
            
            if mounted != theStates['onOffState']:
                theStates['onOffState'] = mounted
                self.logger.info('"{0}" {1}'.format(dev.name, ['off','on'][mounted]))
        
        newStates = []
        for key, value in theStates.iteritems():
            if theStates[key] != dev.states[key]:
                newStates.append({'key':key,'value':value})
        if len(newStates) > 0:
            self.logger.debug('updating states on device "{0}":'.format(dev.name))
            for item in newStates:
                self.logger.debug('{0}: {1}'.format(item['key'].rjust(12),item['value']))
            dev.updateStatesOnServer(newStates)
            
            if filesystemChanged:
                self.deviceDict[devId]['mountCmd'] = self.getMountCmd(dev)
                self.deviceDict[devId]['statsCmd'] = self.getStatsCmd(dev)
                if theStates['filesystem']:
                    # run again with new info
                    self.updateDeviceStates(devId, False, False)
                
    
    ########################################
    # Action Methods
    ########################################
    def actionControlDimmerRelay(self, action, dev):
        self.logger.debug("actionControlDimmerRelay: "+dev.name)
        # TURN ON
        if action.deviceAction == indigo.kDimmerRelayAction.TurnOn:
            self.setDeviceOnOff(dev.id, True)
        # TURN OFF
        elif action.deviceAction == indigo.kDimmerRelayAction.TurnOff:
            self.setDeviceOnOff(dev.id, False)
        # TOGGLE
        elif action.deviceAction == indigo.kDimmerRelayAction.Toggle:
            self.setDeviceOnOff(dev.id, not dev.onState)
        # STATUS REQUEST
        elif action.deviceAction == indigo.kUniversalAction.RequestStatus:
            self.logger.info('"{0}" status update'.format(dev.name))
            if dev.onState:
                self.updateDeviceStates(dev.id, True)
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
    # Callbacks
    ########################################
        
    ########################################
    # Utilities
    ########################################
    def getMountCmd(self, dev):
        if dev.deviceTypeId == 'localDisk':
            if dev.states['filesystem']:
                mCmd = _localMountCmd(      device = cmd_quote(dev.states['filesystem']))
                uCmd = _localUnmountCmd(    device = cmd_quote(dev.states['filesystem']),
                                            force  = ['','force'][dev.pluginProps['forceUnmount']] )
            else:
                mCmd = _returnFalseCmd
                uCmd = _returnFalseCmd
        elif dev.deviceTypeId == 'networkDisk':
            mCmd = _networkMountCmd(        mountpoint = cmd_quote(dev.pluginProps['mountPoint']),
                                            volumeurl  = cmd_quote(dev.pluginProps['volumeURL']),
                                            urlscheme  = dev.pluginProps['urlScheme'] )
            if dev.states['filesystem']:
                uCmd = _networkUnmountCmd(  filesystem = cmd_quote(dev.states['filesystem']),
                                            mountpoint = cmd_quote(dev.pluginProps['mountPoint']),
                                            force      = ['','-f'][dev.pluginProps['forceUnmount']] )
            else:
                uCmd = _returnFalseCmd
        return uCmd, mCmd
        
    ########################################
    def getStatsCmd(self, dev):
        if dev.states['filesystem']:
            exp = _getStatsExp( filesystem = dev.states['filesystem'] )
            cmd = _getStatsCmd( expression = cmd_quote(exp) )
        else:
            cmd = _returnFalseCmd
        return cmd
        
    ########################################
    def getTouchCmd(self, dev):
        cmd = _touchDiskCmd( volumename=dev.pluginProps['volumeName'] )
        return cmd
        
    ########################################
    def getLocFSCmd(self, dev):
        exp = _getFilesystemExp( volumename=dev.pluginProps['volumeName'] )
        cmd = _getFilesystemCmd( expression=cmd_quote(exp) )
        return cmd
        
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
def mb_to_string(unitCount, precision=1):
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