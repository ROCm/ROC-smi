#!/bin/bash

# This script will test that all functionality from the SMI is working properly.
# Each SMI function requires its own corresponding test function. Any failing tests
# will increment $NUM_FAILURES. Once all tests are complete, the test script will
# return 0 if $NUM_FAILURES = 0, or 1 otherwise. This test must be run before
# submitting any modifications to the SMI to ensure that all SMI functionality works.

# test-basic.sh for testing basic SMI functionality
# test-fans.sh for testing get/set/reset fans
# test-perf.sh for testing get/set/reset perfLevel
# test-profile.sh for testing set/reset Power Profile
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
SMI_DEVICE=""
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
    echo '  -d <device>  , --device <device>     Specify the device which the test should be executed on'
    echo '  -h           , --help                Prints this help'
    echo
    echo ' Example usage for subtest:'
    echo
    echo './test-rocm-smi.sh -s "--showclkfrq"'
    echo './test-rocm-smi.sh -s "-f -t -q"'

    return 0
}

# Check that the device is valid
verifyDevice() {
    local dev="${1:3}"
    if [ ! -e "/sys/class/drm/card$dev/device/pp_dpm_sclk" ]; then
        echo "Device card$dev not supported. Exiting."
        exit 1
    fi
}

# Don't run the test on an unsupported node.
setTestDevice() {
    cards="$(ls /sys/class/drm/ | egrep 'card[0-9]+$' | tr '\n' ' ')"
    for card in $cards; do
        if [ -e "/sys/class/drm/$card/device/pp_dpm_sclk" ]; then
            local dev="${card:4}"
            break
        fi
    done
    if [ -z "$dev" ]; then
        echo "No valid device found. Exiting."
        exit 1
    fi
    SMI_DEVICE="-d $dev"
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

# Parse the lines from the SMI output to remove the GPU prefix and headers/footers
# Each line is of the form "GPU[X] \t\t: $ATTRIBUTE: $VALUE", so we return $VALUE
#  param rocmLine       Line from the SMI log to parse
extractRocmValue() {
    local rocmLine="$1"
    # Clear out the prefix and suffix to our desired value
    echo "$(echo ${rocmLine##*: } | sed 's/ *$//')"
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
    while read -r line; do
        if [[ "$line" =~ \*$ ]]; then
            if [ "$type" == "level" ]; then
                value=${line%%:*}
            else
                value=${line##*: }
                value=${value:0:-2}
            fi
            break
        fi
    done <<< "$clocks"
    echo "$value"
}

runTestSuite() {
    local smiPath="$1"; shift;
    local smiDev="$1"; shift;
    local subsetList="$1"; shift;
    setupTestEnv "$smiPath"

    for subset in $subsetList; do
        case $subset in
            -i | --id)
                testGetId "$smiPath" "$smiDev" ;;
            -t | --temp)
                testGetTemp "$smiPath" "$smiDev" ;;
            -c | --showclocks)
                testGetCurrentClocks "$smiPath" "$smiDev" ;;
            -f | --showfan)
                testGetFan "$smiPath" "$smiDev" ;;
            -p | --showperf)
                testGetPerf "$smiPath" "$smiDev" ;;
            -o | --showoverdrive)
                testGetGpuOverDrive "$smiPath" "$smiDev" ;;
            -s | --showclkfrq)
                testGetSupportedClocks "$smiPath" "$smiDev" ;;
            -r | --resetclocks)
                testReset "$smiPath" "$smiDev" ;;
            --setsclk)
                testSetClock "gpu" "$smiPath" "$smiDev" ;;
            --setmclk)
                testSetClock "mem" "$smiPath" "$smiDev" ;;
            --setpclk)
                testSetClock "pcie" "$smiPath" "$smiDev" ;;
            --setfan)
                testSetFan "$smiPath" "$smiDev" ;;
            --resetfans)
                testResetFans "$smiPath" "$smiDev" ;;
            --setperflevel)
                testSetPerf "$smiPath" "$smiDev" ;;
            --setoverdrive)
                testSetGpuOverDrive "$smiPath" "$smiDev" ;;
            --setprofile)
                testSetProfile "$smiPath" "$smiDev" ;;
            --resetprofile)
                testResetProfile "$smiPath" "$smiDev" ;;
            --save)
                testSave "$smiPath" "$smiDev" ;;
            --load)
                testLoad "$smiPath" "$smiDev" ;;
            all)
                testGetId "$smiPath" "$smiDev" ;
                testGetTemp "$smiPath" "$smiDev" ;
                testGetCurrentClocks "$smiPath" "$smiDev" ;
                testGetFan "$smiPath" "$smiDev" ;
                testGetPerf "$smiPath" "$smiDev" ;
                testGetSupportedClocks "$smiPath" "$smiDev" ;
                testGetGpuOverDrive "$smiPath" "$smiDev" ;
                testSetFan "$smiPath" "$smiDev" ;
                testResetFans "$smiPath" "$smiDev" ;
                testSetClock "gpu" "$smiPath" "$smiDev" ;
                testSetClock "mem" "$smiPath" "$smiDev" ;
                testSetClock "pcie" "$smiPath" "$smiDev" ;
                testReset "$smiPath" "$smiDev" ;
                testSetPerf "$smiPath" "$smiDev" ;
                testSetGpuOverDrive "$smiPath" "$smiDev" ;
                testSetProfile "$smiPath" "$smiDev" ;
                testResetProfile "$smiPath" "$smiDev" ;
                testSave "$smiPath" "$smiDev" ;
                testLoad "$smiPath" "$smiDev" ;
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
        -d | --device )
            SMI_DEVICE="-d $2" ; shift ;;
        -h  | --help )
            printUsage; exit 0 ;;
        *)
            printUsage; exit 1 ;;
    esac
    shift 1
done

if [ ! -e "$SMI_DIR/$SMI_NAME" ]; then
    if [ -e "$SMI_DIR/../$SMI_NAME" ]; then
        SMI_DIR="$SMI_DIR/.."
    elif [ -e "/opt/rocm/bin/$SMI_NAME" ]; then
        print "Unable to locate SMI at $SMI_DIR/$SMI_NAME, using /opt/rocm/bin/ instead"
        SMI_DIR="/opt/rocm/bin"
    else
        print "Unable to locate SMI at $SMI_DIR/$SMI_NAME."
        exit 1
    fi
fi

echo "===Start of ROCM-SMI test suite==="
if [ -z "$SMI_DEVICE" ]; then
    setTestDevice
else
    verifyDevice "$SMI_DEVICE"
fi
runTestSuite "$SMI_DIR/$SMI_NAME" "$SMI_DEVICE" "$SMI_SUBSET"
echo "$NUM_FAILURES failure(s) occurred"
echo "===End of ROCM-SMI test suite==="

# Reset the system to get it back to a sane state
reset="$($SMI_DIR/$SMI_NAME -r && $SMI_DIR/$SMI_NAME --resetprofile)"

exit $NUM_FAILURES
