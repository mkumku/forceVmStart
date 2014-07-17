forceVmStart
============
ForceVmStart tool originated from vdsEmergency tool created by Douglas and available here:
https://github.com/dougsland/misc-ovirt/blob/master/forceVMstart.py

My current goal is to make it working with 3.4 version of d/s ovirt - rhevm.


This tool is emergency use only tool, for the scenarios when the manager is not accessible and some VMs need to go up. When using the tool, need to keep in mind that we must confirm the VMs are not running anywhere else (imagine the hosts that are not accessible, for some reason), to prevent brain split and damage on VMs disks data.
