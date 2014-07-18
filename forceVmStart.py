#!/usr/bin/env python
#
# Copyright 2010-2012 Red Hat, Inc.
#
# Licensed to you under the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# Require Packages: python-iniparse
#
# Original script by:
# - Douglas Landgraf (dougsland@redhat.com)
#
# Contributors:
# - Marina Kalinin (marinamku@gmail.com)
# - Vladik Romanovsky (vladik.romanovsky@gmail.com)
# - Pablo Iranzo Gomez (Pablo.Iranzo@redhat.com)
#
# Available in repository:
# https://github.com/mkumku/forceVmStart

###############################################################################
##############                       WARNING                     ##############
##############   The use of this script is inherently raceful    ##############
##############   use it only on emergency cases when it's no     ##############
##############   possible to wait until manager  is up again     ##############
###############################################################################

import getopt
import sys
import commands
import os
import socket
from xml.dom.minidom import parse, parseString

try:
    from iniparse import ConfigParser
except:
    print "Package python-iniparse is required, please install"
    print "#yum install python-iniparse -y"
    sys.exit(1)


try:
    from vdsm import vdscli
except:
    print "Cannot import vdscli, please fix it"
    sys.exit(1)

try:
    import vdsClient
except:
    print "Cannot import vdsClient, please fix it"
    sys.exit(1)

# General Macros
VERSION = "1.0.0"
VDSM_PORT = "54321"

#DEBUG MODE
DEBUG = "False" # True or False

#########################################################################

class vdsmEmergency:

    def __init__(self):
        """Initialize method"""
        sslRet = self.checkSSLvdsm()
        self.useSSL = sslRet
        self.truststore = None

    def do_connect(self, server, port):
        """Do a connection with vdsm daemon"""
        print "Trying to connect to vdsmd host (%s).." % server

        # Connection Validation
        sk = socket.socket()
        try:
            sk.connect((server, int(VDSM_PORT)))
        except Exception, e:
            print "Unable to connect %s" % server
            sk.close()
            return -1

        self.s = vdscli.connect(server + ':' + port, self.useSSL, self.truststore)

        print "OK, Connected to vdsmd!"
        return 0

    def checkRoot(self):
        """check if the user running the script is root"""
        if os.geteuid() != 0:
            print "You must be root to run this script."
            sys.exit(2)

    def getIpManagementIP(self):
        """get the IP from management interface"""

        # TODO: avoid this kind of hack, find a better approach (vdsClient provide the IP of ovirtmgmt/rhevm interface?)
        # strCmd = "ifconfig  ovirtmgmt | grep \"inet addr\" | cut -d \':\' -f 2 | cut -d \' \' -f 1"

        # Code to make it work for the rhevm or the ovirtmgmt interface

        strCmd = "ifconfig ovirtmgmt 2>/dev/null|grep inet|grep -v inet6|awk '{print $2}'|cut -d ':' -f2"
        retCmd = commands.getstatusoutput(strCmd)
        if retCmd[1] == "":
            strCmd = "ifconfig rhevm 2>/dev/null|grep inet|grep -v inet6|awk '{print $2}'|cut -d ':' -f2"
            retCmd = commands.getstatusoutput(strCmd)

        if retCmd[0] != 0:
            print "Error getting IP from management interface"
            sys.exit(1)

        return retCmd[1]

    def checkSSLvdsm(self):
        """check if vdsm is running as SSL or without it"""

        cfg = ConfigParser()
        cfg.read('/etc/vdsm/vdsm.conf')
        cfg.get('vars', 'ssl')

        return cfg.data.vars.ssl


    def checkVmRunning(self, otherHostsList, VmsToStart):
        """check if the vm's are running"""

        hosts = None
        vms = None
        i = 0
        j = 0

        if otherHostsList == None:
            return -1

        if VmsToStart == None:
            return -1

        vms = VmsToStart.split(",")
        hosts = otherHostsList.split(",")

        # Let's check if all other Hosts are running the VirtualMachine
        while (i <> len(hosts)):
            ret = VE.do_connect(hosts[i], VDSM_PORT)
            if ret < 0:
                sys.exit(1)
            response = self.s.list()
            if response['status']['code'] != 0:
                print "cannot execute list operation, err:" + response['status']['message']

            # Checking VM status
            for s in self.s.getAllVmStats()['statsList']:
                j = 0

                # print all vms in each host
                while j < len(vms):
                    if DEBUG == "True":
                        print len(vms)
                        print s['vmId']
                        print hosts[i]
                        print vms[j]

                    vmIdCurr = self.getVmId(vms[j])

                    if DEBUG == "True":
                        print vmIdCurr
                        print s['vmId']

                    if s['vmId'] == vmIdCurr and s['status'] == "Up":
                        print "Cannot continue, the VM %s is running in host %s" % (vms[j], hosts[i])
                        sys.exit(1)
                    j = j + 1

            # counter for hosts
            i = i + 1

        print "OK, the vm(s) specified are not running on the host(s) informed, continuing.."

    def checkSPM(self):
        """check if the host which is running this script is the SPM"""
        self.spUUID = None
        self.spmStatus = None

        ip_management_interface = self.getIpManagementIP()
        self.do_connect(ip_management_interface, VDSM_PORT)

        try:
            list = self.s.getConnectedStoragePoolsList()
        except:
            print "Cannot execute getConnectedStoragePoolsList()"
            sys.exit(1)

        for entry in list['poollist']:
            self.spUUID = entry

        if not self.spUUID:
            print "Cannot locate Storage Pools List.. aborting!"
            sys.exit(1)

        try:
            status = self.s.getSpmStatus(self.spUUID)
        except:
            print "Cannot execute getSpmStatus()"
            sys.exit(1)

        self.spmStatus = status['spm_st']['spmStatus']

        if self.spmStatus <> "SPM":
            print "This host is not the current SPM, status [%s]" % self.spmStatus
            sys.exit(1)

    def getVmId(self, vmName):
        """get the vmId from the vmName used as argument"""
        path = "/rhev/data-center/%s/mastersd/master/vms" % (self.spUUID)

        # First verify which domainID contain de XML files
        try:
            dirList = os.listdir(path)
        except:
            print "Cannot locate the dir with ovf files.. aborting!"
            sys.exit(1)

        #Read all content of xml(s) file(s)
        for fname in dirList:

            pathOVF = path + "/" + fname + "/" + fname + ".ovf"

            dom = parse(pathOVF)

            # Getting vmId field
            i = 0
            attr = 0
            for node in dom.getElementsByTagName('Section'):
                while (i < len(node.attributes)):
                    attr = node.attributes.items()
                    if attr[i][0] == "ovf:id":
                        vmId = attr[i][1]
                    i = i + 1

            # Getting vmName field
            for node in dom.getElementsByTagName('Content'):
                if node.childNodes[0].firstChild <> None:
                    if node.childNodes[0].firstChild.nodeValue == vmName:
                        return vmId



    def _parseDriveSpec(self, spec):
        if ',' in spec:
            d = {}
            for s in spec.split(','):
                k, v = s.split(':', 1)
                if k == 'domain': d['domainID'] = v
                if k == 'pool': d['poolID'] = v
                if k == 'image': d['imageID'] = v
                if k == 'volume': d['volumeID'] = v
                if k == 'boot': d['boot'] = v
                if k == 'format': d['format'] = v
            return d
        return spec

    def readXML(self, VmsStotart, destHostStart):
        """read all xml available pointed to Directory path and parse for specific fields"""

        # number of Vms found
        nrmVms = 0
        cmd = {}
        # Path to XML files
        # example default path:
        # /rhev/data-center/1a516f64-f091-4785-9278-362037513408/vms
        path = "/rhev/data-center/%s/mastersd/master/vms" % (self.spUUID)

        # First verify which domainID contain de XML files
        try:
            dirList = os.listdir(path)
        except:
            print "Cannot locate the dir with ovf files.. aborting!"
            sys.exit(1)

        #Read all content of xml(s) file(s)
        for fname in dirList:

            pathOVF = path + "/" + fname + "/" + fname + ".ovf"
            
            # prepare static fields (same for all vms):
            cmd['acpiEnable'] = "True"
            cmd['kvmEnable'] = "True"
            cmd['tabletEnable'] = "True"
            cmd['nice'] = 0
            cmd['keyboardLayout'] = "en-us"

            dom = parse(pathOVF)
            
            # Getting vmId field
            i = 0
            attr = 0
            for node in dom.getElementsByTagName('Section'):
                while (i < len(node.attributes)):
                    attr = node.attributes.items()
                    if attr[i][0] == "ovf:id":
                        cmd["vmId"] = attr[i][1]
                        #print 'vmId: %s' % cmd["vmId"]
                    i = i + 1

            for node in dom.getElementsByTagName('Content'):
                # Getting vmName field
                if node.getElementsByTagName('Name'):
		    if node.getElementsByTagName('Name')[0].firstChild <> None:
                        self.vmName = node.getElementsByTagName('Name')[0].firstChild.data
                        cmd['vmName'] = self.vmName
                        print 'self.vmName = %s' % self.vmName
                    else:
                        print 'No vmName attribute for vmId %s, continue to next ovf' % cmd[vmId]

                # Getting display driver:
                if node.getElementsByTagName('DefaultDisplayType'):
                    if node.getElementsByTagName('DefaultDisplayType')[0].firstChild <> None:
                        cmd['display'] = 'qxl' if node.getElementsByTagName('DefaultDisplayType')[0].firstChild.data == '1' else 'vnc'
                        print cmd['display']
                else: 
                    print 'Template has no display value'
   


            import pdb; pdb.set_trace()
            # Getting image and volume
            # mku this section does not work
            i = 0
            attr = 0
            for node in dom.getElementsByTagName('Disk'):
                while (i <> len(node.attributes)):
                    attr = node.attributes.items()
                    if attr[i][0] == "ovf:fileRef":
                        storage = attr[i][1]
                        data = storage.split("/")
                        image = data[0]
                        volume = data[1]
                    i += 1

            # Getting VM format, boot
            i = 0
            attr = 0
            for node in dom.getElementsByTagName('Disk'):
                while (i <> len(node.attributes)):
                    attr = node.attributes.items()
                    if attr[i][0] == "ovf:volume-format":
                        format = attr[i][1]

                    if attr[i][0] == "ovf:boot":
                        vmBoot = attr[i][1]

                    if attr[i][0] == "ovf:disk-interface":
                        ifFormat = attr[i][1]

                    i += 1

            if format == "COW":
                vmFormat = ":cow"
            elif format == "RAW":
                vmFormat = ":raw"


            if ifFormat == "VirtIO":
                ifDisk = "virtio"
            elif ifFormat == "IDE":
                ifDisk = "ide"
            drives = []
            # Getting Drive, bridge, memSize, macAddr, smp, smpCoresPerSocket
            for node in dom.getElementsByTagName('Item'):
                # Getting Drive
                if node.childNodes[0].firstChild <> None:
                    str = node.childNodes[0].firstChild.nodeValue
                    if str.find("Drive") > -1:
                        tmp = "pool:" + self.spUUID + ",domain:" + node.childNodes[7].firstChild.nodeValue + ",image:" + image + ",volume:" + volume + ",boot:" + vmBoot + ",format" + vmFormat + ",if:" + ifDisk
                        #param,value = tmp.split("=",1)
                        drives += [self._parseDriveSpec(tmp)]
                        cmd['drives'] = drives

                # Getting bridge
                nicMod = "pv"
                if node.childNodes[0].firstChild.nodeValue == "Ethernet adapter on rhevm":
                    if node.childNodes[3].firstChild.nodeValue == "3":
                        nicMod = "pv" #VirtIO
                    elif node.childNodes[3].firstChild.nodeValue == "2":
                        nicMod = "e1000" #e1000
                    elif node.childNodes[3].firstChild.nodeValue == "1":
                        nicMod = "rtl8139" #rtl8139

                    cmd['nicModel'] = nicMod
                    cmd['bridge'] = node.childNodes[4].firstChild.nodeValue

                # Getting memSize field
                str = node.childNodes[0].firstChild.nodeValue
                if str.find("MB of memory") > -1:
                    cmd['memSize'] = node.childNodes[5].firstChild.nodeValue

                # Getting smp and smpCoresPerSocket fields
                str = node.childNodes[0].firstChild.nodeValue
                if str.find("virtual cpu") > -1:
                    cmd["smp="] = node.childNodes[4].firstChild.nodeValue
                    cmd["smpCoresPerSocket"] = node.childNodes[5].firstChild.nodeValue

                # Getting macAddr field
                if node.childNodes[0].firstChild.nodeValue == "Ethernet adapter on rhevm":
                    if len(node.childNodes) > 6:
                        cmd['macAddr'] = node.childNodes[6].firstChild.nodeValue

                    # if node.childNodes < 6 it`s a template entry, so ignore
                    if len(node.childNodes) > 6:
                        # print only vms to start
                        try:
                            checkvms = VmsToStart.split(",")
                        except:
                            print "Please use , between vms name, avoid space"
                            self.usage()

                        i = 0
                        while (i <> len(checkvms)):
                            if self.vmName == checkvms[i]:
                                nrmVms = nrmVms + 1
				#import pdb; pdb.set_trace()
                                #self.startVM(cmd, destHostStart)
                                print "Debug mode. Not starting VM. Printing cmd:"
                                print cmd
                            i += 1

        print "Total VMs found: %s" % nrmVms

    def startVM(self, cmd, destHostStart):
        """start the VM"""

        #cmd = {'acpiEnable': 'true', 'emulatedMachine': 'rhel6.5.0', 'vmId': '79f4a348-a928-45c4-85c6-b6bfc600d507', 'memGuaranteedSize': 1024, 'spiceSslCipherSuite': 'DEFAULT', 'timeOffset': '0', 'cpuType': 'Penryn', 'custom': {'device_c5d3d740-1c66-43d9-8f69-bbf70b17850fdevice_95d5fd25-7bdb-4c90-a0c0-e6e43fcc3eabdevice_ba80ae13-a054-4d4a-9c68-0df32d6540c5device_ebe2ce74-5668-4c44-9099-21f5c8d690ccdevice_00f0e2b7-5893-45fb-a13e-c3389e6a7dbd': 'VmDevice {vmId=79f4a348-a928-45c4-85c6-b6bfc600d507, deviceId=00f0e2b7-5893-45fb-a13e-c3389e6a7dbd, device=spicevmc, type=CHANNEL, bootOrder=0, specParams={}, address={port=3, bus=0, controller=0, type=virtio-serial}, managed=false, plugged=true, readOnly=false, deviceAlias=channel2, customProperties={}, snapshotId=null}', 'device_c5d3d740-1c66-43d9-8f69-bbf70b17850fdevice_95d5fd25-7bdb-4c90-a0c0-e6e43fcc3eab': 'VmDevice {vmId=79f4a348-a928-45c4-85c6-b6bfc600d507, deviceId=95d5fd25-7bdb-4c90-a0c0-e6e43fcc3eab, device=virtio-serial, type=CONTROLLER, bootOrder=0, specParams={}, address={bus=0x00, domain=0x0000, type=pci, slot=0x05, function=0x0}, managed=false, plugged=true, readOnly=false, deviceAlias=virtio-serial0, customProperties={}, snapshotId=null}', 'device_c5d3d740-1c66-43d9-8f69-bbf70b17850fdevice_95d5fd25-7bdb-4c90-a0c0-e6e43fcc3eabdevice_ba80ae13-a054-4d4a-9c68-0df32d6540c5': 'VmDevice {vmId=79f4a348-a928-45c4-85c6-b6bfc600d507, deviceId=ba80ae13-a054-4d4a-9c68-0df32d6540c5, device=unix, type=CHANNEL, bootOrder=0, specParams={}, address={port=1, bus=0, controller=0, type=virtio-serial}, managed=false, plugged=true, readOnly=false, deviceAlias=channel0, customProperties={}, snapshotId=null}', 'device_c5d3d740-1c66-43d9-8f69-bbf70b17850fdevice_95d5fd25-7bdb-4c90-a0c0-e6e43fcc3eabdevice_ba80ae13-a054-4d4a-9c68-0df32d6540c5device_ebe2ce74-5668-4c44-9099-21f5c8d690cc': 'VmDevice {vmId=79f4a348-a928-45c4-85c6-b6bfc600d507, deviceId=ebe2ce74-5668-4c44-9099-21f5c8d690cc, device=unix, type=CHANNEL, bootOrder=0, specParams={}, address={port=2, bus=0, controller=0, type=virtio-serial}, managed=false, plugged=true, readOnly=false, deviceAlias=channel1, customProperties={}, snapshotId=null}', 'device_c5d3d740-1c66-43d9-8f69-bbf70b17850f': 'VmDevice {vmId=79f4a348-a928-45c4-85c6-b6bfc600d507, deviceId=c5d3d740-1c66-43d9-8f69-bbf70b17850f, device=ide, type=CONTROLLER, bootOrder=0, specParams={}, address={bus=0x00, domain=0x0000, type=pci, slot=0x01, function=0x1}, managed=false, plugged=true, readOnly=false, deviceAlias=ide0, customProperties={}, snapshotId=null}'}, 'smp': '1', 'vmType': 'kvm', 'memSize': 1024, 'smpCoresPerSocket': '1', 'vmName': 'rhel6_64', 'nice': '0', 'smartcardEnable': 'false', 'keyboardLayout': 'en-us', 'kvmEnable': 'true', 'pitReinjection': 'false', 'transparentHugePages': 'true', 'devices': [{'device': 'qxl', 'specParams': {'vram': '32768', 'ram': '65536', 'heads': '1'}, 'type': 'video', 'deviceId': '012a5c68-e3b1-4fe6-8e52-9f19ad944a05', 'address': {'slot': '0x02', 'bus': '0x00', 'domain': '0x0000', 'type': 'pci', 'function': '0x0'}}, {'index': '2', 'iface': 'ide', 'address': {'bus': '1', 'controller': '0', 'type': 'drive', 'target': '0', 'unit': '0'}, 'specParams': {'path': ''}, 'readonly': 'true', 'deviceId': '68eb044c-5c16-4786-ab47-58b4c8b19f00', 'path': '', 'device': 'cdrom', 'shared': 'false', 'type': 'disk'}, {'index': 0, 'iface': 'virtio', 'format': 'cow', 'bootOrder': '1', 'poolID': '00000002-0002-0002-0002-00000000018a', 'volumeID': 'fa5d06e7-02f8-4cb5-898d-6a4ae5cc6069', 'imageID': 'c12b35df-4a87-42f5-82e6-9de41f27d6e1', 'specParams': {}, 'readonly': 'false', 'domainID': 'ea3ab93d-c3d5-444c-aa54-f044013fb60d', 'optional': 'false', 'deviceId': 'c12b35df-4a87-42f5-82e6-9de41f27d6e1', 'address': {'slot': '0x06', 'bus': '0x00', 'domain': '0x0000', 'type': 'pci', 'function': '0x0'}, 'device': 'disk', 'shared': 'false', 'propagateErrors': 'off', 'type': 'disk'},{'nicModel': 'pv', 'macAddr': '00:1a:4a:a8:d8:6d', 'linkActive': 'true', 'network': 'rhevm', 'filter': 'vdsm-no-mac-spoofing', 'specParams': {}, 'deviceId': '8fda0ce3-b37f-4690-926f-24c09988e6f6', 'address': {'slot': '0x03', 'bus': '0x00', 'domain': '0x0000', 'type': 'pci', 'function': '0x0'}, 'device': 'bridge', 'type': 'interface'}, {'device': 'memballoon', 'specParams': {'model': 'virtio'}, 'type': 'balloon', 'deviceId': '3f558724-9415-4123-9b44-130d0562673c'}, {'index': '0', 'specParams': {}, 'deviceId': '40504d0a-5840-4269-a1b0-11debef211fe', 'address': {'slot': '0x04', 'bus': '0x00', 'domain': '0x0000', 'type': 'pci', 'function': '0x0'}, 'device': 'scsi', 'model': 'virtio-scsi', 'type': 'controller'}], 'maxVCpus': '160', 'spiceSecureChannels': 'smain,sinputs,scursor,splayback,srecord,sdisplay,susbredir,ssmartcard', 'display': 'qxl'}


        self.do_connect(destHostStart, VDSM_PORT)
        #print cmd
        #cmd1 = dict(cmd)
        #print cmd1
        ret = self.s.create(cmd)
        #print ret
        print "Triggered VM [%s]" % self.vmName

    def usage(self):
        """shows the program params"""
        print "Usage: " + sys.argv[0] + " [OPTIONS]"
        print "\t--destHost      \t Hypervisor host which will start the VM"
        print "\t--otherHostsList\t All remaining hosts"
        print "\t--vms           \t Specify the Names of which VMs to start"
        print "\t--version        \t List version release"
        print "\t--help           \t This help menu\n"

        print "Example:"
        print "\t" + sys.argv[0] + " --destHost LinuxSrv1 --otherHostsList Megatron,Jerry --vms vm1,vm2,vm3,vm4"
        sys.exit(1)


if __name__ == "__main__":

    otherHostsList = ''
    VmsToStart = None
    destHostStart = None
    
    #import pdb; pdb.set_trace()

    VE = vdsmEmergency()
    try:
        opts, args = getopt.getopt(sys.argv[1:], "Vd:ho:v:", ["destHost=", "otherHostsList=", "vms=", "help", "version"])
    except getopt.GetoptError, err:
        # print help information and exit:
        print(err) # will print something like "option -a not recognized"
        VE.usage()
        sys.exit(2)
    for o, a in opts:
        if o in ("-d", "--destHost"):
            destHostStart = a
            print ""
        elif o in ("-h", "--help"):
            VE.usage()
            sys.exit()
        elif o in ("-o", "--otherHostsList"):
            otherHostsList = a
        elif o in ("-v", "--vms"):
            VmsToStart = a
        elif o in ("-V", "--version"):
            print VERSION
        else:
            assert False, "unhandled option"

    argc = len(sys.argv)
    if argc < 2:
        VE.usage()

    VE.checkSPM()

    # Include the destHost to verify
    otherHostsList += ",%s" % destHostStart
    VE.checkVmRunning(otherHostsList, VmsToStart)

    VE.readXML(VmsToStart, destHostStart)
