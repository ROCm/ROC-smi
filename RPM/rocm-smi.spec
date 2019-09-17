%define name        rocm-smi
%define packageroot $RPM_BUILD_ROOT
%define smiroot     $SMI_ROOT
%define version     %(echo $MODULE_VERSION | sed "s/-/_/g")
%define _installpath %{lua:print(os.getenv("ROCM_INSTALL_PATH"))}
%if %{?_installpath:0}
%define _installpath /opt/rocm
%endif

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
mkdir -p %{packageroot}%{_installpath}/bin
cp -R %{smiroot}/rocm_smi.py %{packageroot}%{_installpath}/bin
ln -srf %{packageroot}%{_installpath}/bin/rocm_smi.py %{packageroot}%{_installpath}/bin/rocm-smi

%clean
rm -rf %{packageroot}

%files
%{_installpath}/bin/rocm-smi
%{_installpath}/bin/rocm_smi.py
%defattr(-,root,root,-)
