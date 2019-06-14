#!/usr/bin/env python
""" ROCm-SMI (System Management Interface) Tool

This tool provides a user-friendly interface for manipulating
the ROCK (Radeon Open Compute Kernel) via sysfs files.
Please view the README.md file for more information
"""

from __future__ import print_function, division
import os
import argparse
import re
import sys
import subprocess
from subprocess import check_output
import json
import collections
import logging
if hasattr(__builtins__, 'raw_input'):
    input = raw_input

# Version of the JSON output used to save clocks
CLOCK_JSON_VERSION = 1

# Set to 1 if an error occurs
RETCODE = 0

# If we want JSON format output instead
PRINT_JSON = False
JSON_DATA = {}

def relaunchAsSudo():
    """ Relaunch the SMI as sudo

    To write to sysfs, the SMI requires root access. Use execvp to relaunch the
    script with sudo privileges
    """
    if os.geteuid() != 0:
        os.execvp('sudo', ['sudo'] + sys.argv)

drmprefix = '/sys/class/drm'
hwmonprefix = '/sys/class/hwmon'
debugprefix = '/sys/kernel/debug/dri'
moduleprefix = '/sys/module'
kfdprefix = '/sys/class/kfd/kfd'

headerString = 'ROCm System Management Interface'
footerString = 'End of ROCm SMI Log'

# 80 characters for string and '=' fillers will be the soft-max
headerSpacer = '='* int((80 - (len(headerString))) / 2)
footerSpacer = '='* int((80 - (len(footerString))) / 2)

# If the string has an odd number of digits, pad with a space for symmetry
if len(headerString) % 2:
    headerString += ' '
if len(footerString) % 2:
    footerString += ' '
logSpacer = '=' * 80

# These are the valid clock types that can be returned/modified,
# dcefclk (only supported on Vega10 and later)
# fclk (only supported on Vega20 and later)
# mclk
# pcie (PCIe speed, sometimes referred to as lclk for Link clock
# sclk
# socclk (only supported on Vega10 and later)
validClockNames = ['dcefclk', 'fclk', 'mclk', 'pcie', 'sclk', 'socclk']

# These are the valid memory info types that are currently supported
# vram
# vis_vram (Visible VRAM)
# gtt
validMemTypes = ['vram', 'vis_vram', 'gtt']

# These are the types of supported RAS blocks and their respective enums
# gfx
# sdma
# umc
validRasBlocks = {'gfx' : 1<<2, 'sdma' : 1<<1, 'umc': 1<<0}
# These are the valid input types to a RAS file
validRasActions = ['disable', 'enable', 'inject']
# Right now, these are the only supported memory error types,
# ue - Uncorrectable error; ce - Correctable error
validRasTypes = ['ue', 'ce']

# List of software components that we support printing versioning information
validVersionComponents = ['driver']

# Supported firmware blocks
validFwBlocks = {'vce', 'uvd', 'mc', 'me', 'pfp',
'ce', 'rlc', 'rlc_srlc', 'rlc_srlg', 'rlc_srls',
'mec', 'mec2', 'sos', 'asd', 'ta_ras', 'ta_xgmi',
'smc', 'sdma', 'sdma2', 'vcn', 'dmcu'}


valuePaths = {
    'id' : {'prefix' : drmprefix, 'filepath' : 'device', 'needsparse' : True},
    'sub_id' : {'prefix' : drmprefix, 'filepath' : 'subsystem_device', 'needsparse' : False},
    'vbios' : {'prefix' : drmprefix, 'filepath' : 'vbios_version', 'needsparse' : False},
    'perf' : {'prefix' : drmprefix, 'filepath' : 'power_dpm_force_performance_level', 'needsparse' : False},
    'sclk_od' : {'prefix' : drmprefix, 'filepath' : 'pp_sclk_od', 'needsparse' : False},
    'mclk_od' : {'prefix' : drmprefix, 'filepath' : 'pp_mclk_od', 'needsparse' : False},
    'dcefclk' : {'prefix' : drmprefix, 'filepath' : 'pp_dpm_dcefclk', 'needsparse' : False},
    'fclk' : {'prefix' : drmprefix, 'filepath' : 'pp_dpm_fclk', 'needsparse' : False},
    'mclk' : {'prefix' : drmprefix, 'filepath' : 'pp_dpm_mclk', 'needsparse' : False},
    'pcie' : {'prefix' : drmprefix, 'filepath' : 'pp_dpm_pcie', 'needsparse' : False},
    'sclk' : {'prefix' : drmprefix, 'filepath' : 'pp_dpm_sclk', 'needsparse' : False},
    'socclk' : {'prefix' : drmprefix, 'filepath' : 'pp_dpm_socclk', 'needsparse' : False},
    'clk_voltage' : {'prefix' : drmprefix, 'filepath' : 'pp_od_clk_voltage', 'needsparse' : False},
    'voltage' : {'prefix' : hwmonprefix, 'filepath' : 'in0_input', 'needsparse' : False},
    'profile' : {'prefix' : drmprefix, 'filepath' : 'pp_power_profile_mode', 'needsparse' : False},
    'use' : {'prefix' : drmprefix, 'filepath' : 'gpu_busy_percent', 'needsparse' : False},
    'use_mem' : {'prefix' : drmprefix, 'filepath' : 'mem_busy_percent', 'needsparse' : False},
    'pcie_bw' : {'prefix' : drmprefix, 'filepath' : 'pcie_bw', 'needsparse' : False},
    'replay_count' : {'prefix' : drmprefix, 'filepath' : 'pcie_replay_count', 'needsparse' : False},
    'unique_id' : {'prefix' : drmprefix, 'filepath' : 'unique_id', 'needsparse' : False},
    'vendor' : {'prefix' : drmprefix, 'filepath' : 'vendor', 'needsparse' : False},
    'sub_vendor' : {'prefix' : drmprefix, 'filepath' : 'subsystem_vendor', 'needsparse' : False},
    'fan' : {'prefix' : hwmonprefix, 'filepath' : 'pwm1', 'needsparse' : False},
    'fanmax' : {'prefix' : hwmonprefix, 'filepath' : 'pwm1_max', 'needsparse' : False},
    'fanmode' : {'prefix' : hwmonprefix, 'filepath' : 'pwm1_enable', 'needsparse' : False},
    'temp1' : {'prefix' : hwmonprefix, 'filepath' : 'temp1_input', 'needsparse' : True},
    'temp1_label' : {'prefix' : hwmonprefix, 'filepath' : 'temp1_label', 'needsparse' : False},
    'temp2' : {'prefix' : hwmonprefix, 'filepath' : 'temp2_input', 'needsparse' : True},
    'temp2_label' : {'prefix' : hwmonprefix, 'filepath' : 'temp2_label', 'needsparse' : False},
    'temp3' : {'prefix' : hwmonprefix, 'filepath' : 'temp3_input', 'needsparse' : True},
    'temp3_label' : {'prefix' : hwmonprefix, 'filepath' : 'temp3_label', 'needsparse' : False},
    'power' : {'prefix' : hwmonprefix, 'filepath' : 'power1_average', 'needsparse' : True},
    'power_cap' : {'prefix' : hwmonprefix, 'filepath' : 'power1_cap', 'needsparse' : False},
    'power_cap_max' : {'prefix' : hwmonprefix, 'filepath' : 'power1_cap_max', 'needsparse' : False},
    'power_cap_min' : {'prefix' : hwmonprefix, 'filepath' : 'power1_cap_min', 'needsparse' : False},
    'dpm_state' : {'prefix' : drmprefix, 'filepath' : 'power_dpm_state', 'needsparse' : False},
    'vram_used' : {'prefix' : drmprefix, 'filepath' : 'mem_info_vram_used', 'needsparse' : False},
    'vram_total' : {'prefix' : drmprefix, 'filepath' : 'mem_info_vram_total', 'needsparse' : False},
    'vis_vram_used' : {'prefix' : drmprefix, 'filepath' : 'mem_info_vis_vram_used', 'needsparse' : False},
    'vis_vram_total' : {'prefix' : drmprefix, 'filepath' : 'mem_info_vis_vram_total', 'needsparse' : False},
    'gtt_used' : {'prefix' : drmprefix, 'filepath' : 'mem_info_gtt_used', 'needsparse' : False},
    'gtt_total' : {'prefix' : drmprefix, 'filepath' : 'mem_info_gtt_total', 'needsparse' : False},
    'ras_gfx' : {'prefix' : drmprefix, 'filepath' : 'ras/gfx_err_count', 'needsparse' : False},
    'ras_sdma' : {'prefix' : drmprefix, 'filepath' : 'ras/sdma_err_count', 'needsparse' : False},
    'ras_umc' : {'prefix' : drmprefix, 'filepath' : 'ras/umc_err_count', 'needsparse' : False},
    'ras_features' : {'prefix' : drmprefix, 'filepath' : 'ras/features', 'needsparse' : True},
    'ras_ctrl' : {'prefix' : debugprefix, 'filepath' : 'ras/ras_ctrl', 'needsparse' : False},
    'gpu_reset' : {'prefix' : debugprefix, 'filepath' : 'amdgpu_gpu_recover', 'needsparse' : False},
    'driver' : {'prefix' : moduleprefix, 'filepath' : 'amdgpu/version', 'needsparse' : False}
}

for block in validFwBlocks:
    valuePaths['%s_fw_version' % block] = {'prefix' : drmprefix, 'filepath' : 'fw_version/%s_fw_version' % block, 'needsparse' : False}
#SMC has different formatting for its version
valuePaths['smc_fw_version']['needsparse'] = True

def getFilePath(device, key):
    """ Return the filepath for a specific device and key

    Parameters:
    device -- Device whose filepath will be returned
    key -- [$valuePaths.keys()] The sysfs path to return
    """
    if key not in valuePaths.keys():
        print('Cannot get file path for key %s' % key)
        logging.debug('Key %s not present in valuePaths map' % key)
        return None

    pathDict = valuePaths[key]
    fileValue = ''

    if pathDict['prefix'] == hwmonprefix:
        # HW Monitor values have a different path structure
        if not getHwmonFromDevice(device):
            logging.warning('GPU[%s]\t: No corresponding HW Monitor found', parseDeviceName(device))
            return None
        filePath = os.path.join(getHwmonFromDevice(device), pathDict['filepath'])
    elif pathDict['prefix'] == debugprefix:
        # Kernel DebugFS values have a different path structure
        filePath = os.path.join(pathDict['prefix'], parseDeviceName(device), pathDict['filepath'])
    elif pathDict['prefix'] == drmprefix:
        filePath = os.path.join(pathDict['prefix'], device, 'device', pathDict['filepath'])
    else:
        # Otherwise, just join the 2 fields without any parsing
        filePath = os.path.join(pathDict['prefix'], pathDict['filepath'])

    if not os.path.isfile(filePath):
        return None
    return filePath


def getSysfsValue(device, key):
    """ Return the desired SysFS value for a specified device

    Parameters:
    device -- DRM device identifier
    key -- [$valuePaths.keys()] Key referencing desired SysFS file
    """
    filePath = getFilePath(device, key)
    pathDict = valuePaths[key]

    if not filePath:
        return None
    # Use try since some sysfs files like power1_average will throw -EINVAL
    # instead of giving something useful.
    try:
        with open(filePath, 'r') as fileContents:
            fileValue = fileContents.read().rstrip('\n')
    except:
        logging.warning('GPU[%s]\t: Unable to read %s', parseDeviceName(device), filePath)
        return None

    # Some sysfs files aren't a single line of text
    if pathDict['needsparse']:
        fileValue = parseSysfsValue(key, fileValue)

    if fileValue == '':
        logging.debug('GPU[%s]\t: Empty SysFS value: %s', parseDeviceName(device), key)

    return fileValue


def parseSysfsValue(key, value):
    """ Parse the sysfs value string

    Parameters:
    key -- [$valuePaths.keys()] Key referencing desired SysFS file
    value -- SysFS value to parse

    Some SysFS files aren't a single line/string, so we need to parse it
    to get the desired value
    """
    if key == 'id':
        # Strip the 0x prefix
        return value[2:]
    if re.match(r'temp[0-9]+', key):
        # Convert from millidegrees
        return int(value) / 1000
    if key == 'power':
        # power1_average returns the value in microwatts. However, if power is not
        # available, it will return "Invalid Argument"
        if value.isdigit():
            return float(value) / 1000 / 1000
    # ras_reatures has "feature mask: 0x%x" as the first line, so get the bitfield out
    if key == 'ras_features':
        return int((value.split('\n')[0]).split(' ')[-1], 16)
    # The smc_fw_version sysfs file stores the version as a hex value like 0x12345678
    # but is parsed as int(0x12).int(0x34).int(0x56).int(0x78)
    if key == 'smc_fw_version':
        return (str('%02d' % int((value[2:4]), 16)) + '.' + str('%02d' % int((value[4:6]), 16)) + '.' +
                str('%02d' % int((value[6:8]), 16)) + '.' + str('%02d' % int((value[8:10]), 16)))

    return ''


def parseDeviceNumber(deviceNum):
    """ Parse the device number, returning the format of card#

    Parameters:
    deviceNum -- DRM device number to parse
    """
    return 'card' + str(deviceNum)


def parseDeviceName(deviceName):
    """ Parse the device name, which is of the format card#.

    Parameters:
    deviceName -- DRM device name to parse
    """
    return deviceName[4:]


def printErr(device, err):
    """ Print out an error to the SMI log

    Parameters:
    device -- DRM device identifier
    err -- Error string to print
    """
    devName = parseDeviceName(device)
    for line in err.split('\n'):
        errstr = 'GPU[%s] \t\t: %s' % (devName, line)
        logging.error(errstr)
        print(errstr)


def formatJson(device, log):
    """ Print out in JSON format

    Parameters:
    device -- DRM device identifier
    log -- String to parse and output into JSON format
    """
    global JSON_DATA
    for line in log.splitlines():
        # If we got some bad input somehow, quietly ignore it
        if ':' not in line:
            return
        logTuple = line.split(': ')
        JSON_DATA[device][logTuple[0]] = logTuple[1]


def printLog(device, log):
    """ Print out to the SMI log.

    Parameters:
    device -- DRM device identifier
    log -- String to print to the log
    """
    global PRINT_JSON
    if PRINT_JSON is True:
        formatJson(device, log)
        return

    devName = parseDeviceName(device)
    for line in log.split('\n'):
        logstr = 'GPU[%s] \t\t: %s' % (devName, line)
        logging.debug(logstr)
        print(logstr)


def printLogSpacer():
    """ A helper function to print out the log spacer

    We use this to prevent unnecessary output when printing out
    JSON data. If we want JSON, do nothing, otherwise print out
    the spacer. To keep Python2 compatibility, we don't just use
    the print(end='') option, so instead we made this helper
    """
    global PRINT_JSON
    if PRINT_JSON:
        return
    print(logSpacer)


def doesDeviceExist(device):
    """ Check whether the specified device exists in sysfs.

    Parameters:
    device -- DRM device identifier
    """
    if os.path.exists(os.path.join(drmprefix, device)) == 0:
        return False
    return True


def getPid(name):
    """ Get the process id of a specific application """
    return check_output(["pidof", name])


def confirmOutOfSpecWarning(autoRespond):
    """ Print the warning for running outside of specification and prompt user to accept the terms.

    Parameters:
    autoRespond -- Response to automatically provide for all prompts
    """

    print('''
          ******WARNING******\n
          Operating your AMD GPU outside of official AMD specifications or outside of
          factory settings, including but not limited to the conducting of overclocking,
          over-volting or under-volting (including use of this interface software,
          even if such software has been directly or indirectly provided by AMD or otherwise
          affiliated in any way with AMD), may cause damage to your AMD GPU, system components
          and/or result in system failure, as well as cause other problems.
          DAMAGES CAUSED BY USE OF YOUR AMD GPU OUTSIDE OF OFFICIAL AMD SPECIFICATIONS OR
          OUTSIDE OF FACTORY SETTINGS ARE NOT COVERED UNDER ANY AMD PRODUCT WARRANTY AND
          MAY NOT BE COVERED BY YOUR BOARD OR SYSTEM MANUFACTURER'S WARRANTY.
          Please use this utility with caution.
          ''')
    if not autoRespond:
        user_input = input('Do you accept these terms? [y/N] ')
    else:
        user_input = autoRespond
    if user_input in ['Yes', 'yes', 'y', 'Y', 'YES']:
        return
    else:
        sys.exit('Confirmation not given. Exiting without setting value')


def isDPMAvailable(device):
    """ Check if DPM is available for a specified device.

    Parameters:
    device -- DRM device identifier
    """
    if not doesDeviceExist(device) or not os.path.isfile(getFilePath(device, 'dpm_state')):
        logging.warning('GPU[%s]\t: DPM is not available', parseDeviceName(device))
        return False
    return True


def isRasControlAvailable(device):
    """ Check if RAS control is available for a specified device.

    Parameters:
    device -- DRM device identifier
    """
    path = getFilePath(device, 'ras_ctrl')
    if not doesDeviceExist(device) or not path or not os.path.isfile(path):
        logging.warning('GPU[%s]\t: RAS control is not available', parseDeviceName(device))
        return False
    return True


def getNumProfileArgs(device):
    """ Get the number of Power Profile fields for a specific device

    Parameters:
    device -- DRM device identifier

    This varies per ASIC, so ensure that we get the right number of arguments
    """

    profile = getSysfsValue(device, 'profile')
    numHiddenFields = 0
    if not profile:
        return 0
    # Get the 1st line (column names)
    fields = profile.splitlines()[0]
    # SMU7 has 2 hidden fields for SclkProfileEnable and MclkProfileEnable
    if 'SCLK_UP_HYST' in fields:
        numHiddenFields = 2
    # If there is a CLOCK_TYPE category, that requires a value as well
    if 'CLOCK_TYPE(NAME)' in fields:
        numHiddenFields = 1
    # Subtract 2 to remove NUM and MODE NAME, since they're not valid Profile fields
    return len(fields.split()) - 2 + numHiddenFields


def getBus(device):
    """ Get the PCIe bus information for a specified device

    Parameters:
    device -- DRM device identifier
    """
    bus = os.readlink(os.path.join(drmprefix, device, 'device'))
    return bus.split('/')[-1]


def verifySetProfile(device, profile):
    """ Verify data from user to set as Power Profile.

    Ensure that we can set the profile, with Profiles being supported and
    the profile being passed in being valid

    Parameters:
    device -- DRM device identifier
    """
    global RETCODE
    if not isDPMAvailable(device):
        printErr(device, 'Unable to specify profile')
        RETCODE = 1
        return False

    # If it's 1 number, we're setting the level, not the Custom Profile
    if profile.isdigit():
        maxProfileLevel = getMaxLevel(device, 'profile')
        if maxProfileLevel is None:
            printErr(device, 'Unable to set profile')
            logging.debug('GPU[%s]\t: Unable to get max level when trying to set profile', parseDeviceName(device))
            return False
        if int(profile) > maxProfileLevel:
            printErr(device, 'Unable to set profile to level' + str(profile))
            logging.debug('GPU[%s]\t: %d is an invalid level, maximum level is %d', parseDeviceName(device), profile, maxProfileLevel)
            return False
        return True
    # If we get a string, split it into elements to make it a list
    elif isinstance(profile, str):
        if profile == 'reset':
            printErr(device, 'Reset no longer accepted as a Power Profile')
            return False
        else:
            profileList = profile.strip().split(' ')
    elif isinstance(profile, collections.Iterable):
        profileList = profile
    else:
        printErr(device, 'Unsupported profile argument : ' + str(profile))
        return False
    numProfileArgs = getNumProfileArgs(device)
    if numProfileArgs == 0:
        printErr(device, 'Power Profiles not supported')
        return False
    if len(profileList) != numProfileArgs:
        printErr(device, 'Unable to set profile')
        logging.error('GPU[%s]\t: Profile must contain 1 or %d values', parseDeviceName(device), numProfileArgs)
        RETCODE = 1
        return False

    return True


def getProfile(device):
    """ Get either the current profile level, or the custom profile

    The CUSTOM profile might be set, or a specific profile level may have been selected
    Return either a single digit for a non-CUSTOM profile, or return the CUSTOM profile

    Parameters:
    device -- DRM device identifier
    """
    profiles = getSysfsValue(device, 'profile')
    custom = ''
    asic = ''
    level = ''
    numArgs = getNumProfileArgs(device)
    if numArgs == 0:
        printErr(device, 'Unable to get power profile')
        logging.debug('GPU[%s]\t: Power Profile not supported (file is empty)', parseDeviceName(device))
        return None
    for line in profiles.splitlines():
        if re.match(r'.*SCLK_UP_HYST./*', line):
            asic = 'SMU7'
            continue
        if re.match(r'.*\*.*', line):
            level = line.split()[0]
            if re.match(r'.*CUSTOM.*', line):
                # Ditch the NUM and NAME, which end with a : before the profile values
                # Then put it into single words via split
                custom = line.split(':')[1].split()
            break
    if not custom:
        return level
    # We need some special parsing for SMU7 if it's a CUSTOM profile
    if asic == 'SMU7' and custom:
        sclk = custom[0:3]
        mclk = custom[3:]
        if sclk[0] == '-':
            sclkStr = '0 0 0 0'
        else:
            sclkStr = '1 ' + ' '.join(sclk)
        if mclk[0] == '-':
            mclkStr = '0 0 0 0'
        else:
            mclkStr = '1 ' + ' '.join(mclk)
        customStr = sclkStr + ' ' + mclkStr
    else:
        customStr = ' '.join(custom[-numArgs:])
    return customStr


def writeProfileSysfs(device, value):
    """ Write to the Power Profile sysfs file

    This function is different from a regular sysfs file as it could involve
    parsing of the data first.

    Parameters:
    device -- DRM device identifier
    value -- Value to write to the Profile sysfs file
    """
    if not verifySetProfile(device, value):
        return

    # Perf Level must be set to manual for a Power Profile to be specified
    # This is new compared to previous versions of the Power Profile
    setPerfLevel(device, 'manual')
    profilePath = getFilePath(device, 'profile')
    maxLevel = getMaxLevel(device, 'profile')
    if maxLevel is None:
        printErr(device, 'Unable to set profile')
        logging.debug('GPU[%s]\t: Max profile level could not be obtained', parseDeviceName(device))
        return False
    # If it's a single number, then we're choosing the Power Profile, not setting CUSTOM
    if isinstance(value, str) and len(value) == 1:
        profileString = value
    # Otherwise, we're setting the CUSTOM profile
    elif value.isdigit():
        profileString = str(value)
    elif isinstance(value, str) and len(value) > 1:
        if maxLevel is not None:
            # Prepend the Max Level of Profiles since that will always be the CUSTOM profile
            profileString = str(maxLevel) + value
    else:
        printErr(device, 'Invalid input argument ' + value)
        return False
    if writeToSysfs(profilePath, profileString):
        return True
    return False


def writeToSysfs(fsFile, fsValue):
    """ Write to a sysfs file.

    Parameters:
    fsFile -- Path to the sysfs file to modify
    fsValue -- Value to write to the sysfs file
    """
    global RETCODE
    if not os.path.isfile(fsFile):
        print('Unable to write to sysfs file')
        logging.debug('%s does not exist', fsFile)
        return False
    try:
        logging.debug('Writing value \'%s\' to file \'%s\'', fsValue, fsFile)
        with open(fsFile, 'w') as fs:
            fs.write(fsValue + '\n') # Certain sysfs files require \n at the end
    except (IOError, OSError):
        print('Unable to write to to sysfs file ' + fsFile)
        logging.warning('IO or OS error')
        RETCODE = 1
        return False
    return True


def listDevices(showall):
    """ Return a list of GPU devices.

    Parameters:
    showall -- [True|False] Show all devices, not just AMD devices
    """

    devicelist = [device for device in os.listdir(drmprefix) if re.match(r'^card\d+$', device) and (isAmdDevice(device) or showall)]
    devicelist.sort()
    return devicelist


def listAmdHwMons():
    """Return a list of AMD HW Monitors."""
    hwmons = []

    for mon in os.listdir(hwmonprefix):
        tempname = os.path.join(hwmonprefix, mon, 'name')
        if os.path.isfile(tempname):
            with open(tempname, 'r') as tempmon:
                drivername = tempmon.read().rstrip('\n')
                if drivername in ['radeon', 'amdgpu']:
                    hwmons.append(os.path.join(hwmonprefix, mon))
    return hwmons


def getHwmonFromDevice(device):
    """ Return the corresponding HW Monitor for a specified GPU device.

    Parameters:
    device -- DRM device identifier
    """
    drmdev = os.path.realpath(os.path.join(drmprefix, device, 'device'))
    for hwmon in listAmdHwMons():
        if os.path.realpath(os.path.join(hwmon, 'device')) == drmdev:
            return hwmon
    return None


def getFanSpeed(device):
    """ Return an tuple with the fan speed (value,%) for a specified device,
    or (None,None) if either current fan speed or max fan speed cannot be
    obtained.

    Parameters:
    device -- DRM device identifier
    """

    fanLevel = getSysfsValue(device, 'fan')
    fanMax = getSysfsValue(device, 'fanmax')
    if not fanLevel or not fanMax:
        return (None, None)
    return (int(fanLevel), round((float(fanLevel) / float(fanMax)) * 100, 2))


def getCurrentClock(device, clock, clocktype):
    """ Return the current clock frequency for a specified device.

    Parameters:
    device -- DRM device identifier
    clock -- [$validClockNames] Clock to return
    clocktype -- [freq|level] Return either the clock frequency (freq) or clock level (level)
    """
    currClk = ''

    if clock in validClockNames:
        currClocks = getSysfsValue(device, clock)
    else:
        logging.error('Invalid clock type %s', clocktype)
        currClocks = None

    if not currClocks:
        return None

    # Hack: In the kernel, FCLK doesn't have an * at all if DPM is disabled.
    # If there is only 1 speed (1 line total, meaning 0 levels), just print it
    if len(currClocks.splitlines()) == 1 and len(currClocks) > 1:
        if clocktype is 'freq':
            if currClocks.find('DPM disabled'):
                logging.debug('Only 1 level for clock %s; DPM is disabled for this specific clock' % clock)
            return currClocks.split(' *')[0][3:]
        else:
            return '0'

    # Since the current clock line is of the format 'X: #Mhz *', we either want the
    # first character for level, or the 3rd-to-2nd-last characters for speed
    for line in currClocks.splitlines():
        if re.match(r'.*\*$', line):
            if clocktype == 'freq':
                currClk = line[3:-2]
            else:
                currClk = line[0]
            break
    return currClk


def getMaxLevel(device, leveltype):
    """ Return the maximum level for a specified device.

    Parameters:
    device -- DRM device identifier
    leveltype -- [$validClockNames] Return the maximum desired clock,
                 or the highest numbered Power Profiles
    """
    global RETCODE
    if not leveltype in validClockNames and leveltype != 'profile':
        printErr(device, 'Unable to get max level')
        logging.error('Invalid level type %s', leveltype)
        RETCODE = 1
        return None

    levels = getSysfsValue(device, leveltype)
    if not levels:
        return None
    # lstrip since there are leading spaces for this sysfs file, but no others
    if leveltype == 'profile':
        for line in levels.splitlines():
            if re.match(r'.*CUSTOM.*', line):
                return int(line.lstrip().split()[0])
    return int(levels.splitlines()[-1][0])


def getMemInfo(device, memType):
    """ Return the specified memory usage for the specified device

    Parameters:
    device -- DRM device identifier
    type -- [vram|vis_vram|gtt] Memory type to return
    """
    if memType not in validMemTypes:
        logging.error('Invalid memory type %s', memType)
        return (None, None)
    memUsed = getSysfsValue(device, '%s_used' % memType)
    memTotal = getSysfsValue(device, '%s_total' % memType)
    if memUsed == None:
        logging.debug('Unable to get %s_used' % memType)
    elif memTotal == None:
        logging.debug('Unable to get %s_total' % memType)
    return (memUsed, memTotal)


def getRasEnablement(device, rasType):
    """ Return RAS enablement information for the specified device

    Parameters:
    device -- DRM device identifier
    rasType -- [$validRasBlocks] RAS counter to display
    """
    # The ras/features file is a bit field of supported blocks
    rasBitfield = getSysfsValue(device, 'ras_features')
    if rasBitfield is None:
        return None
    return ('ENABLED' if rasBitfield & (1 << validRasBlocks[rasType]) else 'DISABLED')


def isAmdDevice(device):
    """ Return whether the specified device is an AMD device or not

    Parameters:
    device -- DRM device identifier
    """
    vid = getSysfsValue(device, 'vendor')
    if vid == '0x1002':
        return True
    return False


def setPerfLevel(device, level):
    """ Set the Performance Level for a specified device.

    Parameters:
    device -- DRM device identifier
    level -- Performance Level to set
    """
    global RETCODE
    validLevels = ['auto', 'low', 'high', 'manual']
    perfPath = getFilePath(device, 'perf')

    if level not in validLevels:
        printErr(device, 'Unable to set Performance Level')
        logging.error('Invalid Performance level: %s', level)
        RETCODE = 1
        return False
    if not os.path.isfile(perfPath):
        return False
    writeToSysfs(perfPath, level)
    return True


def showId(deviceList):
    """ Display the device ID for a list of devices.

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    """
    printLogSpacer()
    for device in deviceList:
        printLog(device, 'GPU ID: 0x' + getSysfsValue(device, 'id'))
    printLogSpacer()


def showVbiosVersion(deviceList):
    """ Display the VBIOS version for a list of devices.

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    """
    printLogSpacer()
    for device in deviceList:
        vbios = getSysfsValue(device, 'vbios')
        if vbios:
            printLog(device, 'VBIOS version: ' + vbios)
        else:
            printErr(device, 'Unable to get VBIOS version')
    printLogSpacer()


def showCurrentClock(deviceList, clocktype):
    """ Display the current clocktype frequency for a list of devices.

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    clocktype -- Specific type of clock to return
    """
    global RETCODE
    if clocktype not in validClockNames:
        print('Unable to display ' + clocktype)
        logging.error('GPU[%s]\t: Invalid clock type %s', clocktype)
        RETCODE = 1
        return
    for device in deviceList:
        if not isDPMAvailable(device):
            printErr(device, 'Unable to display ' + clocktype)
            continue
        if not getFilePath(device, clocktype):
            # If the clock file doesn't exist, don't print it out.
            # It may not be an error if the HW doesn't support it,
            # like fclk on Vega10 for example
            # TODO: Add a debug-level log explaining a lack of file
            continue
        clk = getCurrentClock(device, clocktype, 'freq')
        if clk:
            level = getCurrentClock(device, clocktype, 'level')

        if not clk or not level:
            printErr(device, 'Unable to display ' + clocktype)
            logging.debug('GPU[%s]\t: Clock file %s is empty. ASIC may not support it', parseDeviceName(device), clocktype)
            return

        printLog(device, clocktype + ' Clock Level: ' + str(level) + ' (' + str(clk) + ')')


def showCurrentClocks(deviceList):
    """ Display all clocks for a list of devices.

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    """
    global RETCODE
    printLogSpacer()
    for device in deviceList:
        if not isDPMAvailable(device):
            printErr(device, 'Unable to display clocks')
            continue
        for clk in validClockNames:
            showCurrentClock([device], clk)
        printLogSpacer()


def showCurrentTemps(deviceList):
    """ Display the current temperature for a list of devices.

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    """

    printLogSpacer()
    tempList = []
    tempLabelList = []
    for device in deviceList:
        # We currently have temp1/2/3, so use range(1,4)
        for x in range(1, 4):
            temp = getSysfsValue(device, 'temp%d' % x)
            tempLabel = getSysfsValue(device, 'temp%d_label' % x)
            if temp and tempLabel:
                printLog(device, 'Temperature (%s): %s c' % (tempLabel, temp))
            elif temp:
                printLog(device, 'Temperature (Sensor #%d): %s c' % (x, temp))
    printLogSpacer()


def showCurrentFans(deviceList):
    """ Display the current fan speed for a list of devices.

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    """
    printLogSpacer()
    for device in deviceList:
        (fanLevel, fanSpeed) = getFanSpeed(device)
        if not fanLevel or not fanSpeed:
            printErr(device, 'Unable to display current fan speed')
            continue
        printLog(device, 'Fan Level: %d (%d%%)' % (fanLevel, fanSpeed))
    printLogSpacer()


def showClocks(deviceList):
    """ Display current GPU and GPU Memory clock frequencies for a list of devices.

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    """
    printLogSpacer()
    for device in deviceList:
        if not isDPMAvailable(device):
            printErr(device, 'Unable to display clocks')
            continue
        for clk in validClockNames:
            clkPath = getFilePath(device, clk)
            if not clkPath or not os.path.isfile(clkPath):
                continue
            with open(clkPath, 'r') as clkFile:
                clkLog = 'Supported ' + clk + ' frequencies on GPU' + parseDeviceName(device) + '\n' + clkFile.read()
            printLog(device, clkLog)
    printLogSpacer()


def showPowerPlayTable(deviceList):
    """ Display current GPU and GPU Memory clock frequencies and voltages for a list of devices.

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    """
    printLogSpacer()
    for device in deviceList:
        if not isDPMAvailable(device):
            printErr(device, 'Unable to display PowerPlay table')
            continue
        table = getSysfsValue(device, 'clk_voltage')
        if not table:
            printErr(device, 'Unable to display PowerPlay table')
            logging.debug('GPU[%s]\t: clk_voltage is empty', parseDeviceName(device))
            continue
        printLog(device, table)
    printLogSpacer()


def showPerformanceLevel(deviceList):
    """ Display current Performance Level for a list of devices.

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    """
    printLogSpacer()
    for device in deviceList:
        level = getSysfsValue(device, 'perf')
        if not level:
            printErr(device, 'Unable to get Performance Level')
            logging.debug('GPU[%s]\t: Performance Level not supported (file is empty)', parseDeviceName(device))
        else:
            printLog(device, 'Current Performance Level: ' + level)
    printLogSpacer()


def showOverDrive(deviceList, odtype):
    """ Display current OverDrive level for a list of devices.

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    odtype -- [sclk|mclk] OverDrive type
    """

    printLogSpacer()
    for device in deviceList:
        if odtype == 'sclk':
            od = getSysfsValue(device, 'sclk_od')
            odStr = 'GPU'
        elif odtype == 'mclk':
            od = getSysfsValue(device, 'mclk_od')
            odStr = 'GPU Memory'
        if not od or int(od) < 0:
            printErr(device, 'Unable to get ' + odStr + ' OverDrive value')
            logging.debug('GPU[%s]\t: %s OverDrive not supported', odStr)
        else:
            printLog(device, 'Current ' + odStr + ' OverDrive value: ' + str(od) + '%')
    printLogSpacer()


def showProfile(deviceList):
    """ Display available Power Profiles for a list of devices.

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    """
    printLogSpacer()
    for device in deviceList:
        if not isDPMAvailable(device):
            printErr(device, 'Power Profiles not supported')
            continue
        profile = getSysfsValue(device, 'profile')
        if not profile:
            printErr(device, 'Unable to get Power Profile')
            logging.debug('GPU[%s]\t: Power Profile not supported (file is empty)', parseDeviceName(device))
            continue
        if len(profile) > 1:
            printLog(device, '\n' + profile)
        else:
            printErr(device, 'Unable to get Power Profile')
            logging.debug('GPU[%s]\t: Invalid return value from Power Profile SysFS file', parseDeviceName(device))
    printLogSpacer()


def showPower(deviceList):
    """ Display current Average Graphics Package Power Consumption for a list of devices.

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    """
    printLogSpacer()
    try:
        getPid("atitool")
        logging.error('Please terminate ATItool to use this functionality')
    except subprocess.CalledProcessError:
        for device in deviceList:
            power = getSysfsValue(device, 'power')
            if not power:
                printErr(device, 'Unable to get Average Graphics Package Power Consumption')
                logging.debug('GPU[%s]\t: Average GPU Power not supported', parseDeviceName(device))
            else:
                printLog(device, 'Average Graphics Package Power: ' + str(power) + 'W')
    printLogSpacer()


def showMaxPower(deviceList):
    """ Display the maximum Graphics Package Power that this GPU will attempt to consume
    before it begins throttling performance.

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    """
    printLogSpacer()
    for device in deviceList:
        power_cap = getSysfsValue(device, 'power_cap')
        if not power_cap:
            printErr(device, 'Unable to get maximum Graphics Package Power')
        else:
            power_cap = str(int(getSysfsValue(device, 'power_cap')) / 1000000)
            printLog(device, 'Max Graphics Package Power: ' + power_cap + 'W')
    printLogSpacer()


def showGpuUse(deviceList):
    """ Display GPU use for a list of devices.

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    """
    printLogSpacer()
    for device in deviceList:
        use = getSysfsValue(device, 'use')
        if use == None:
            printErr(device, 'Unable to get GPU use.')
            logging.debug('GPU[%s]\t: GPU usage not supported (file is empty)', parseDeviceName(device))
        else:
            printLog(device, 'Current GPU use: ' + use + '%')
    printLogSpacer()


def showMemUse(deviceList):
    """ Display GPU memory usage for a list of devices.

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    """
    printLogSpacer()
    for device in deviceList:
        memoryUse = getSysfsValue(device, 'use_mem')
        if memoryUse == None:
            printErr(device, 'Unable to get GPU memory use.')
            logging.debug('GPU[%s]\t: GPU memory usage not supported (file is empty)', parseDeviceName(device))
        else:
            printLog(device, 'Current GPU memory use: ' + memoryUse + '%')
    printLogSpacer()


def showPcieBw(deviceList):
    """ Display estimated PCIe bandwidth usage for a list of devices.

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    """
    printLogSpacer()
    for device in deviceList:
        fsvals = getSysfsValue(device, 'pcie_bw')
        if fsvals == None:
            printErr(device, 'Unable to get PCIe bandwidth')
            logging.debug('GPU[%s]\t: PCIe bandwidth not supported (file is empty)', parseDeviceName(device))
        else:
            # The sysfs file returns 3 integers: bytes-received, bytes-sent, maxsize
            # Multiply the number of packets by the maxsize to estimate the PCIe usage
            received = int(fsvals.split()[0])
            sent = int(fsvals.split()[1])
            mps = int(fsvals.split()[2])

            # Use 1024.0 to ensure that the result is a float and not integer division
            bw = ((received + sent) * mps) / 1024.0 / 1024.0
            # Use the bwstr below to control precision on the string
            bwstr = '%.3f' % bw

            printLog(device, 'Estimated maximum PCIe bandwidth over the last second: ' + bwstr + ' MB/s')
    printLogSpacer()


def showPcieReplayCount(deviceList):
    """ Display number of PCIe replays for a list of devices.

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    """
    printLogSpacer()
    for device in deviceList:
        count = getSysfsValue(device, 'replay_count')
        if count == None:
            printErr(device, 'Unable to get PCIe replay count')
            logging.debug('GPU[%s]\t: File is empty. Likely a kernel bug', parseDeviceName(device))
        else:
            printLog(device, 'PCIe Replay Count: %s' % count)
    printLogSpacer()


def showUniqueId(deviceList):
    """ Display Unique ID for a list of devices.

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    """
    printLogSpacer()
    for device in deviceList:
        uid = getSysfsValue(device, 'unique_id')
        if uid:
            printLog(device, 'Unique ID: %s' % uid)
        else:
            printLog(device, 'Unique ID: N/A')
            # Not supported on GFX8-or-older, so debug-log if we don't find a UID, just in case
            logging.debug('GPU[%s]\t: NOTE: Unique ID is only supported on GFX9 and later', parseDeviceName(device))
    printLogSpacer()


def showMemInfo(deviceList, memType):
    """ Display Memory information for a list of devices

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    memType -- [$validMemTypes] Type of memory information to display
    """
    # Python will pass in a list of values as a single-value list.
    # If we get 'all' as the string, just set the list to all supported types
    # Otherwise, split the single-item list by space, then split each element
    # up to process it below
    if 'all' in memType:
        returnTypes = validMemTypes
    else:
        returnTypes = memType

    printLogSpacer()
    for device in deviceList:
        for mem in returnTypes:
            memInfo = getMemInfo(device, mem)
            if memInfo[0]  == None or memInfo[1] == None:
                printErr(device, 'Unable to get %s memory usage information' % mem)
            else:
                printLog(device, '%s ::\ttotal: %s B   \tused: %s B' % (mem, memInfo[1], memInfo[0]))
    printLogSpacer()


def showVoltage(deviceList):
    """ Display the current voltage (in millivolts) for a list of devices.

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    """

    printLogSpacer()
    for device in deviceList:
        voltage = getSysfsValue(device, 'voltage')
        if not voltage:
            printErr(device, 'Unable to display voltage')
            continue
        printLog(device, 'Voltage: %s mV' % str(voltage))
    printLogSpacer()


def showVersion(deviceList, component):
    """ Show the software version for the specified component

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    component - Component (currently only driver)
    """
    if component not in validVersionComponents:
        printLog(device, 'Unable to display version information for unsupported component %s' % component)
        return
    if component is 'driver':
        # Only 1 version, so report it for GPU 0
        driver = getSysfsValue(None, 'driver')
        if driver is None:
            driver = os.uname()[2]
        print('%s version: %s' % (component.capitalize(), driver))


def showAllConciseHw(deviceList):
    """ Display critical Hardware info for all devices in a concise format.

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    """
    printLogSpacer()
    header = ['GPU', 'DID', 'GFX RAS', 'SDMA RAS', 'UMC RAS', 'VBIOS', 'BUS']
    head_widths = [len(head)+2 for head in header]
    values = {}
    for device in deviceList:
        gpuid = getSysfsValue(device, 'id')

        gfxRas = getRasEnablement(device, 'gfx')
        sdmaRas = getRasEnablement(device, 'sdma')
        umcRas = getRasEnablement(device, 'umc')
        gfxRas = 'N/A' if gfxRas is None else gfxRas
        sdmaRas = 'N/A' if sdmaRas is None else sdmaRas
        umcRas = 'N/A' if umcRas is None else umcRas
        vbios = getSysfsValue(device, 'vbios')
        bus = getBus(device)

        values[device] = [device[4:], gpuid, gfxRas, sdmaRas, umcRas, vbios, bus]
    val_widths = {}
    for device in deviceList:
        val_widths[device] = [len(val)+2 for val in values[device]]
    max_widths = head_widths
    for device in deviceList:
        for col in range(len(val_widths[device])):
            max_widths[col] = max(max_widths[col], val_widths[device][col])
    print("".join(word.ljust(max_widths[col]) for col,word in zip(range(len(max_widths)),header)))
    for device in deviceList:
        print("".join(word.ljust(max_widths[col]) for col,word in zip(range(len(max_widths)),values[device])))


def showAllConcise(deviceList):
    """ Display critical info for all devices in a concise format.

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    """
    printLogSpacer()
    header = ['GPU', 'Temp', 'AvgPwr', 'SCLK', 'MCLK', 'Fan', 'Perf', 'PwrCap', 'VRAM%', 'GPU%']
    head_widths = [len(head)+2 for head in header]
    values = {}
    for device in deviceList:
        # Default to temp1, it's always there
        temp = getSysfsValue(device, 'temp1')
        for x in range(1, 4):
            # But report 'edge' if the ASIC supports it
            tempLabel = getSysfsValue(device, 'temp%d_label' % x)
            if tempLabel == 'edge':
                temp = getSysfsValue(device, 'temp%d' % x)
                break
        if not temp:
            temp = 'N/A'
        else:
            temp = str(temp) + 'c'

        power = getSysfsValue(device, 'power')
        if not power:
            power = 'N/A'
        else:
            power = str(power) + 'W'

        sclk = getCurrentClock(device, 'sclk', 'freq')
        if not sclk:
            sclk = 'N/A'

        mclk = getCurrentClock(device, 'mclk', 'freq')
        if not mclk:
            mclk = 'N/A'

        fan = str(getFanSpeed(device)[1])
        if not fan:
            fan = 'N/A'
        else:
            fan = fan + '%'

        perf = getSysfsValue(device, 'perf')
        if not perf:
            perf = 'N/A'

        power_cap = getSysfsValue(device, 'power_cap')
        if not power_cap:
            power_cap = 'N/A'
        else:
            power_cap = str(int(power_cap)/1000000) + 'W'

        memInfo = getMemInfo(device, 'vram')
        if memInfo[0]  == None or memInfo[1] == None:
            mem_use = 'N/A'
        else:
            mem_use = '% 3.0f%%' % (100*(float(memInfo[0])/float(memInfo[1])))

        gpu_use = getSysfsValue(device, 'use')
        if gpu_use == None:
            gpu_use = 'N/A'
        else:
            gpu_use = gpu_use + '%'

        values[device] = [device[4:], temp, power, sclk, mclk, fan, perf, power_cap, mem_use, gpu_use]
    val_widths = {}
    for device in deviceList:
        val_widths[device] = [len(val)+2 for val in values[device]]
    max_widths = head_widths
    for device in deviceList:
        for col in range(len(val_widths[device])):
            max_widths[col] = max(max_widths[col], val_widths[device][col])
    print("".join(word.ljust(max_widths[col]) for col,word in zip(range(len(max_widths)),header)))
    for device in deviceList:
        print("".join(word.ljust(max_widths[col]) for col,word in zip(range(len(max_widths)),values[device])))
    printLogSpacer()


def showRasInfo(deviceList, rasType):
    """ Show the requested RAS information for a list of devices

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    rasType -- [$validRasBlocks] RAS counter to display (all if left empty)
    """
    if 'all' in rasType:
        returnTypes = validRasBlocks.keys()
    else:
        returnTypes = rasType

    printLogSpacer()
    for device in deviceList:
        for ras in returnTypes:
            if ras not in validRasBlocks.keys():
                print('Unable to get %s RAS information' % rasType)
                logging.debug('Invalid RAS block %s' % rasType)
                continue
            rasEnabled = getRasEnablement(device, ras)
            if rasEnabled is None:
                printErr(device, 'Unable to get information for block %s' % ras)
                logging.debug('GPU[%s]\t: RAS not supported for block %s', parseDeviceName(device), rasType)
            else:
                printLog(device, 'Block %s is: %s' % (ras, rasEnabled))
                if rasEnabled == 'ENABLED':
                    # Now print the error count
                    printLog(device, getSysfsValue(device, 'ras_%s' % ras))
    printLogSpacer()

def showFwInfo(deviceList, fwType):
    """ Show the requested FW information for a list of devices

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    fwType -- [$validFwBlocks] FW block version to display (all if left empty)
    """
    if not fwType or 'all' in fwType:
        returnTypes = sorted(validFwBlocks)
    else:
        returnTypes = fwType
    printLogSpacer()
    for device in deviceList:
        for block in returnTypes:
            fwLogName = block.replace('_', ' ').upper()
            blockFile = '%s_fw_version' % block
            version = getSysfsValue(device, blockFile)
            if version:
                if valuePaths[blockFile]['needsparse']:
                    printLog(device, '%s firmware version:  \t%s' % (fwLogName,
                             getSysfsValue(device, blockFile)))
                else:
                    # PSP, UVD, VCE and VCN report their FW in hex
                    if block in ['ta_ras', 'ta_xgmi', 'uvd', 'vce', 'vcn']:
                        printLog(device, '%s firmware version:  \t%s' % (fwLogName,
                                 getSysfsValue(device, blockFile)))
                    else:
                        printLog(device, '%s firmware version:  \t%i' % (fwLogName,
                                 int(getSysfsValue(device, blockFile), 16)))
            else:
                print('Unable to get %s_fw_version sysfs file.' % block)
    printLogSpacer()


def showProductName(deviceList):
    """ Show the requested product name for a list of devices

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    """
    printLogSpacer()
    fileString = ''
    pciLines = ''
    pciFilePath = '/usr/share/misc/pci.ids'
    # If the pci.ids file is found in hwdata, switch to that path
    if os.path.isfile('/usr/share/hwdata/pci.ids'):
        pciFilePath = '/usr/share/hwdata/pci.ids'
    try:
        with open (pciFilePath, 'rt') as pciFile:
            fileString = pciFile.read()
        # pciLines stores all AMD GPU names (from 1002 to 1003 in pci.ids file)
        pciLines = fileString.split('\n1002')[1].split('\n1003')[0]
    except:
        print('Unable to locate pci.ids file')
    # Fetch required sysfs files for product name and store them
    for device in deviceList:
        vendor = getSysfsValue(device, 'vendor')
        if vendor and len(vendor) > 2:
            vendor = vendor[2:]
            # Check if the device vendor is 1002, which is AMD's number in pci.ids
            if vendor == '1002':
                vbios = getSysfsValue(device, 'vbios')
                if not vbios:
                    printErr(device, 'Unable to get the SKU')
                    continue
                device_id = getSysfsValue(device, 'id')
                if not device_id:
                    printErr(device, 'Unable to get device id')
                    continue
                sub_id = getSysfsValue(device, 'sub_id')
                if sub_id:
                    sub_id = sub_id[2:]
                else:
                    printErr(device, 'Unable to get subsystem_device')
                sub_vendor = getSysfsValue(device, 'sub_vendor')
                if sub_vendor:
                    sub_vendor = sub_vendor[2:]
                else:
                    printErr(device, 'Unable to get subsystem_vendor')
                if len(pciLines) > 0 and len(fileString) > 0:
                    # Check if the device ID exists in pciLines before attempting to print
                    if pciLines.find('\n\t%s' % device_id) != -1:
                        # variants gets a sublist of all devices in a specific GPU series
                        variants = re.split(r'\n\t[a-z0-9]',\
                                            pciLines.split('\n\t%s' % device_id)[1])[0]
                        series = variants.split('\n', 1)[0].strip()
                        printLog(device, 'Card series:\t\t%s' % series)
                        if variants.find('%s %s' % (sub_vendor, sub_id)) != -1:
                            model = variants.split(sub_id, 1)[1].split('\n', 1)[0].strip()
                            printLog(device, 'Card model:\t\t%s' % model)
                        else:
                            logging.debug('Subsystem device information not found. \
                                          Run update-pciids and try again')
                    else:
                        printErr(device, 'Unable to find device ID in PCI IDs file')
                    # Check if sub_vendor ID exists in the file before attempting to print
                    if fileString.find('\n' + sub_vendor + '  ') != -1:
                        vendorName = re.split(r'\n\t[a-z0-9]', \
                                              fileString.split('\n%s' % sub_vendor)[1])[0].strip()
                        printLog(device, 'Card vendor:\t\t%s' % vendorName)
                    else:
                        printErr(device, 'Unable to find device vendor in PCI IDs file')
                # sku is just 6 characters after the first occurance of '-' in vbios_version
                sku = vbios.split('-')[1][:6]
                printLog(device, 'Card SKU:\t\t%s' % sku)
            else:
                printErr(device, 'PCI device is not an AMD device (%s instead of 1002)' % vendor)
        else:
            printErr(device, 'Unable to get device vendor')

    printLogSpacer()


def showPids():
    """Show PIDs created in a KFD (Compute) context
    """

    pidPath = os.path.join(kfdprefix, 'proc')
    pidsStr = ''
    maxPidLen = 8
    if os.path.isdir(pidPath):
        pids = os.listdir(pidPath)
    else:
        return None
    # Get the max size of PIDs, then divide the length of that by 80
    # so that we can space things out nicely and stay <80chars
    if os.path.isfile('/proc/sys/kernel/pid_max'):
        with open('/proc/sys/kernel/pid_max', 'r') as pidFile:
            maxPidLen = len(pidFile.read().strip())
    else:
        print('Unable to open pid_max file. Using 8 as max PID length')
    # Add 1 to accommodate the space between PIDs
    maxPidLen += 1
    # // is integer division, which truncates/rounds down
    pidsPerLine = 80 // maxPidLen

    # Add one since // truncates, and we want to round up without
    # having to import the math lib just for ceil
    for x in range(0, (len(pids) // pidsPerLine) + 1):
        pidsStr += '\n'
        pidsStr += ' '.join(pids[pidsPerLine * x:(pidsPerLine * x) + pidsPerLine])
    print('PIDs for KFD processes:%s' % pidsStr)


def setPerformanceLevel(deviceList, level):
    """ Set the Performance Level for a list of devices.

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    level -- Specific Performance Level to set
    """
    printLogSpacer()
    for device in deviceList:
        if setPerfLevel(device, level):
            printLog(device, 'Successfully set current Performance Level to ' + level)
        else:
            printErr(device, 'Unable to set current Performance Level to ' + level)
    printLogSpacer()


def setClocks(deviceList, clktype, clk):
    """ Set clock frequency level for a list of devices.

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    clktype -- [validClockNames] Clock type to set
    clk -- Clock frequency level to set
    """
    global RETCODE
    if not clk:
        print('Invalid clock frequency')
        RETCODE = 1
        return
    check_value = ''.join(map(str, clk))
    value = ' '.join(map(str, clk))
    try:
        int(check_value)
    except ValueError:
        print('Unable to set Clock level')
        logging.error('Non-integer characters are present in value %s', value)
        RETCODE = 1
        return
    for device in deviceList:
        if not isDPMAvailable(device):
            printErr(device, 'Unable to set clock level')
            RETCODE = 1
            continue
        if clktype not in validClockNames:
            printErr(device, 'Unable to set clock level')
            logging.error('Invalid clock type %s', clktype)
            RETCODE = 1
            return

        # If maxLevel is empty, it means that the sysfs file is empty, so quit
        # But 0 is a max level option, so use "is None" instead of "not maxLevel"
        maxLevel = getMaxLevel(device, clktype)
        if maxLevel is None:
            printErr(device, 'Unable to set clock level')
            logging.warning('GPU[%s]\t: Unable to get max level for clock type %s', parseDeviceName(device), clktype)
            RETCODE = 1
            continue
        # GPU clocks can be set to multiple levels at the same time (of the format
        # 4 5 6 for levels 4, 5 and 6). Don't compare against the max level for gpu
        # clocks in this case
        if any(int(item) > getMaxLevel(device, clktype) for item in clk):
            printErr(device, 'Unable to set clock level')
            logging.error('GPU[%s]\t: Max clock level is %d', parseDeviceName(device), getMaxLevel(device, clktype))
            RETCODE = 1
            continue
        setPerfLevel(device, 'manual')
        if writeToSysfs(getFilePath(device, clktype), value):
            printLog(device, 'Successfully set ' + clktype + ' frequency mask to Level ' + value)
        else:
            printErr(device, 'Unable to set ' + clktype + ' clock to Level ' + value)
            RETCODE = 1


def setPowerPlayTableLevel(deviceList, clktype, levelList, autoRespond):
    """ Set clock frequency and voltage for a level in the PowerPlay table for a list of devices.

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    clktype -- [sclk|mclk] Clock type to set
    levelList -- Clock frequency level to set
    autoRespond -- Response to automatically provide for all prompts
    """
    global RETCODE
    if not levelList:
        print('Invalid clock state')
        RETCODE = 1
        return
    value = ' '.join(map(str, levelList))
    try:
        all(int(item) for item in levelList)
    except ValueError:
        print('Unable to set PowerPlay table level')
        logging.error('Non-integer characters are present in %s', levelList)
        RETCODE = 1
        return
    if clktype == 'sclk':
        value = 's ' + value
    else:
        value = 'm ' + value
    for device in deviceList:
        if not isDPMAvailable(device):
            printErr(device, 'Unable to set voltages')
            RETCODE = 1
            continue
        clkFile = getFilePath(device, 'clk_voltage')

        confirmOutOfSpecWarning(autoRespond)

        maxLevel = getMaxLevel(device, clktype)
        if maxLevel is None:
            printErr(device, 'Unable to set clock level')
            logging.warning('GPU[%s]\t: Unable to get maximum %s level', parseDeviceName(device), clktype)
            RETCODE = 1
            continue
        if int(levelList[0]) > maxLevel:
            printErr(device, 'Unable to set clock level')
            logging.error('GPU[%s]\t: %s is greater than maximum level %s ', parseDeviceName(device), levelList[0], getMaxLevel(device, clktype))
            RETCODE = 1
            continue
        setPerfLevel(device, 'manual')
        if writeToSysfs(clkFile, value) and writeToSysfs(clkFile, 'c'):
            if clktype == 'sclk':
                printLog(device, 'Successfully set GPU Clock frequency mask to Level ' + value)
            else:
                printLog(device, 'Successfully set GPU Memory Clock frequency mask to Level ' + value)
        else:
            printErr(device, 'Unable to set ' + clktype + ' clock to Level ' + value)
            RETCODE = 1


def setClockOverDrive(deviceList, clktype, value, autoRespond):
    """ Set clock speed to OverDrive for a list of devices

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    type -- [sclk|mclk] Clock type to set
    value -- [0-20] OverDrive percentage
    autoRespond -- Response to automatically provide for all prompts
    """
    global RETCODE
    try:
        int(value)
    except ValueError:
        print('Unable to set OverDrive level')
        logging.error('%s it is not an integer', value)
        RETCODE = 1
        return
    logging.error('NOTE: GPU and MEM Overdrive have been deprecated in the kernel. Use --setslevel/--setmlevel instead')
    confirmOutOfSpecWarning(autoRespond)

    for device in deviceList:
        if not isDPMAvailable(device):
            printErr(device, 'Unable to set OverDrive')
            continue
        if clktype == 'sclk':
            odPath = getFilePath(device, 'sclk_od')
            odStr = 'GPU'
        elif clktype == 'mclk':
            odPath = getFilePath(device, 'mclk_od')
            odStr = 'GPU Memory'
        else:
            printErr(device, 'Unable to set OverDrive')
            logging.error('Unsupported clock type %s', clktype)
            RETCODE = 1
            continue

        if int(value) < 0:
            printErr(device, 'Unable to set OverDrive')
            logging.debug('Overdrive cannot be less than 0%')
            RETCODE = 1
            return

        if int(value) > 20:
            printLog(device, 'Setting OverDrive to 20%')
            logging.debug('OverDrive cannot be set to a value greater than 20%')
            value = '20'

        if writeToSysfs(odPath, value):
            printLog(device, 'Successfully set ' + odStr + ' OverDrive to ' + value + '%')
            setClocks([device], clktype, [getMaxLevel(device, clktype)])
        else:
            printErr(device, 'Unable to set OverDrive to ' + value + '%')

def setPowerOverDrive(deviceList, value, autoRespond):
    """ Use Power OverDrive to change the the maximum power available power
    available to the GPU in Watts. May be limited by the maximum power the
    VBIOS is configured to allow this card to use in OverDrive mode.

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    value -- New maximum power to assign to the target device, in Watts
    autoRespond -- Response to automatically provide for all prompts
    """
    global RETCODE
    try:
        int(value)
    except ValueError:
        print('Unable to set Power OverDrive')
        logging.error('%s it is not an integer', value)
        RETCODE = 1
        return

    confirmOutOfSpecWarning(autoRespond)

    # Value in Watt - stored early this way to avoid pythons float -> int -> str conversion after dividing a number
    strValue = value
    # Our Watt value converted for sysfs as microWatt
    value = int(value) * 1000000

    for device in deviceList:
        if not isDPMAvailable(device):
            printErr(device, 'Unable to set Power OverDrive')
            continue
        power_cap_path = getFilePath(device, 'power_cap')

        # Avoid early unnecessary conversions
        max_power_cap = int(getSysfsValue(device, 'power_cap_max'))
        min_power_cap = int(getSysfsValue(device, 'power_cap_min'))

        if value < min_power_cap:
            printErr(device, 'Unable to set Power OverDrive')
            logging.error('GPU[%s]\t: Value cannot be less than %dW ', parseDeviceName(device), min_power_cap / 1000000)
            RETCODE = 1
            return

        if value > max_power_cap:
            printErr(device, 'Unable to set Power OverDrive')
            logging.error('GPU[%s]\t: Value cannot be greater than %dW ', parseDeviceName(name), max_power_cap / 1000000)
            RETCODE = 1
            return;

        if writeToSysfs(power_cap_path, str(value)):
            if value != 0:
                printLog(device, 'Successfully set Power OverDrive to ' + strValue + 'W')
            else:
                printLog(device, 'Successfully reset Power OverDrive')
        else:
            if value != 0:
                printErr(device, 'Unable to set Power OverDrive to ' + strValue + 'W')
            else:
                printErr(device, 'Unable to reset Power OverDrive to default')

def resetPowerOverDrive(deviceList, autoRespond):
    """ Reset Power OverDrive to the default power limit that comes with the GPU

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    """
    setPowerOverDrive(deviceList, 0, autoRespond)

def resetFans(deviceList):
    """ Reset fans to driver control for a list of devices.

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    """
    for device in deviceList:
        if not isDPMAvailable(device):
            printErr(device, 'Unable to reset fan speed')
            continue
        fanpath = getFilePath(device, 'fanmode')
        if writeToSysfs(fanpath, '2'):
            printLog(device, 'Successfully reset fan speed to driver control')
        else:
            printErr(device, 'Unable to reset fan speed to driver control')


def setFanSpeed(deviceList, fan):
    """ Set fan speed for a list of devices.

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    level -- [0-255] Fan speed level
    """
    global RETCODE
    for device in deviceList:
        if not isDPMAvailable(device):
            printErr(device, 'Unable to set fan speed')
            RETCODE = 1
            continue
        fanpath = getFilePath(device, 'fan')
        modepath = getFilePath(device, 'fanmode')
        maxfan = getSysfsValue(device, 'fanmax')
        if not maxfan:
            printErr(device, 'Unable to set fan speed')
            logging.warning('GPU[%s]\t: Unable to get max fan level (file is empty)')
            RETCODE = 1
            continue
        if str(fan).endswith('%'):
            fanpct = int(fan[:-1])
            if fanpct > 100 or fanpct < 0:
                printErr(device, 'Unable to set fan speed')
                logging.error('GPU[%s]\t: Invalid fan percentage, %d is not between 0 and 100', parseDeviceName(device), fan)
                RETCODE = 1
                continue
            fan = str(int((fanpct * int(maxfan)) / 100))
        if int(fan) > int(maxfan):
            printErr(device, 'Unable to set fan speed')
            logging.error('GPU[%s]\t: Fan value %s is greater than maximum level %s', parseDeviceName(device), fan, maxfan)
            RETCODE = 1
            continue
        if getSysfsValue(device, 'fanmode') != '1':
            if writeToSysfs(modepath, '1'):
                printLog(device, 'Successfully set fan control to \'manual\'')
            else:
                printErr(device, 'Unable to set fan control to \'manual\'')
                continue
        if writeToSysfs(fanpath, str(fan)):
            printLog(device, 'Successfully set fan speed to Level ' + str(fan))
        else:
            printErr(device, 'Unable to set fan speed to Level ' + str(fan))


def setProfile(deviceList, profile):
    """ Set Power Profile, or set CUSTOM Power Profile values for a list of devices.

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    profile -- Profile to set
    """
    if len(profile) == 1:
        execMsg = 'Power Profile to level ' + profile
    else:
        execMsg = 'CUSTOM Power Profile values'
    for device in deviceList:
        if writeProfileSysfs(device, profile):
            printLog(device, 'Successfully set ' + execMsg)
        else:
            printErr(device, 'Unable to set ' + execMsg)


def resetProfile(deviceList):
    """ Reset profile for a list of a devices.

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    """
    for device in deviceList:
        if not getSysfsValue(device, 'profile'):
            printErr(device, 'Unable to reset Power Profile')
            logging.debug('GPU[%s]\t: Unable to get current Power Profile', parseDeviceName(device))
            continue
        # Performance level must be set to manual for a reset of the profile to work
        setPerfLevel(device, 'manual')
        if not writeProfileSysfs(device, '0 ' * getNumProfileArgs(device)):
            printErr(device, 'Unable to reset CUSTOM Power Profile values')
        if writeProfileSysfs(device, '0'):
            printLog(device, 'Successfully reset Power Profile')
        else:
            printErr(device, 'Unable to reset Power Profile')
        setPerfLevel(device, 'auto')


def resetOverDrive(deviceList):
    """ Reset OverDrive to 0 if needed. We check first as setting OD requires sudo

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    """
    for device in deviceList:
        odpath = getFilePath(device, 'sclk_od')
        odclkpath = getFilePath(device, 'clk_voltage')
        if not odpath or not os.path.isfile(odpath):
            printErr(device, 'Unable to reset OverDrive')
            logging.debug('GPU[%s]\t: OverDrive not available', parseDeviceName(device))
            continue
        od = getSysfsValue(device, 'sclk_od')
        if not od or int(od) != 0:
            if not writeToSysfs(odpath, '0'):
                printErr(device, 'Unable to reset OverDrive')
                continue
        printLog(device, 'OverDrive set to 0')
        if odclkpath and os.path.isfile(odclkpath):
            if writeToSysfs(odclkpath, 'r') and writeToSysfs(odclkpath, 'c'):
                printLog(device, 'Reset OverDrive DPM table')


def resetClocks(deviceList):
    """ Reset clocks to default

    Reset clocks to default values by setting performance level to auto, as well
    as setting OverDrive back to 0


    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    """
    for device in deviceList:
        resetOverDrive([device])
        setPerfLevel(device, 'auto')

        od = getSysfsValue(device, 'sclk_od')
        perf = getSysfsValue(device, 'perf')

        if not perf or not od or perf != 'auto' or od != '0':
            printErr(device, 'Unable to reset clocks')
        else:
            printLog(device, 'Successfully reset clocks')


def resetGpu(device):
    """ Perform a GPU reset on the specified device

    Parameters:
    device -- DRM Device identifier
    """
    global RETCODE
    if isinstance(device, list) and len(device) > 1:
        # This is primarily to prevent people using the GPU reset on all
        # GPUs by mistake, since it's rare that more than one GPU is hanging
        # at the same time.
        logging.error('GPU Reset can only be performed on one GPU per call')
        RETCODE = 1
        return
    # We don't capture the value because 'cat gpu_reset' just resets the
    # GPU without returning anything. Also pass device[0] since the device
    # passed in by argparse is a single-item list: ['cardX']
    getSysfsValue(device[0], 'gpu_reset')
    printLog(device[0], 'GPU reset was successful')


def setRas(deviceList, rasAction, rasBlock, rasType):
    """ Perform a RAS action on the devices

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    rasAction -- [enable|disable|inject] RAS Action to perform
    rasBlock -- [$validRasBlocks] RAS block
    rasType -- [ce|ue] Error type to enable/disable
    """
    if rasAction not in validRasActions:
        print('Unable to perform RAS command %s on block %s for type %s' % (rasAction, rasBlock, rasType))
        logging.debug('Action %s is not a valid RAS command' % rasAction)
        return
    if rasBlock not in validRasBlocks.keys():
        print('Unable to perform RAS command %s on block %s for type %s' % (rasAction, rasBlock, rasType))
        logging.debug('Block %s is not a valid RAS block' % rasBlock)
        return
    if rasType not in validRasTypes:
        print('Unable to perform RAS command %s on block %s for type %s' % (rasAction, rasBlock, rasType))
        logging.debug('Memory error type %s is not a valid RAS memory type' % rasAction)
        return
    printLogSpacer()
    #NOTE PSP FW doesn't support enabling disabled counters yet
    for device in deviceList:
        if isRasControlAvailable(device):
            rasPath = getFilePath(device, 'ras_ctrl')
            rasCmd = '%s %s %s' % (rasAction, rasBlock, rasType)
            writeToSysfs(rasPath, rasCmd)
    printLogSpacer()
    return


def load(savefilepath, autoRespond):
    """ Load clock frequencies and fan speeds from a specified file.

    Parameters:
    savefilepath -- Path to the save file
    autoRespond -- Response to automatically provide for all prompts
    """

    if not os.path.isfile(savefilepath):
        print('No settings file found at ', savefilepath)
        sys.exit()
    with open(savefilepath, 'r') as savefile:
        jsonData = json.loads(savefile.read())
        for (device, values) in jsonData.items():
            if values['vJson'] != CLOCK_JSON_VERSION:
                print('Unable to load legacy clock file - file v' + str(values['vJson']) +
                      ' != current v' + str(CLOCK_JSON_VERSION))
                break
            if values['fan']:
                setFanSpeed([device], values['fan'])
            if values['overdrivesclk']:
                setClockOverDrive([device], 'sclk', values['overdrivesclk'], autoRespond)
            if values['overdrivemclk']:
                setClockOverDrive([device], 'mclk', values['overdrivemclk'], autoRespond)
            for clk in validClockNames:
                if clk in values['clocks']:
                    setClocks([device], clk, values['clocks'][clk])
            if values['profile']:
                setProfile([device], values['profile'])

            # Set Perf level last, since setting OverDrive sets the Performance level
            # it to manual, and Profiles only work when the Performance level is auto
            if values['perflevel']:
                setPerfLevel(device, values['perflevel'])

            printLog(device, 'Successfully loaded values from ' + savefilepath)


def save(deviceList, savefilepath):
    """ Save clock frequencies and fan speeds for a list of devices to a specified file path.

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    savefilepath -- Path to use to create the save file
    """
    perfLevels = {}
    clocks = {}
    fanSpeeds = {}
    overDriveGpu = {}
    overDriveGpuMem = {}
    profiles = {}
    jsonData = {}

    if os.path.isfile(savefilepath):
        print(savefilepath, 'already exists. Settings not saved')
        sys.exit()
    for device in deviceList:
        if not isDPMAvailable(device):
            printErr(device, 'Unable to save clocks')
            continue
        perfLevels[device] = getSysfsValue(device, 'perf')
        for clks in validClockNames:
            clocks[device] = clocks.get(device, {})
            clk = getCurrentClock(device, clks, 'level')
            if clk is None:
                continue
            clocks[device][clks] = clk
        fanSpeeds[device] = getFanSpeed(device)[0]
        overDriveGpu[device] = getSysfsValue(device, 'sclk_od')
        overDriveGpuMem[device] = getSysfsValue(device, 'mclk_od')
        profiles[device] = getProfile(device)
        jsonData[device] = {'vJson': CLOCK_JSON_VERSION, 'clocks': clocks[device], 'fan': fanSpeeds[device], 'overdrivesclk': overDriveGpu[device], 'overdrivemclk': overDriveGpuMem[device], 'profile': profiles[device], 'perflevel': perfLevels[device]}
    printLog(device, 'Current settings successfully saved to ' + savefilepath)
    with open(savefilepath, 'w') as savefile:
        json.dump(jsonData, savefile, ensure_ascii=True)


def checkAmdGpus(deviceList):
    """ Check if there are any AMD GPUs being queried,
    print a warning if there are none

    Parameters:
    deviceList -- List of DRM devices (can be a single-item list)
    """

    for device in deviceList:
        if isAmdDevice(device):
            return True
    return False


# Below is for when called as a script instead of when imported as a module
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='AMD ROCm System Management Interface', formatter_class=lambda prog: argparse.HelpFormatter(prog, max_help_position=90, width=120))
    groupDev = parser.add_argument_group()
    groupDisplay = parser.add_argument_group()
    groupAction = parser.add_argument_group()
    groupFile = parser.add_mutually_exclusive_group()
    groupResponse = parser.add_argument_group()
    groupOutput = parser.add_argument_group()

    groupDev.add_argument('-d', '--device', help='Execute command on specified device', type=int, nargs='+')
    groupDisplay.add_argument('-i', '--showid', help='Show GPU ID', action='store_true')
    groupDisplay.add_argument('-v', '--showvbios', help='Show VBIOS version', action='store_true')
    groupDisplay.add_argument('--showhw', help='Show Hardware details', action='store_true')
    groupDisplay.add_argument('-t', '--showtemp', help='Show current temperature', action='store_true')
    groupDisplay.add_argument('-c', '--showclocks', help='Show current clock frequencies', action='store_true')
    groupDisplay.add_argument('-g', '--showgpuclocks', help='Show current GPU clock frequencies', action='store_true')
    groupDisplay.add_argument('-f', '--showfan', help='Show current fan speed', action='store_true')
    groupDisplay.add_argument('-p', '--showperflevel', help='Show current DPM Performance Level', action='store_true')
    groupDisplay.add_argument('-P', '--showpower', help='Show current Average Graphics Package Power Consumption', action='store_true')
    groupDisplay.add_argument('-o', '--showoverdrive', help='Show current GPU Clock OverDrive level', action='store_true')
    groupDisplay.add_argument('-m', '--showmemoverdrive', help='Show current GPU Memory Clock OverDrive level', action='store_true')
    groupDisplay.add_argument('-M', '--showmaxpower', help='Show maximum graphics package power this GPU will consume', action='store_true')
    groupDisplay.add_argument('-l', '--showprofile', help='Show Compute Profile attributes', action='store_true')
    groupDisplay.add_argument('-s', '--showclkfrq', help='Show supported GPU and Memory Clock', action='store_true')
    groupDisplay.add_argument('-u', '--showuse', help='Show current GPU use', action='store_true')
    groupDisplay.add_argument('--showmemuse', help='Show current GPU memory used', action='store_true')
    groupDisplay.add_argument('-b', '--showbw', help='Show estimated PCIe use', action='store_true')
    groupDisplay.add_argument('--showreplaycount', help='Show PCIe Replay Count', action='store_true')
    groupDisplay.add_argument('-S', '--showclkvolt', help='Show supported GPU and Memory Clocks and Voltages', action='store_true')
    groupDisplay.add_argument('--showvoltage', help='Show current GPU voltage', action='store_true')
    groupDisplay.add_argument('--showrasinfo', help='Show RAS enablement information and error counts for the specified block(s)', metavar='BLOCK', type=str, nargs='+')
    groupDisplay.add_argument('--showfwinfo', help='Show FW information', metavar='BLOCK', type=str, nargs='*')
    groupDisplay.add_argument('--showproductname', help='Show SKU/Vendor name', action='store_true')
    groupDisplay.add_argument('-a' ,'--showallinfo', help='Show Temperature, Fan and Clock values', action='store_true')
    groupDisplay.add_argument('--showmeminfo', help='Show Memory usage information for given block(s) TYPE', metavar='TYPE', type=str, nargs='+')
    groupDisplay.add_argument('--showdriverversion', help='Show kernel driver version', action='store_true')
    groupDisplay.add_argument('--showuniqueid', help='Show GPU\'s Unique ID', action='store_true')
    groupDisplay.add_argument('--showpids', help='Show current running KFD PIDs', action='store_true')
    groupDisplay.add_argument('--alldevices', help='Execute command on non-AMD devices as well as AMD devices', action='store_true')

    groupAction.add_argument('-r', '--resetclocks', help='Reset clocks and OverDrive to default', action='store_true')
    groupAction.add_argument('--setsclk', help='Set GPU Clock Frequency Level(s) (requires manual Perf level)', type=int, metavar='LEVEL', nargs='+')
    groupAction.add_argument('--setmclk', help='Set GPU Memory Clock Frequency Level(s) (requires manual Perf level)', type=int, metavar='LEVEL', nargs='+')
    groupAction.add_argument('--setpcie', help='Set PCIE Clock Frequency Level(s) (requires manual Perf level)', type=int, metavar='LEVEL', nargs='+')
    groupAction.add_argument('--setslevel', help='Change GPU Clock frequency (MHz) and Voltage (mV) for a specific Level', metavar=('SCLKLEVEL', 'SCLK', 'SVOLT'), nargs=3)
    groupAction.add_argument('--setmlevel', help='Change GPU Memory clock frequency (MHz) and Voltage for (mV) a specific Level', metavar=('MCLKLEVEL', 'MCLK', 'MVOLT'), nargs=3)
    groupAction.add_argument('--resetfans', help='Reset fans to automatic (driver) control', action='store_true')
    groupAction.add_argument('--setfan', help='Set GPU Fan Speed (Level or %%)', metavar='LEVEL')
    groupAction.add_argument('--setperflevel', help='Set Performance Level', metavar='LEVEL')
    groupAction.add_argument('--setoverdrive', help='Set GPU OverDrive level (requires manual|high Perf level)', metavar='%')
    groupAction.add_argument('--setmemoverdrive', help='Set GPU Memory Overclock OverDrive level (requires manual|high Perf level)', metavar='%')
    groupAction.add_argument('--setpoweroverdrive', help='Set the maximum GPU power using Power OverDrive in Watts', metavar='WATTS')
    groupAction.add_argument('--resetpoweroverdrive', help='Set the maximum GPU power back to the device deafult state', action='store_true')
    groupAction.add_argument('--setprofile', help='Specify Power Profile level (#) or a quoted string of CUSTOM Profile attributes "# # # #..." (requires manual Perf level)')
    groupAction.add_argument('--resetprofile', help='Reset Power Profile back to default', action='store_true')
    groupAction.add_argument('--rasenable', help='Enable RAS for specified block and error type', type=str, nargs=2, metavar=('BLOCK', 'ERRTYPE'))
    groupAction.add_argument('--rasdisable', help='Disable RAS for specified block and error type', type=str, nargs=2, metavar=('BLOCK', 'ERRTYPE'))
    groupAction.add_argument('--rasinject', help='Inject RAS poison for specified block (ONLY WORKS ON UNSECURE BOARDS)', type=str, metavar='BLOCK', nargs=1)
    groupAction.add_argument('--gpureset', help='Reset specified GPU (One GPU must be specified)', action='store_true')

    groupFile.add_argument('--load', help='Load Clock, Fan, Performance and Profile settings from FILE', metavar='FILE')
    groupFile.add_argument('--save', help='Save Clock, Fan, Performance and Profile settings to FILE', metavar='FILE')

    groupResponse.add_argument('--autorespond', help='Response to automatically provide for all prompts (NOT RECOMMENDED)', metavar='RESPONSE')

    groupOutput.add_argument('--loglevel', help='How much output will be printed for what program is doing, one of debug/info/warning/error/critical', metavar='ILEVEL')
    groupOutput.add_argument('--json', help='Print output in JSON format', action='store_true')

    args = parser.parse_args()

    logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.WARNING)
    if args.loglevel is not None:
        numericLogLevel = getattr(logging, args.loglevel.upper(), logging.WARNING)
        logging.getLogger().setLevel(numericLogLevel)

    # If there is one or more device specified, use that for all commands, otherwise use a
    # list of all available devices. Also use "is not None" as device 0 would
    # have args.device=0, and "if 0" returns false.
    if args.device is not None:
        deviceList = []
        for dev in args.device:
            device = parseDeviceNumber(dev)
            if not doesDeviceExist(device):
                print('No such device ' + device)
                sys.exit()
            if (isAmdDevice(device) or args.alldevices) and device not in deviceList:
                deviceList.append(device)
            else:
                print('No supported devices available to display')
    else:
        deviceList = listDevices(args.alldevices)

    # If we want JSON output, initialize the keys (devices)
    if args.json:
        PRINT_JSON = True
        for device in deviceList:
            JSON_DATA[device] = {}

    if args.showallinfo:
        args.showid = True
        args.showtemp = True
        args.showclocks = True
        args.showfan = True
        args.list = True
        args.showuse = True
        args.showmemuse = True
        args.showperflevel = True
        args.showoverdrive = True
        args.showmemoverdrive = True
        args.showmaxpower = True
        args.showpower = True
        args.showvoltage = True
        args.showdriverversion = True
        args.showreplaycount = True
        args.showuniqueid = True
        args.showpids = True
        if not PRINT_JSON:
            args.showprofile = True
            args.showclkfrq = True
            args.showclkvolt = True

    if args.setsclk or args.setmclk or args.setpcie or args.resetfans or args.setfan or args.setperflevel or \
       args.load or args.resetclocks or args.setprofile or args.resetprofile or args.setoverdrive or \
       args.setmemoverdrive or args.setpoweroverdrive or args.resetpoweroverdrive or \
       args.rasenable or args.rasdisable or args.rasinject or \
       args.setslevel or args.setmlevel or args.gpureset:
        relaunchAsSudo()

    # Header for the SMI
    print('\n\n', headerSpacer + headerString + headerSpacer, sep='')

    # If all fields are requested, only print it for devices with DPM support. There is no point
    # in printing a bunch of "Feature unavailable" messages and cluttering the output
    # unnecessarily. We do it here to get it under the SMI Header, and to not print it multiple times
    # in case the SMI is relaunched as sudo
    # Note that this only affects the --all tab. While it won't output the supported fields like
    # temperature or fan speed, that would require a rework to implement. For now, devices without
    # DPM support can get the fields from the concise output, or by specifying the flag. But the
    # --all flag will not show any fields for a device that doesn't have DPM, even fan speed or temperature
    if args.showallinfo:
        for device in deviceList:
            if not isDPMAvailable(device):
                printErr(device, 'Skipping output for this device')
                deviceList.remove(device)

    # Don't do reset in combination with any other command
    if args.gpureset:
        if not args.device:
            logging.error('No device specified. One device must be specified for GPU reset')
            print(footerSpacer + footerString + footerSpacer, sep='')
            sys.exit(1)
        logging.debug('Only executing GPU reset, no other commands will be executed')
        resetGpu(deviceList)
        print(footerSpacer + footerString + footerSpacer, sep='')
        sys.exit(0)

    if not checkAmdGpus(deviceList):
        logging.warning('No AMD GPUs specified')

    if len(sys.argv) == 1 or \
        len(sys.argv) == 2 and (args.alldevices or args.json) or \
        len(sys.argv) == 3 and (args.alldevices and args.json):
        if PRINT_JSON:
            print("ERROR: Cannot print JSON output for concise output (no flags)")
            printLogSpacer()
            sys.exit(1)
        showAllConcise(deviceList)
    if args.showhw:
        if PRINT_JSON:
            print("ERROR: Cannot print JSON output for --showhw")
            printLogSpacer()
            sys.exit(1)
        showAllConciseHw(deviceList)
    if args.showid:
        showId(deviceList)
    if args.showvbios:
        showVbiosVersion(deviceList)
    if args.resetclocks:
        resetClocks(deviceList)
    if args.showtemp:
        showCurrentTemps(deviceList)
    if args.showclocks:
        showCurrentClocks(deviceList)
    if args.showgpuclocks:
        showCurrentClock(deviceList, 'sclk')
    if args.showfan:
        showCurrentFans(deviceList)
    if args.showperflevel:
        showPerformanceLevel(deviceList)
    if args.showoverdrive:
        showOverDrive(deviceList, 'sclk')
    if args.showmemoverdrive:
        showOverDrive(deviceList, 'mclk')
    if args.showdriverversion:
        showVersion(deviceList, 'driver')
    if args.showmaxpower:
        showMaxPower(deviceList)
    if args.showprofile:
        if PRINT_JSON:
            print("ERROR: Cannot print JSON output for --showprofile")
            printLogSpacer()
            sys.exit(1)
        showProfile(deviceList)
    if args.showpower:
        showPower(deviceList)
    if args.showclkfrq:
        if PRINT_JSON:
            print("ERROR: Cannot print JSON output for --showclkfrq")
            printLogSpacer()
            sys.exit(1)
        showClocks(deviceList)
    if args.showuse:
        showGpuUse(deviceList)
    if args.showmemuse:
        showMemUse(deviceList)
    if args.showbw:
        showPcieBw(deviceList)
    if args.showreplaycount:
        showPcieReplayCount(deviceList)
    if args.showuniqueid:
        showUniqueId(deviceList)
    if args.showpids:
        showPids()
    if args.showclkvolt:
        if PRINT_JSON:
            print("ERROR: Cannot print JSON output for --showclkvolt")
            printLogSpacer()
            sys.exit(1)
        showPowerPlayTable(deviceList)
    if args.showvoltage:
        showVoltage(deviceList)
    if args.showmeminfo:
        showMemInfo(deviceList, args.showmeminfo)
    if args.showrasinfo:
        showRasInfo(deviceList, args.showrasinfo)
    # The second condition in the below 'if' statement checks whether showfwinfo was given arguments.
    # It compares itself to the string representation of the empty list and prints all firmwares.
    # This allows the user to call --showfwinfo without the 'all' argument and still print all.
    if args.showfwinfo or str(args.showfwinfo) == '[]':
        showFwInfo(deviceList, args.showfwinfo)
    if args.showproductname:
        showProductName(deviceList)
    if args.setsclk:
        setClocks(deviceList, 'sclk', args.setsclk)
    if args.setmclk:
        setClocks(deviceList, 'mclk', args.setmclk)
    if args.setpcie:
        setClocks(deviceList, 'pcie', args.setpcie)
    if args.setslevel:
        setPowerPlayTableLevel(deviceList, 'sclk', args.setslevel, args.autorespond)
    if args.setmlevel:
        setPowerPlayTableLevel(deviceList, 'mclk', args.setmlevel, args.autorespond)
    if args.resetfans:
        resetFans(deviceList)
    if args.setfan:
        setFanSpeed(deviceList, args.setfan)
    if args.setperflevel:
        setPerformanceLevel(deviceList, args.setperflevel)
    if args.setoverdrive:
        setClockOverDrive(deviceList, 'sclk', args.setoverdrive, args.autorespond)
    if args.setmemoverdrive:
        setClockOverDrive(deviceList, 'mclk', args.setmemoverdrive, args.autorespond)
    if args.setpoweroverdrive:
        setPowerOverDrive(deviceList, args.setpoweroverdrive, args.autorespond)
    if args.resetpoweroverdrive:
        resetPowerOverDrive(deviceList, args.autorespond)
    if args.setprofile:
        setProfile(deviceList, args.setprofile)
    if args.resetprofile:
        resetProfile(deviceList)
    if args.rasenable:
        setRas(deviceList, 'enable', args.rasenable[0], args.rasenable[1])
    if args.rasdisable:
        setRas(deviceList, 'disable', args.rasdisable[0], args.rasdisable[1])
    if args.rasinject:
        setRas(deviceList, 'inject', args.rasinject[0], args.rasinject[1])
    if args.load:
        load(args.load, args.autorespond)
    if args.save:
        save(deviceList, args.save)

    if PRINT_JSON:
        print(json.dumps(JSON_DATA))

    # If RETCODE isn't 0, inform the user
    if RETCODE:
        logging.warning('One or more commands failed')

    # Footer for the SMI
    print(footerSpacer + footerString + footerSpacer, sep='')
    sys.exit(RETCODE)
