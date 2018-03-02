%define name        rocm-smi
%define packageroot $RPM_BUILD_ROOT
%define smiroot     $SMI_ROOT
%define version     %(echo $MODULE_VERSION | sed "s/-/_/g")

Name:       %{name}
Version:    %{version}
Release:    1
Summary:    System Management Interface for ROCm

Group:      Applications/System
License:    Advanced Micro Devices Inc.

%description
This package includes the System Management Interface for the ROC Platform

%prep
%setup -T -D -c -n %{name}

%install
mkdir -p %{packageroot}/opt/rocm/bin
cp -R %{smiroot}/rocm_smi.py %{packageroot}/opt/rocm/bin
ln -srf %{packageroot}/opt/rocm/bin/rocm_smi.py %{packageroot}/opt/rocm/bin/rocm-smi

%clean
rm -rf %{packageroot}

%files
/opt/rocm/bin/rocm-smi
/opt/rocm/bin/rocm_smi.py
%defattr(-,root,root,-)
