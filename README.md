### ROCm System Management Interface

This repository includes the rocm-smi tool. This tool exposes functionality for
clock and temperature management of your ROCm enabled system.

#### Installation

You may find rocm-smi at the following location after installing the rocm package:
```shell
/opt/rocm/bin/rocm-smi
```

Alternatively, you may clone this repository and run the tool directly.

#### Usage

For detailed and up to date usage information, we recommend consulting the help:
```shell
/opt/rocm/bin/rocm-smi -h
```

For convenience purposes, following is a quick excerpt:
```shell
usage: rocm-smi [-h] [-d DEVICE [DEVICE ...]] [-i] [-v] [--showhw] [-t] [-c] [-g] [-f] [-p] [-P] [-o] [-m] [-M] [-l]
                [-s] [-u] [-b] [--showreplaycount] [-S] [--showvoltage] [--showrasinfo BLOCK [BLOCK ...]]
                [--showfwinfo [BLOCK [BLOCK ...]]] [-a] [--showmeminfo TYPE [TYPE ...]] [--showdriverversion]
                [--alldevices] [-r] [--setsclk LEVEL [LEVEL ...]] [--setmclk LEVEL [LEVEL ...]]
                [--setpcie LEVEL [LEVEL ...]] [--setslevel SCLKLEVEL SCLK SVOLT] [--setmlevel MCLKLEVEL MCLK MVOLT]
                [--resetfans] [--setfan LEVEL] [--setperflevel LEVEL] [--setoverdrive %] [--setmemoverdrive %]
                [--setpoweroverdrive WATTS] [--resetpoweroverdrive] [--setprofile SETPROFILE] [--resetprofile]
                [--rasenable BLOCK ERRTYPE] [--rasdisable BLOCK ERRTYPE] [--rasinject BLOCK] [--gpureset]
                [--load FILE | --save FILE] [--autorespond RESPONSE] [--loglevel ILEVEL] [--json]

AMD ROCm System Management Interface

optional arguments:
  -h, --help                                            show this help message and exit
  --load FILE                                           Load Clock, Fan, Performance and Profile settings from FILE
  --save FILE                                           Save Clock, Fan, Performance and Profile settings to FILE

  -d DEVICE [DEVICE ...], --device DEVICE [DEVICE ...]  Execute command on specified device

  -i, --showid                                          Show GPU ID
  -v, --showvbios                                       Show VBIOS version
  --showhw                                              Show Hardware details
  -t, --showtemp                                        Show current temperature
  -c, --showclocks                                      Show current clock frequencies
  -g, --showgpuclocks                                   Show current GPU clock frequencies
  -f, --showfan                                         Show current fan speed
  -p, --showperflevel                                   Show current DPM Performance Level
  -P, --showpower                                       Show current Average Graphics Package Power Consumption
  -o, --showoverdrive                                   Show current GPU Clock OverDrive level
  -m, --showmemoverdrive                                Show current GPU Memory Clock OverDrive level
  -M, --showmaxpower                                    Show maximum graphics package power this GPU will consume
  -l, --showprofile                                     Show Compute Profile attributes
  -s, --showclkfrq                                      Show supported GPU and Memory Clock
  -u, --showuse                                         Show current GPU use
  -b, --showbw                                          Show estimated PCIe use
  --showreplaycount                                     Show PCIe Replay Count
  -S, --showclkvolt                                     Show supported GPU and Memory Clocks and Voltages
  --showvoltage                                         Show current GPU voltage
  --showrasinfo BLOCK [BLOCK ...]                       Show RAS enablement information and error counts for the
                                                        specified block(s)
  --showfwinfo [BLOCK [BLOCK ...]]                      Show FW information
  -a, --showallinfo                                     Show Temperature, Fan and Clock values
  --showmeminfo TYPE [TYPE ...]                         Show Memory usage information for given block(s) TYPE
  --showdriverversion                                   Show kernel driver version
  --alldevices                                          Execute command on non-AMD devices as well as AMD devices

  -r, --resetclocks                                     Reset clocks and OverDrive to default
  --setsclk LEVEL [LEVEL ...]                           Set GPU Clock Frequency Level(s) (requires manual Perf level)
  --setmclk LEVEL [LEVEL ...]                           Set GPU Memory Clock Frequency Level(s) (requires manual Perf
                                                        level)
  --setpcie LEVEL [LEVEL ...]                           Set PCIE Clock Frequency Level(s) (requires manual Perf level)
  --setslevel SCLKLEVEL SCLK SVOLT                      Change GPU Clock frequency (MHz) and Voltage (mV) for a specific
                                                        Level
  --setmlevel MCLKLEVEL MCLK MVOLT                      Change GPU Memory clock frequency (MHz) and Voltage for (mV) a
                                                        specific Level
  --resetfans                                           Reset fans to automatic (driver) control
  --setfan LEVEL                                        Set GPU Fan Speed (Level or %)
  --setperflevel LEVEL                                  Set Performance Level
  --setoverdrive %                                      Set GPU OverDrive level (requires manual|high Perf level)
  --setmemoverdrive %                                   Set GPU Memory Overclock OverDrive level (requires manual|high
                                                        Perf level)
  --setpoweroverdrive WATTS                             Set the maximum GPU power using Power OverDrive in Watts
  --resetpoweroverdrive                                 Set the maximum GPU power back to the device deafult state
  --setprofile SETPROFILE                               Specify Power Profile level (#) or a quoted string of CUSTOM
                                                        Profile attributes "# # # #..." (requires manual Perf level)
  --resetprofile                                        Reset Power Profile back to default
  --rasenable BLOCK ERRTYPE                             Enable RAS for specified block and error type
  --rasdisable BLOCK ERRTYPE                            Disable RAS for specified block and error type
  --rasinject BLOCK                                     Inject RAS poison for specified block (ONLY WORKS ON UNSECURE
                                                        BOARDS)
  --gpureset                                            Reset specified GPU (One GPU must be specified)

  --autorespond RESPONSE                                Response to automatically provide for all prompts (NOT
                                                        RECOMMENDED)

  --loglevel ILEVEL                                     How much output will be printed for what program is doing, one
                                                        of debug/info/warning/error/critical
  --json                                                Print output in JSON format
```


#### Detailed Option Descriptions

--setsclk/--setmclk # [# # ...]:
    This allows you to set a mask for the levels. For example, if a GPU has 8 clock levels,
    you can set a mask to use levels 0, 5, 6 and 7 with --setsclk 0 5 6 7 . This will only
    use the base level, and the top 3 clock levels. This will allow you to keep the GPU at
    base level when there is no GPU load, and the top 3 levels when the GPU load increases.

    NOTES:
        The clock levels will change dynamically based on GPU load based on the default
        Compute and Graphics profiles. The thresholds and delays for a custom mask cannot
        be controlled through the SMI tool

        This flag automatically sets the Performance Level to "manual" as the mask is not
        applied when the Performance level is set to auto

--setfan LEVEL:
    This sets the fan speed to a value ranging from 0 to maxlevel, or from 0%-100%

    If the level ends with a %, the fan speed is calculated as pct*maxlevel/100
        (maxlevel is usually 255, but is determined by the ASIC)

    NOTE: While the hardware is usually capable of overriding this value when required, it is
          recommended to not set the fan level lower than the default value for extended periods
          of time

--setperflevel LEVEL:
    This lets you use the pre-defined Performance Level values for clocks and power profile, which can include:
        auto (Automatically change values based on GPU workload)
        low (Keep values low, regardless of workload)
        high (Keep values high, regardless of workload)
        manual (Only use values defined by --setsclk and --setmclk)

--setoverdrive/--setmemoverdrive #:
    ***DEPRECATED IN NEWER KERNEL VERSIONS (use --setslevel/--setmlevel instead)***
    This sets the percentage above maximum for the max Performance Level.
    For example, --setoverdrive 20 will increase the top sclk level by 20%, similarly
    --setmemoverdrive 20 will increase the top mclk level by 20%. Thus if the maximum
    clock level is 1000MHz, then --setoverdrive 20 will increase the maximum clock to 1200MHz

    NOTES:
        This option can be used in conjunction with the --setsclk/--setmclk mask

        Operating the GPU outside of specifications can cause irreparable damage to your hardware
        Please observe the warning displayed when using this option

        This flag automatically sets the clock to the highest level, as only the highest level is
        increased by the OverDrive value

--setpoweroverdrive/--resetpoweroverdrive #:
    This allows users to change the maximum power available to a GPU package.
    The input value is in Watts. This limit is enforced by the hardware, and
    some cards allow users to set it to a higher value than the default that
    ships with the GPU. This Power OverDrive mode allows the GPU to run at
    higher frequencies for longer periods of time, though this may mean the
    GPU uses more power than it is allowed to use per power supply
    specifications. Each GPU has a model-specific maximum Power OverDrive that
    is will take; attempting to set a higher limit than that will cause this
    command to fail.

    NOTES:
        Operating the GPU outside of specifications can cause irreparable damage to your hardware
        Please observe the warning displayed when using this option

--setprofile SETPROFILE:
    The Compute Profile accepts 1 or n parameters, either the Profile to select (see --showprofile for a list
    of preset Power Profiles) or a quoted string of values for the CUSTOM profile.
    NOTE: These values can vary based on the ASIC, and may include:
        SCLK_PROFILE_ENABLE  - Whether or not to apply the 3 following SCLK settings (0=disable,1=enable)
            NOTE: This is a hidden field. If set to 0, the following 3 values are displayed as '-'
        SCLK_UP_HYST         - Delay before sclk is increased (in milliseconds)
        SCLK_DOWN_HYST       - Delay before sclk is decresed (in milliseconds)
        SCLK_ACTIVE_LEVEL    - Workload required before sclk levels change (in %)
        MCLK_PROFILE_ENABLE  - Whether or not to apply the 3 following MCLK settings (0=disable,1=enable)
            NOTE: This is a hidden field. If set to 0, the following 3 values are displayed as '-'
        MCLK_UP_HYST         - Delay before mclk is increased (in milliseconds)
        MCLK_DOWN_HYST       - Delay before mclk is decresed (in milliseconds)
        MCLK_ACTIVE_LEVEL    - Workload required before mclk levels change (in %)

        BUSY_SET_POINT       - Threshold for raw activity level before levels change
        FPS                  - Frames Per Second
        USE_RLC_BUSY         - When set to 1, DPM is switched up as long as RLC busy message is received
        MIN_ACTIVE_LEVEL     - Workload required before levels change (in %)

    NOTES:
        When a compute queue is detected, the COMPUTE Power Profile values will be automatically
        applied to the system, provided that the Perf Level is set to "auto"

        The CUSTOM Power Profile is only applied when the Performance Level is set to "manual"
        so using this flag will automatically set the performance level to "manual"

        It is not possible to modify the non-CUSTOM Profiles. These are hard-coded by the kernel

-P, --showpower:
Show Average Graphics Package power consumption

"Graphics Package" refers to the GPU plus any HBM (High-Bandwidth memory) modules, if present

-M, --showmaxpower:
Show the maximum Graphics Package power that the GPU will attempt to consume.
This limit is enforced by the hardware.

--loglevel:
This will allow the user to set a logging level for the SMI's actions. Currently this is
only implemented for sysfs writes, but can easily be expanded upon in the future to log
other things from the SMI

--showmeminfo:
This allows the user to see the amount of used and total memory for a given block (vram,
vis_vram, gtt). It returns the number of bytes used and total number of bytes for each block
'all' can be passed as a field to return all blocks, otherwise a quoted-string is used for
multiple values (e.g. "vram vis_vram")
vram refers to the Video RAM, or graphics memory, on the specified device
vis_vram refers to Visible VRAM, which is the CPU-accessible video memory on the device
gtt refers to the Graphics Translation Table

-b, --showbw:
This shows an approximation of the number of bytes received and sent by the GPU over
the last second through the PCIe bus. Note that this will not work for APUs since data for
the GPU portion of the APU goes through the memory fabric and does not 'enter/exit'
the chip via the PCIe interface, thus no accesses are generated, and the performance
counters can't count accesses that are not generated.
NOTE: It is not possible to easily grab the size of every packet that is transmitted
in real time, so the kernel estimates the bandwidth by taking the maximum payload size (mps),
which is the max size that a PCIe packet can be. and multiplies it by the number of packets
received and sent. This means that the SMI will report the maximum estimated bandwidth,
the actual usage could (and likely will be) less

--showrasinfo:
This shows the RAS information for a given block. This includes enablement of the block
(currently GFX, SDMA and UMC are the only supported blocks) and the number of errors
ue - Uncorrectable errors
ce - Correctable errors

### Clock Type Descriptions
DCEFCLK - DCE (Display)
FCLK    - Data fabric (VG20 and later) - Data flow from XGMI, Memory, PCIe
SCLK    - GFXCLK (Graphics core)
          Note - SOCCLK split from SCLK as of Vega10. Pre-Vega10 they were both controlled by SCLK
MCLK    - GPU Memory (VRAM)
PCLK    - PCIe bus
          Note - This gives 2 speeds, PCIe Gen1 x1 and the highest available based on the hardware
SOCCLK  - System clock (VG10 and later) - Data Fabric (DF), MM HUB, AT HUB, SYSTEM HUB, OSS, DFD
          Note - DF split from SOCCLK as of Vega20. Pre-Vega20 they were both controlled by SOCCLK

--gpureset:
This flag will attempt to reset the GPU for a specified device. This will invoke the GPU reset through
the kernel debugfs file amdgpu_gpu_recover. Note that GPU reset will not always work, depending on the
manner in which the GPU is hung.

---showdriverversion:
This flag will print out the AMDGPU module version for amdgpu-pro or ROCK kernels. For other kernels,
it will simply print out the name of the kernel (uname)

### OverDrive settings ####

For OverDrive functionality, the OverDrive bit (bit 14) must be enabled (by default, the
OverDrive bit is disabled on the ROCK and upstream kernels). This can be done by setting
amdgpu.ppfeaturemask accordingly in the kernel parameters, or by changing the default value
inside amdgpu_drv.c (if building your own kernel).

As an example, if the ppfeaturemask is set to 0xffffbfff (11111111111111111011111111111111),
then enabling the OverDrive bit would make it 0xffffffff (11111111111111111111111111111111).

#### Testing changes

After making changes to the SMI, run the test script to ensure that all functionality
remains intact before uploading the patch. This can be done using:
```shell
./test-rocm-smi.sh /opt/rocm/bin/rocm-smi
```

The test can run all flags for the SMI, or specific flags can be tested with the -s option.

Any new functionality added to the SMI should have a corresponding test added to the test script.

#### Disclaimer

The information contained herein is for informational purposes only, and is subject to change without notice. While every precaution has been taken in the preparation of this document, it may contain technical inaccuracies, omissions and typographical errors, and AMD is under no obligation to update or otherwise correct this information. Advanced Micro Devices, Inc. makes no representations or warranties with respect to the accuracy or completeness of the contents of this document, and assumes no liability of any kind, including the implied warranties of noninfringement, merchantability or fitness for particular purposes, with respect to the operation or use of AMD hardware, software or other products described herein. No license, including implied or arising by estoppel, to any intellectual property rights is granted by this document. Terms and limitations applicable to the purchase or use of AMD's products are as set forth in a signed agreement between the parties or in AMD's Standard Terms and Conditions of Sale.

AMD, the AMD Arrow logo, and combinations thereof are trademarks of Advanced Micro Devices, Inc. Other product names used in this publication are for identification purposes only and may be trademarks of their respective companies.

Copyright (c) 2014-2019 Advanced Micro Devices, Inc. All rights reserved.
