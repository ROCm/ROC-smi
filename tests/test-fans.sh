#!/bin/bash

# Test that the current fan speed reported by the SMI matches the current fan speed of
# the corresponding device(s)
#  param smiPath        Path to the SMI
testGetFan() {
    local smiPath="$1"; shift;
    local smiCmd="-f"
    echo -e "\nTesting $smiPath $smiCmd..."
    local fans="$($smiPath $smiCmd)"
    IFS=$'\n'
    for line in $fans; do
        if [ "$(checkLogLine $line)" != "true" ]; then
            continue
        elif [[ "$line" == *"Unable to determine"* ]]; then
            continue
        fi
        local rocmFan="$(extractRocmValue $line)"
        local rocmGpu="$(getGpuFromRocm $line)"
        local hwmon="$(getHwmonFromDevice $rocmGpu)"
        local rocmFanLevel="${rocmFan%% \(*}"
        local rocmFanPct="${rocmFan##*(}"
        rocmFanPct="${rocmFanPct%%.*}" # Truncate fan percent decimals

        local sysFan="$(cat "$HWMON_PREFIX/$hwmon/pwm1")" # Fan speed level (not percentage)
        local sysFanMax="$(cat "$HWMON_PREFIX/$hwmon/pwm1_max")" # Maximum fan speed
        local sysFanPct=$((100*$sysFan/$sysFanMax))

        if [ "$sysFan" != "$rocmFanLevel" ]; then
            echo "FAILURE: GPU fan level from $SMI_NAME $rocmFanLevel does not match $sysFan"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        elif [ "$rocmFanPct" != "$sysFanPct" ]; then
            echo "FAILURE: GPU fan percentage from $SMI_NAME $rocmFanPct does not match $sysFanPct"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        fi
    done
    echo -e "Test complete: $smiPath $smiCmd\n"
    return 0
}

# Test that the setting the fan speed through the SMI changes the current fan speed of the
# corresponding device(s)
#  param smiPath        Path to the SMI
testSetFan() {
    local smiPath="$1"; shift;
    local smiCmd="--setfan"
    echo -e "\nTesting $smiPath $smiCmd..."

    if isApu; then
        echo -e "Cannot test $smiCmd on an APU. Skipping test."
        return
    fi

    IFS=$'\n'
    # Get a list of current GPU clock frequencies. Since some GPUs can report but not
    # modify the fan speed, use ones that we can control.
    local clocks="$($smiPath -g)"
    for line in $clocks; do
        if [ "$(checkLogLine $line)" != "true" ]; then
            continue
        elif [[ "$line" == *"PowerPlay not enabled"* ]]; then
            continue
        fi
        local rocmGpu="$(getGpuFromRocm $line)"
        local hwmon="$(getHwmonFromDevice $rocmGpu)"

        local currSysFan="$(cat $HWMON_PREFIX/$hwmon/pwm1)" # Fan speed level
        local sysFanMin="$(cat $HWMON_PREFIX/$hwmon/pwm1_min)" # Minimum fan speed
        local sysFanMax="$(cat $HWMON_PREFIX/$hwmon/pwm1_max)" # Maximum fan speed
        local newFanValue="$sysFanMax"

        local fan="$($smiPath $smiCmd $sysFanMin)"
        local newSysFan="$(cat $HWMON_PREFIX/$hwmon/pwm1)" # Fan speed level
        if [ "$newSysFan" != "$sysFanMin" ]; then
            echo "FAILURE: Could not set fan to minimum value $sysFanMin"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        fi

        fan="$($smiPath $smiCmd $sysFanMax)"
        newSysFan="$(cat $HWMON_PREFIX/$hwmon/pwm1)" # Fan speed level
        if [ "$newSysFan" != "$sysFanMax" ]; then
            echo "FAILURE: Could not set fan to maximum value $sysFanMax"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        fi

        # Restore the original fan settings
        fan="$($smiPath $smiCmd $currSysFan)"
    done
    echo -e "Test complete: $smiPath $smiCmd\n"
    return 0
}

# Test that resetting the fan control to auto through the SMI changes the current
# fan control mode of all devices.
#  param smiPath        Path to the SMI
testResetFans() {
    local smiPath="$1"; shift;
    local smiCmd="--resetfans"
    echo -e "\nTesting $smiPath $smiCmd..."

    if isApu; then
        echo -e "Cannot test $smiCmd on an APU. Skipping test"
        return
    fi

    IFS=$'\n'
    # should reset fan control mode of all GPUs to auto (2)
    local mode="$($smiPath $smiCmd)"
    # Get a list of current GPU clock frequencies. Since some GPUs can report but not
    # modify the fan speed, use ones that we can control.
    local clocks="$($smiPath -g)"
    for line in $clocks; do
        if [ "$(checkLogLine $line)" != "true" ]; then
            continue
        elif [[ "$line" == *"PowerPlay not enabled"* ]]; then
            continue
        fi
        local rocmGpu="$(getGpuFromRocm $line)"
        local hwmon="$(getHwmonFromDevice $rocmGpu)"

        local actualSysMode="$(cat $HWMON_PREFIX/$hwmon/pwm1_enable)" # Fan control mode
        if [ "$actualSysMode" != "2" ]; then
            echo "FAILURE: Could not set fan controls to auto (2), $hwmon still at $actualSysMode"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        fi
    done
    echo -e "Test complete: $smiPath $smiCmd\n"
    return 0
}
