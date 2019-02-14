#!/bin/bash

# Test that the current fan speed reported by the SMI matches the current fan speed of
# the corresponding device(s)
#  param smiPath        Path to the SMI
testGetFan() {
    local smiPath="$1"; shift;
    local smiDev="$1"; shift;
    local smiCmd="-f"
    echo -e "\nTesting $smiPath $smiDev $smiCmd..."
    local fans="$($smiPath $smiDev $smiCmd)"
    IFS=$'\n'
    for line in $fans; do
        if [ "$(checkLogLine $line)" != "true" ]; then
            continue
        elif [[ "$line" == *"Unable to"* ]]; then
            continue
        fi
        local rocmFan="$(extractRocmValue $line)"
        local hwmon="$(getHwmonFromDevice ${smiDev:3})"
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
    echo -e "Test complete: $smiPath $smiDev $smiCmd\n"
    return 0
}

# Test that the setting the fan speed through the SMI changes the current fan speed of the
# corresponding device(s)
#  param smiPath        Path to the SMI
testSetFan() {
    local smiPath="$1"; shift;
    local smiDev="$1"; shift;
    local smiCmd="--setfan"
    echo -e "\nTesting $smiPath $smiDev $smiCmd..."

    if isApu; then
        echo -e "Cannot test $smiCmd on an APU. Skipping test."
        return
    fi

    local hwmon="$(getHwmonFromDevice ${smiDev:3})"

    local currSysFan="$(cat $HWMON_PREFIX/$hwmon/pwm1)" # Fan speed level
    local sysFanMin="$(cat $HWMON_PREFIX/$hwmon/pwm1_min)" # Minimum fan speed
    local sysFanMax="$(cat $HWMON_PREFIX/$hwmon/pwm1_max)" # Maximum fan speed

    # On server cards, there are no controllable fans. If the fan is set to auto and 0, then
    # it's safe to assume that there is no controllable fan for it
    local resetFan=$($smiPath $smiDev --resetfans)
    if [ "$(cat $HWMON_PREFIX/$hwmon/pwm1)" == "0" ]; then
        echo -e "Cannot control fan, skipping test."
        return
    fi

    local fan="$($smiPath $smiDev $smiCmd $sysFanMin)"
    local newSysFan="$(cat $HWMON_PREFIX/$hwmon/pwm1)" # Fan speed level
    if [ "$newSysFan" != "$sysFanMin" ]; then
        echo "FAILURE: Could not set fan to minimum value $sysFanMin"
        NUM_FAILURES=$(($NUM_FAILURES+1))
    fi

    fan="$($smiPath $smiDev $smiCmd $sysFanMax)"
    newSysFan="$(cat $HWMON_PREFIX/$hwmon/pwm1)" # Fan speed level
    if [ "$newSysFan" != "$sysFanMax" ]; then
        echo "FAILURE: Could not set fan to maximum value $sysFanMax"
        NUM_FAILURES=$(($NUM_FAILURES+1))
    fi

    # Restore the original fan settings
    fan="$($smiPath $smiDev $smiCmd $currSysFan)"
    echo -e "Test complete: $smiPath $smiDev $smiCmd\n"
    return 0
}

# Test that resetting the fan control to auto through the SMI changes the current
# fan control mode of all devices.
#  param smiPath        Path to the SMI
testResetFans() {
    local smiPath="$1"; shift;
    local smiDev="$1"; shift;
    local smiCmd="--resetfans"
    echo -e "\nTesting $smiPath $smiDev $smiCmd..."

    if isApu; then
        echo -e "Cannot test $smiCmd on an APU. Skipping test"
        return
    fi

    # should reset fan control mode of all GPUs to auto (2)
    local mode="$($smiPath $smiDev $smiCmd)"
    local hwmon="$(getHwmonFromDevice ${smiDev:3})"

    local actualSysMode="$(cat $HWMON_PREFIX/$hwmon/pwm1_enable)" # Fan control mode
    if [ "$actualSysMode" != "2" ]; then
        echo "FAILURE: Could not set fan controls to auto (2), $hwmon still at $actualSysMode"
        NUM_FAILURES=$(($NUM_FAILURES+1))
    fi
    echo -e "Test complete: $smiPath $smiDev $smiCmd\n"
    return 0
}
