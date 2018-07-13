#!/bin/bash

# Test that the current OverDrive Level reported by the SMI matches the current
# OverDrive Level of the corresponding device(s)
#  param smiPath        Path to the SMI
testGetGpuOverDrive() {
    local smiPath="$1"; shift;
    local smiCmd="-o"
    echo -e "\nTesting $smiPath $smiCmd..."
    local perfs="$($smiPath $smiCmd)"
    IFS=$'\n'
    for line in $perfs; do
        if [ "$(checkLogLine $line)" != "true" ]; then
            continue
        fi
        local rocmOd="$(extractRocmValue $line)"
        local rocmGpu="$(getGpuFromRocm $line)"

        local sysOd="$(cat $DRM_PREFIX/card$rocmGpu/device/pp_sclk_od)%"
        if [ "$sysOd" != "$rocmOd" ]; then
            echo "FAILURE: OverDrive level from $SMI_NAME $rocmOd does not match $sysOd"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        fi
    done
    echo -e "Test complete: $smiPath $smiCmd\n"
    return 0
}

# Test that the setting the OverDrive Level through the SMI changes the current
# OverDrive Level of the corresponding device(s), and sets the current GPU Clock level
# to level 7 to use this new value
#  param smiPath        Path to the SMI
testSetGpuOverDrive() {
    local smiPath="$1"; shift;
    local smiCmd="--setoverdrive"
    echo -e "\nTesting $smiPath $smiCmd..."

    if isApu; then
        echo -e "Cannot test $smiCmd on an APU. Skipping test."
        return
    fi

    IFS=$'\n'
    local clocks=$($smiPath "-g") # Get a list of current GPU clock frequencies
    for line in $clocks; do
        if [ "$(checkLogLine $line)" != "true" ]; then
            continue
        elif [[ "$line" == *"PowerPlay not enabled"* ]]; then
            continue
        fi
        local rocmGpu="$(getGpuFromRocm $line)"
        local hwmon="$(getHwmonFromDevice $rocmGpu)"
        local odPath="$DRM_PREFIX/card$rocmGpu/device/pp_sclk_od"

        local sysOdVolt=$(cat $DRM_PREFIX/card$rocmGpu/device/pp_od_clk_voltage)
        if [ -z "$sysOdVolt" ]; then
            echo "OverDrive not supported. Skipping test."
            continue
        fi
        local currOd="$(cat $odPath)" # OverDrive level
        local newOd="3"
        if [ "$currOd" == "3" ]; then
            local newOd="6"
        fi

        local od="$($smiPath $smiCmd $newOd --autorespond YES)"
        local newSysOd="$(cat $odPath)"
        if [ "$newSysOd" != "$newOd" ]; then
            echo "FAILURE: Could not set OverDrive Level"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        fi
    done
    echo -e "Test complete: $smiPath $smiCmd\n"
    return 0
}
