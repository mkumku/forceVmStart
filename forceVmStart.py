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
DEBUG = False # True or False

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


    def checkVmRunning(self, otherHostsList):
        """check if the vm's are running"""

        if otherHostsList == None:
            return -1

        i = 0
        hosts = None
        hosts = otherHostsList.split(",")
        self.upVms = {} # dict by vm_uuid, to hold vmStatus and host
        
        # Let's scan all the hosts and make a list of VMs that are running now 
        # running == appears on vdsClient list output == vmStatus<>Down
        while (i < len(hosts)):
            ret = VE.do_connect(hosts[i], VDSM_PORT)
            if ret < 0:
                sys.exit(1)
            response = self.s.list()
            if response['status']['code'] != 0:
                print "cannot execute list operation, err:" + response['status']['message']

            # Checking VM status
            for s in self.s.getAllVmStats()['statsList']:
                vmId = s['vmId']
                vmStatus = s['status']
                
                self.upVms[vmId]= {}
                self.upVms[vmId]['status'] = vmStatus
                self.upVms[vmId]['host'] = hosts[i]
 
            i = i + 1
        if DEBUG: print 'Vms found up: %s' % self.upVms 

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

    def readXML(self, VmsToStart, destHostStart):
        """read all xml available pointed to Directory path and parse for specific fields"""

        global DEBUG

        # number of Vms found
        foundVmsNum = 0
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
            isTmplt = False
            for node in dom.getElementsByTagName('Section'):
                while (i < len(node.attributes)):
                    attr = node.attributes.items()
                    if attr[i][0] == "ovf:id":
                        self.vmId = attr[i][1]
                        cmd["vmId"] = self.vmId
                        #if DEBUG: print 'vmId: %s' % cmd["vmId"]
                    i = i + 1

            for node in dom.getElementsByTagName('Content'):
                # Getting vmName field
                if node.getElementsByTagName('Name'):
		    if node.getElementsByTagName('Name')[0].firstChild <> None:
                        self.vmName = node.getElementsByTagName('Name')[0].firstChild.data
                        cmd['vmName'] = self.vmName
			#if DEBUG: DEBUG = (self.vmName == 'rhel6_64') or (self.vmName == 'rhel7_64') 
			#if DEBUG: print 'self.vmName = %s' % self.vmName
                    else:
                        print 'No vmName attribute for vmId %s, continue to next ovf' % cmd[vmId]
                 

                # Getting display driver:
                if node.getElementsByTagName('DefaultDisplayType'):
                    if node.getElementsByTagName('DefaultDisplayType')[0].firstChild <> None:
                        cmd['display'] = 'qxl' if node.getElementsByTagName('DefaultDisplayType')[0].firstChild.data == '1' else 'vnc'
                        #if DEBUG: print cmd['display']
                else:
                    isTmplt = True
                    #if DEBUG: print 'Template has no display value'
               
            # check if the vm is in the list and do not parse anymore 
            if not self.vmName in VmsToStart: 
                 #if DEBUG: print "Vm %s is not in the list of Vms to Start" % self.vmName
                 continue                
            foundVmsNum += 1
            
            if isTmplt:
                print "Vm %s is a template, cannot run template" % self.vmName
                continue  
                
            # Getting VM disks info
            # Get only Active Vm snapshots:
            devices = []
            volumes = {}
            for node in dom.getElementsByTagName('File'):
                attr = node.attributes.items()
                i = 0
	        while (i < len(attr)):
                    if attr[i][0] == "ovf:description":
                        isLeaf = (attr[i][1]=="Active VM")
                    # Getting image and volume
                    if attr[i][0] == "ovf:href":
                        data = attr[i][1].split("/")
                        image = data[0]
                        vol = data[1]
                        #if DEBUG: print 'img/vol: %s' % data
                    i += 1
                if isLeaf: 
                   volumes[vol] = {}
                   volumes[vol]['device'] = 'disk'
                   volumes[vol]['type'] = 'disk'
                   volumes[vol]['propagateErrors'] = 'off' # since today this is the only supported option, and it is not in ovf
                   volumes[vol]['imageID'] = volumes[vol]['deviceId'] = image
                   volumes[vol]['volumeID'] = vol
			
                   # Getting Pool and SD values:
                   for item in dom.getElementsByTagName('Item'):
                       if vol == item.getElementsByTagName('rasd:InstanceId')[0].firstChild.data:
                           volumes[vol]['domainID'] = item.getElementsByTagName('rasd:StorageId')[0].firstChild.data
                           volumes[vol]['poolID'] = item.getElementsByTagName('rasd:StoragePoolId')[0].firstChild.data
                           break
                   
                   # Getting additional attributes:
                   for disk in dom.getElementsByTagName('Disk'):
                       d_attr = disk.attributes.items()
                       j = 0
                       isMatch = False
                       while (j < len(d_attr)):
                           if d_attr[j][0] == "ovf:diskId":
                               if vol <> d_attr[j][1]:
                                   break
                               else:
                                   isMatch = True

                           if d_attr[j][0] == "ovf:volume-format":
                               vmFormat = "cow" if d_attr[j][1]=="COW" else "raw"

                           if d_attr[j][0] == "ovf:boot":
                               vmBoot = '1' if d_attr[j][1] == 'true' else '0'

                           if d_attr[j][0] == "ovf:disk-interface":
                               ifDisk = "virtio" if d_attr[j][1] == "VirtIO" else "ide"
      
                           j += 1
                           
                       if isMatch:
                           if vmBoot == '1': volumes[vol]['bootOrder'] = vmBoot
                           volumes[vol]['iface'] = ifDisk
                           volumes[vol]['format'] = vmFormat
                           break

            #if DEBUG: print 'Active Volumes: %s' % volumes

            for dev in volumes: 
                devices.append(volumes[dev])

            # Getting VM nics info
            networks = {}
            for node in dom.getElementsByTagName('Nic'):
                nic = node.attributes.items()[0][1]  
                networks[nic] = {} 
                networks[nic]['device'] = 'bridge'
                networks[nic]['type'] = 'interface'
                networks[nic]['deviceId'] = nic
			
                for item in dom.getElementsByTagName('Item'):
                   if nic == item.getElementsByTagName('rasd:InstanceId')[0].firstChild.data:
                       networks[nic]['macAddr'] = item.getElementsByTagName('rasd:MACAddress')[0].firstChild.data
                       
                       networks[nic]['linkActive'] = item.getElementsByTagName('rasd:Linked')[0].firstChild.data
                       networks[nic]['network'] = item.getElementsByTagName('rasd:Connection')[0].firstChild.data
                        
                       nicMod = "pv"
                       nicSubType = item.getElementsByTagName('rasd:ResourceSubType')[0].firstChild.data
                       if nicSubType == "3":
                           nicMod = "pv" #VirtIO
                       elif nicSubType == "2":
                           nicMod = "e1000" #e1000
                       elif nicSubType == "1":
                           nicMod = "rtl8139" #rtl8139

                       networks[nic]['nicModel'] = nicMod
                       break

                #if DEBUG: print 'networks: %s' % networks
                devices.append(networks[nic])
            
            # Finally now update cmd with all the devices: disks and networks 
            cmd['devices'] = devices
            #if DEBUG: print 'cmd[devices]: %s' % cmd['devices']

            # Getting memSize, macAddr, smp, smpCoresPerSocket
            for node in dom.getElementsByTagName('Item'):
                    
                # Getting memSize field
                str = node.getElementsByTagName('rasd:Caption')[0].firstChild.data
                if str.find("MB of memory") > -1:
                    cmd['memSize'] = node.getElementsByTagName('rasd:VirtualQuantity')[0].firstChild.data

                # Getting smp and smpCoresPerSocket fields
                str = node.getElementsByTagName('rasd:Caption')[0].firstChild.data
                if str.find("virtual cpu") > -1:
                    cmd["smp"] = node.getElementsByTagName('rasd:num_of_sockets')[0].firstChild.data
                    cmd["smpCoresPerSocket"] = node.getElementsByTagName('rasd:cpu_per_socket')[0].firstChild.data

            self.startVM(cmd, destHostStart)
            if DEBUG: print "Printing cmd: %s" % cmd
    
        if DEBUG: print 'Total Vms found: %s' % foundVmsNum   
        if foundVmsNum == 0:
            print 'Requested Vms were not found in the system'
                
    def checkVmStatus(self):
        """ Check if current VM is not running already somewhere """

        if self.vmId in self.upVms.keys():
            print ("Vm %s would not be started! It is in status %s on host %s." % 
                (self.vmName, self.upVms[self.vmId]['status'], self.upVms[self.vmId]['host']))
            return 1
        return 0        
 

    def startVM(self, cmd, destHostStart):
        """start the VM"""

        ret = self.checkVmStatus()
        if ret <> 0: return

        self.do_connect(destHostStart, VDSM_PORT)
        ret = self.s.create(cmd)
        print "Triggered VM [%s] start" % self.vmName

    def usage(self):
        """shows the program params"""
        print "Usage: " + sys.argv[0] + " [OPTIONS]"
        print "\t--destHost      \t Hypervisor host which will start the VM"
        print "\t--otherHostsList\t All remaining hosts, if single host in Data Center, use 127.0.0.1"
        print "\t--vms           \t Specify the Names of which VMs to start"
        print "\t--debug         \t Enable Debug outputs"
        print "\t--version        \t List version release"
        print "\t--help           \t This help menu\n"

        print "Example:"
        print "\t" + sys.argv[0] + " --destHost LinuxSrv1 --otherHostsList Megatron,Jerry --vms vm1,vm2,vm3,vm4"
        sys.exit(1)


if __name__ == "__main__":

    otherHostsList = ''
    VmsToStart = None
    destHostStart = None
    
    VE = vdsmEmergency()
    try:
        opts, args = getopt.getopt(sys.argv[1:], "Vd:ho:v:D", ["destHost=", "otherHostsList=", "vms=", "help", "version", "debug"])
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
        elif o in ("-D", "--debug"):
            DEBUG = True
            print 'Debug mode enabled'
        elif o in ("-V", "--version"):
            print VERSION
        else:
            assert False, "unhandled option"

    argc = len(sys.argv)
    if argc < 2:
        VE.usage()
   
    if otherHostsList == "":
        print 'Must provide otherHostsList!'
        VE.usage()
     
    try:
        VmsToStart = VmsToStart.split(",")
    except:
        print "Please use , between vms name, avoid space"
        VE.usage()

    VE.checkSPM()

    # Include the destHost to verify
    otherHostsList += ",%s" % destHostStart
    VE.checkVmRunning(otherHostsList)

    # Read ovf files and start the vms found
    VE.readXML(VmsToStart, destHostStart)
