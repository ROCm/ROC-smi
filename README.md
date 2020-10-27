### ROCm System Management Interface

This repository is the previous home of the rocm-smi tool.

As of ROCm 3.9, this version of the rocm-smi has been deprecated.

You can find the new implementation at https://github.com/RadeonOpenCompute/rocm_smi_lib/tree/master/python_smi_tools

Old ROCm releases of the rocm-smi can be used by changing the branch. Only the master branch will feature this deprecation notice

### Reason for deprecation
The original rocm-smi CLI was implemented by parsing and manipulating sysfs files in the amdgpu sysfs pool (and debugfs pool).
This was done to support end-user utilization, but the desire to have a library of SMI commands was expressed and was implemented primarily by Chris Freehill. 
This resulted in having 2 repositories that did 95% of the same thing, and interacted with the same files but were completely isolated from one another. Due to this separation, we had functionality that was present in one project and not in the other, as well as inconsistent testing and performance.
As such, we made the decision to change the SMI CLI to use the library for as much functionality as possible, starting in ROCm 3.8. 
The change of rocm_smi.py to rocm_smi_deprecated.py in ROCm 3.8 implied this. 
The advantage of this change is that we can ensure consistency between SMI implementations, increase testing of SMI CLI functionality, and can expand the SMI in the future to use IOCTL calls instead of relying solely on the sysfs interface for increased functionality/performance/reliability/consistency. 
Both the deprecated and lib-backed SMI CLI can be used and installed together, just note that /opt/rocm/bin/rocm-smi will now point to the lib-backed SMI, starting in 3.8. Official deprecation of the old SMI CLI will be done around ROCm 4.0.

NOTE: Users should not notice a difference in the actual implementation of the LIB-backed SMI.
If there are any differences or bugs, please open a Bug Report in the rocm_smi_lib project.
