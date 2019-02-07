#!/bin/bash

# Test that the current OverDrive Level reported by the SMI matches the current
# OverDrive Level of the corresponding device(s)
#  param smiPath        Path to the SMI
testGetGpuOverDrive() {
    local smiPath="$1"; shift;
    local smiDev="$1"; shift;
    local smiCmd="-o"
    echo -e "\nTesting $smiPath $smiDev $smiCmd..."
    local perfs="$($smiPath $smiDev $smiCmd)"
    IFS=$'\n'
    for line in $perfs; do
        if [ "$(checkLogLine $line)" != "true" ]; then
            continue
        fi
        local rocmOd="$(extractRocmValue $line)"

        local sysOd="$(cat $DRM_PREFIX/card${smiDev:3}/device/pp_sclk_od)%"
        if [ "$sysOd" != "$rocmOd" ]; then
            echo "FAILURE: OverDrive level from $SMI_NAME $rocmOd does not match $sysOd"
            NUM_FAILURES=$(($NUM_FAILURES+1))
        fi
    done
    echo -e "Test complete: $smiPath $smiDev $smiCmd\n"
    return 0
}

# Test that the setting the OverDrive Level through the SMI changes the current
# OverDrive Level of the corresponding device(s), and sets the current GPU Clock level
# to level 7 to use this new value
#  param smiPath        Path to the SMI
testSetGpuOverDrive() {
    local smiPath="$1"; shift;
    local smiDev="$1"; shift;
    local smiCmd="--setoverdrive"
    echo -e "\nTesting $smiPath $smiDev $smiCmd..."

    if isApu; then
        echo -e "Cannot test $smiCmd on an APU. Skipping test."
        return
    fi

    local odPath="$DRM_PREFIX/card${smiDev:3}/device/pp_sclk_od"

    local sysOdVolt=$(cat $DRM_PREFIX/card${smiDev:3}/device/pp_od_clk_voltage)
    if [ -z "$sysOdVolt" ]; then
        echo "OverDrive not supported. Skipping test."
        return 0
    fi
    local currOd="$(cat $odPath)" # OverDrive level
    local newOd="3"
    if [ "$currOd" == "3" ]; then
        local newOd="6"
    fi

    local od="$($smiPath $smiDev $smiCmd $newOd --autorespond YES)"
    local newSysOd="$(cat $odPath)"
    if [ "$newSysOd" != "$newOd" ]; then
        echo "FAILURE: Could not set OverDrive Level"
        NUM_FAILURES=$(($NUM_FAILURES+1))
    fi
    echo -e "Test complete: $smiPath $smiDev $smiCmd\n"
    return 0
}
