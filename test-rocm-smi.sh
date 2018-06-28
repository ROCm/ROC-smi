#!/bin/bash

# This script will test that all functionality from the SMI is working properly.
# Each SMI function requires its own corresponding test function. Any failing tests
# will increment $NUM_FAILURES. Once all tests are complete, the test script will
# return 0 if $NUM_FAILURES = 0, or 1 otherwise. This test must be run before
# submitting any modifications to the SMI to ensure that all SMI functionality works.

# test-basic.sh for testing getId, getTemp, save, load, getVbios reset, 
# test-fans.sh for testing get/set/reset fans
# test-perf.sh for testing get/set/reset perfLevel
# test-profile.sh for testing set/reset Profile
# test-clocks.sh for testing getCurrent/getSupported/setClock/reset GPU and Mem clocks
# test-overdrive.sh for testing get/set OverDrive for GPU and Mem

source tests/test-basic.sh
source tests/test-fans.sh
source tests/test-perf.sh
source tests/test-profile.sh
source tests/test-clocks.sh
source tests/test-overdrive.sh

SMI_DIR="$(pwd)"
SMI_SUBSET="all"
SMI_NAME="rocm-smi" # Name of the SMI application
DRM_PREFIX="/sys/class/drm"
HWMON_PREFIX="/sys/class/hwmon"
NUM_FAILURES=0

printUsage() {
    echo
    echo "Usage: $(basename $0) [options ...]"
    echo
    echo 'Options:'
    echo '  -p <path>    , --path <path>         Specify folder containing SMI'
    echo '  -s "flag(s)" , --subset "flag(s)"    Specify subset of SMI flags to test (must be in quotes)'
    echo '  -h           , --help                Prints this help'
    echo
    echo ' Example usage for subtest:'
    echo
    echo './test-rocm-smi.sh -s "--showclkfrq"'
    echo './test-rocm-smi.sh -s "-f -t -q"'

    return 0
}

# Check if the device is an APU. If so, there are certain SMI features that cannot
# be used, e.g. Fan Control (since the fan is technically the CPU fan)
isApu() {
    local simdcnt=$(awk '/simd_count/ {print $2}' /sys/class/kfd/kfd/topology/nodes/0/properties)
    # Evaluate if the count is >0. Using $? as the caller will give us the return status
    [ "$simdcnt" -gt "0" ]
}

# Get the corresponding HW Monitor for the specified GPU device $device
#  param device     Card number to obtain the corresponding HW Monitor
getHwmonFromDevice() {
    device="$1"; shift;
    local monitor=""
    local hwmons="$(ls $HWMON_PREFIX)"
    for hwmon in $hwmons; do
        if [ -e "$HWMON_PREFIX/$hwmon/name" ]; then
            local hwmonDevPath="$(readlink -f $HWMON_PREFIX/$hwmon/device)"
            local drmDevPath="$(readlink -f $DRM_PREFIX/card$device/device)"
            if [ "$hwmonDevPath" == "$drmDevPath" ]; then
                monitor="$hwmon"
                break
            fi
        fi
    done
    echo "$monitor"
}

# Set up the test environment by resetting all settings to default
setupTestEnv() {
    local smiPath="$1"; shift
    $($smiPath --resetclocks) &> /dev/null
    sleep 1
}

# Parse the line from the SMI output to remove the GPU prefix
# Each line is of the form "GPU[X] \t\t: $ATTRIBUTE: $VALUE", so we return $VALUE
#  param rocmLine       Line from the SMI log to parse
extractRocmValue() {
    local rocmLine="$1"; shift;
    local value="${rocmLine##*: }" # Remove the 'GPU[X] \t: [Attribute]:' prefix
    echo "$(echo $value | sed 's/ *$//')" # Remove any trailing whitespace
}

# Extract value from JSON file (modified from https://gist.github.com/cjus/1047794)
#  param device         Specific device for JSON value extraction
#  param jsonFile       Path to the JSON file to format
#  param field          Field to extract from the JSON file
extractJsonValue() {
    local device="$1"; shift;
    local jsonFile="$1"; shift;
    local field="$1"; shift;

    local value=""

    local json="$(cat $jsonFile)"
    # Remove everything before and after the desired device values (indicated with ||)
    # {card$device: |{values...}|, card$device+1: {values...}...})
    json="${json##*card$device}"
    json="${json%%card*}"

    value="$(echo "$json" | sed 's/\\\\\//\//g' | sed 's/[{}]//g' |\
        awk -v k="text" '{n=split($0,a,","); for (i=1; i<=n; i++) print a[i]}' |\
        sed 's/\"\:\"/\|/g' | sed 's/[\,]/ /g' | sed 's/\"//g' | grep -w $field |\
        awk -F ": " '{print $NF}')"
    echo "$value"
}

# Check the string to see if it starts with the SMI information prefix 'GPU[x]'
checkLogLine() {
    local rocmLine="$1"; shift;
    if [[ ! "$rocmLine" =~ ^"GPU[" ]]; then
        echo "false"
    else
        echo "true"
    fi
}

# Parse the line from the SMI output to determine the GPU number
#  param rocmLine       Line from the SMI log to parse
getGpuFromRocm() {
    local rocmLine="$1"; shift;
    local gpuPrefix="${rocmLine%%]*}" # Strip all information after 'GPU[X'
    echo "${gpuPrefix:4}" # Strip the 'GPU[' prefix
}

# Manually echo the value to the specified sysfs file
echoSysFs() {
    local sysfsPath="$1"; shift;
    local value="$1"; shift;
    echo "$value" | sudo tee $sysfsPath > /dev/null
}

# Return the number of clock levels in a specified clock file
#  param clockFile      Path to clock file
getNumLevels() {
    local clockFile="$1"; shift
    local numClockLevels="$(wc -l $clockFile)"
    numClockLevels="${numClockLevels%% *}" # Remove filename from wc output
    echo "$numClockLevels"
}

# Get current clock level for a specified clock file
#  param type           [freq|level] Type of clock to return
#  param clockFile      Path to clock file
getCurrentClock() {
    local type="$1"; shift;
    local clockFile="$1"; shift;
    local value=""
    clocks="$(cat $clockFile)"
    for line in $clocks; do
        if [ "${line: -1:1}" == "*" ]; then
            if [ "$type" == "level" ]; then
                value=${line%%:*}
            else
                value=${line##*: }
                value=${value:0:-2}
            fi
            break
        fi
    done
    echo "$value"
}

runTestSuite() {
    local smiPath="$1"; shift;
    local subsetList="$1"; shift;
    setupTestEnv "$smiPath"

    for subset in $subsetList; do
        case $subset in
            -i | --id)
                testGetId "$smiPath" ;;
            -t | --temp)
                testGetTemp "$smiPath" ;;
            -c | --showclocks)
                testGetCurrentClocks "$smiPath" ;;
            -f | --showfan)
                testGetFan "$smiPath" ;;
            -p | --showperf)
                testGetPerf "$smiPath" ;;
            -o | --showoverdrive)
                testGetGpuOverDrive "$smiPath" ;;
            -s | --showclkfrq)
                testGetSupportedClocks "$smiPath" ;;
            -r | --resetclocks)
                testReset "$smiPath" ;;
            --setsclk)
                testSetClock "gpu" "$smiPath" ;;
            --setmclk)
                testSetClock "mem" "$smiPath" ;;
            --setfan)
                testSetFan "$smiPath" ;;
            --resetfans)
                testResetFans "$smiPath" ;;
            --setperflevel)
                testSetPerf "$smiPath" ;;
            --setoverdrive)
                testSetGpuOverDrive "$smiPath" ;;
            --setprofile)
                testSetProfile "$smiPath" ;;
            --resetprofile)
                testResetProfile "$smiPath" ;;
            --save)
                testSave "$smiPath" ;;
            --load)
                testLoad "$smiPath" ;;
            all)
                testGetId "$smiPath" ;
                testGetTemp "$smiPath" ;
                testGetCurrentClocks "$smiPath" ;
                testGetFan "$smiPath" ;
                testGetPerf "$smiPath" ;
                testGetSupportedClocks "$smiPath" ;
                testGetGpuOverDrive "$smiPath" ;
                testSetFan "$smiPath" ;
                testResetFans "$smiPath" ;
                testSetClock "gpu" "$smiPath" ;
                testSetClock "mem" "$smiPath" ;
                testReset "$smiPath" ;
                testSetPerf "$smiPath" ;
                testSetGpuOverDrive "$smiPath" ;
                testSetProfile "$smiPath" ;
                testResetProfile "$smiPath" ;
                testSave "$smiPath" ;
                testLoad "$smiPath" ;
                break
                ;;
            *)
                echo "Unsupported option $subset . Exiting" ; exit 1 ;;
        esac
    done
}

while [ "$1" != "" ]; do
    case "$1" in
        -p  | --path )
            SMI_DIR="$2"; shift ;;
        -s  | --subtest )
            SMI_SUBSET="$2" ; shift ;;
        -h  | --help )
            printUsage; exit 0 ;;
        *)
            printUsage; exit 1 ;;
    esac
    shift 1
done

if [ ! -e "$SMI_DIR/$SMI_NAME" ]; then
    print "Unable to locate SMI at $SMI_DIR/$SMI_NAME."
    exit 1
fi

echo "===Start of ROCM-SMI test suite==="
runTestSuite "$SMI_DIR/$SMI_NAME" "$SMI_SUBSET"
echo "$NUM_FAILURES failure(s) occurred"
echo "===End of ROCM-SMI test suite==="

# Reset the system to get it back to a sane state
reset="$($SMI_DIR/$SMI_NAME -r && $SMI_DIR/$SMI_NAME --resetprofile)"

exit $NUM_FAILURES
