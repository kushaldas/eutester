# Software License Agreement (BSD License)
#
# Copyright (c) 2009-2011, Eucalyptus Systems, Inc.
# All rights reserved.
#
# Redistribution and use of this software in source and binary forms, with or
# without modification, are permitted provided that the following conditions
# are met:
#
#   Redistributions of source code must retain the above
#   copyright notice, this list of conditions and the
#   following disclaimer.
#
#   Redistributions in binary form must reproduce the above
#   copyright notice, this list of conditions and the
#   following disclaimer in the documentation and/or other
#   materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
# Author: vic.iglesias@eucalyptus.com

from eutester import Eutester
import time
import re
import sys
import os
import pprint
import boto
from boto.ec2.image import Image
from boto.ec2.instance import Reservation
from boto.ec2.volume import Volume
from boto.ec2.blockdevicemapping import BlockDeviceMapping, BlockDeviceType
from boto.exception import EC2ResponseError
from eutester.euinstance import EuInstance

class EC2ops(Eutester):
    def __init__(self, config_file=None, password=None, keypath=None, credpath=None, aws_access_key_id=None, aws_secret_access_key = None,account="eucalyptus",user="admin", username="root",region=None, boto_debug=0):
        super(EC2ops, self).__init__(config_file=config_file,password=password, keypath=keypath, credpath=credpath, aws_access_key_id=aws_access_key_id, aws_secret_access_key=aws_secret_access_key,account=account, user=user, region=region, boto_debug=boto_debug)
        self.poll_count = 48
        self.username = username
        if self.hypervisor is "vmware":
            self.poll_count = 96
        self.test_resources = {}
        self.setup_ec2_resource_trackers()
        
    def setup_ec2_resource_trackers(self):
        """
        Setup keys in the test_resources hash in order to track artifacts created
        """
        self.test_resources["reservations"] = []
        self.test_resources["volumes"] = []
        self.test_resources["snapshots"] = []
        self.test_resources["keypairs"] = []
        self.test_resources["security-groups"] = []
        self.test_resources["images"] = []
    
    def add_keypair(self,key_name=None):
        """
        Add a keypair with name key_name unless it already exists
        key_name      The name of the keypair to add and download.
        """
        if key_name==None:
            key_name = "keypair-" + str(int(time.time())) 
        self.debug(  "Looking up keypair " + key_name )
        key = []
        try:
            key = self.ec2.get_all_key_pairs(keynames=[key_name])    
        except EC2ResponseError:
            pass
        
        if key == []:
            self.debug( 'Creating keypair: %s' % key_name)
            # Create an SSH key to use when logging into instances.
            key = self.ec2.create_key_pair(key_name)
            # AWS will store the public key but the private key is
            # generated and returned and needs to be stored locally.
            # The save method will also chmod the file to protect
            # your private key.
            key.save(self.key_dir)
            self.test_resources["keypairs"].append(key)
            return key
        else:
            self.debug(  "Key " + key_name + " already exists")
            
            
            
    def verify_local_keypath(self,keyname, path=None, exten=".pem"):
        '''
        Convenience function to verify if a given ssh key 'keyname' exists on the local server at 'path'
        Returns the keypath if the key is found.
        Example:
        instance= self.get_instances(state='running')[0]
        keypath = self.get_local_keypath(instance.key_name)
        '''
        if (path is None):
            path = os.getcwd()
        keypath = path + "/" + keyname + exten
        try:
            mode = os.stat(keypath).st_mode
        except:
            raise Exception("key:"+keyname+"not found at the provided path:"+str(path))
        return keypath
    
    def get_all_current_local_keys(self,path=None, exten=".pem"):
        '''
        Convenience function to provide a list of all keys in the local dir at 'path'
        that exist on the server. To help avoid additional keys in test dev. 
        '''
        keylist = []
        keys = self.ec2.get_all_key_pairs()
        for k in keys:
            try:
                self.verify_local_keypath(k.name, path, exten)
                self.debug('Found key:'+k.name)
                keylist.append(k)
            except: pass
        return keylist
            
        
    def delete_keypair(self,keypair):
        """
        Delete the keypair object passed in and check that it no longer shows up
        keypair      Keypair object to delete and check
        """
        name = keypair.name
        self.debug(  "Sending delete for keypair: " + name)
        keypair.delete()
        try:
            keypair = self.ec2.get_all_key_pairs(keynames=[name])
        except EC2ResponseError:
            keypair = []
            
        if len(keypair) > 0:
            self.fail("Keypair found after attempt to delete it")
            return False
        return True
    
    def add_group(self, group_name=None, fail_if_exists=False ):
        """
        Add a security group to the system with name group_name, if it exists dont create it
        group_name      Name of the security group to create
        fail_if_exists  IF set, will fail if group already exists, otherwise will return the existing group
        returns boto group object upon success or None for failure
        """
        group=None
        if group_name == None:
            group_name = "group-" + str(int(time.time()))
        if self.check_group(group_name):
            if ( fail_if_exists == True ):
                self.fail(  "Group " + group_name + " already exists")
            else:
                self.debug(  "Group " + group_name + " already exists")
                group = self.ec2.get_all_security_groups(group_name)[0]
            self.test_resources["security-groups"].append(group)
            return group
        else:
            self.debug( 'Creating Security Group: %s' % group_name)
            # Create a security group to control access to instance via SSH.
            group = self.ec2.create_security_group(group_name, group_name)
        return group
    
    def delete_group(self, group):
        """
        Delete the group object passed in and check that it no longer shows up
        group      Group object to delete and check
        """
        name = group.name
        self.debug( "Sending delete for group: " + name )
        group.delete()
        if self.check_group(name):
            self.fail("Group found after attempt to delete it")
            return False
        return True
    
    def check_group(self, group_name):
        """
        Check if a group with group_name exists in the system
        group_name      Group name to check for existence
        """
        self.debug( "Looking up group " + group_name )
        try:
            group = self.ec2.get_all_security_groups(groupnames=[group_name])
        except EC2ResponseError:
            return False
        
        if group == []:
            return False
        else:
            return True    
    
    def authorize_group_by_name(self,group_name="default", port=22, protocol="tcp", cidr_ip="0.0.0.0/0"):
        """
        Authorize the group with group_name, 
        group_name      Name of the group to authorize, default="default"
        port            Port to open, default=22
        protocol        Protocol to authorize, default=tcp
        cidr_ip         CIDR subnet to authorize, default="0.0.0.0/0" everything
        """
        try:
            self.debug( "Attempting authorization of " + group_name + " on port " + str(port) + " " + protocol )
            self.ec2.authorize_security_group_deprecated(group_name,ip_protocol=protocol, from_port=port, to_port=port, cidr_ip=cidr_ip)
            return True
        except self.ec2.ResponseError, e:
            if e.code == 'InvalidPermission.Duplicate':
                self.debug( 'Security Group: %s already authorized' % group_name )
            else:
                raise
            
    def authorize_group(self,group, port=22, protocol="tcp", cidr_ip="0.0.0.0/0"):
        """
        Authorize the group with group_name, 
        group_name      Name of the group to authorize, default="default"
        port            Port to open, default=22
        protocol        Protocol to authorize, default=tcp
        cidr_ip         CIDR subnet to authorize, default="0.0.0.0/0" everything
        """
        return self.authorize_group_by_name(group.name, port, protocol, cidr_ip) 
    
    def wait_for_instance(self,instance, state="running", poll_count = None):
        """
        Wait for the instance to enter the state
        instance      Boto instance object to check the state on
        state        state that we are looking for
        """
        if poll_count is None:
            poll_count = self.poll_count
        self.debug( "Beginning poll loop for instance " + str(instance) + " to go to " + str(state) )
        instance.update()
        instance_original_state = instance.state
        start = time.time()
        elapsed = 0
        ### If the instance changes state or goes to the desired state before my poll count is complete
        while( poll_count > 0) and (instance.state != state):
            poll_count -= 1
            self.debug( "Instance("+instance.id+") State("+instance.state+"), elapsed:"+str(elapsed))
            time.sleep(10)
            instance.update()
            elapsed = int(time.time()- start)
            if (instance.state != instance_original_state):
                break
        self.debug("Instance("+instance.id+") State("+instance.state+") Poll("+str(self.poll_count-poll_count)+") time elapsed (" +str(elapsed).split('.')[0]+")")
        #self.debug( "Waited a total o" + str( (self.poll_count - poll_count) * 10 ) + " seconds" )
        if instance.state != state:
            self.fail(str(instance) + " did not enter the proper state and was left in " + instance.state)
            raise Exception( str(instance) + " did not enter proper state")
        self.debug( str(instance) + ' is now in ' + instance.state )
        return True

    def wait_for_reservation(self,reservation, state="running"):
        """
        Wait for the an entire reservation to enter the state
        reservation  Boto reservation object to check the state on
        state        state that we are looking for
        """
        self.debug( "Beginning poll loop for the " + str(len(reservation.instances))   + " found in " + str(reservation) )
        aggregate_result = True
        for instance in reservation.instances:
            if self.wait_for_instance(instance, state) == False:
                aggregate_result = False
        return aggregate_result
    
    def create_volume(self, azone, size=1, snapshot=None): 
        """
        Create a new EBS volume then wait for it to go to available state, size or snapshot is mandatory
        azone        Availability zone to create the volume in
        size         Size of the volume to be created
        snapshot     Snapshot to create the volume from
        """
        # Determine the Availability Zone of the instance
        poll_count = self.poll_count
        poll_interval = 10
        self.debug( "Sending create volume request" )
        volume = self.ec2.create_volume(size, azone, snapshot)
        # Wait for the volume to be created.
        self.debug( "Polling for volume to become available")
        while volume.status != 'available' and (poll_count > 0):
            poll_count -= 1
            self.debug("Volume ("+volume.id+") State("+volume.status+") sleeping " + str(poll_interval) + "s")
            time.sleep(poll_interval)
            volume.update()
            self.debug( str(volume) + " in " + volume.status +" state") 
            if volume.status == 'failed':
                self.fail(str(volume) + " went to: " + volume.status)
                return None  
        if poll_count == 0:
            self.fail(str(volume) + " never went to available and stayed in " + volume.status)
            self.debug( "Deleting volume that never became available")
            volume.delete()
            return None
        self.debug( "Done. Waited a total of " + str( (self.poll_count - poll_count) * poll_interval) + " seconds" )
        self.test_resources["volumes"].append(volume)
        return volume
    
    def delete_volume(self, volume):
        """
        Delete the EBS volume then check that it no longer exists
        volume        Volume object to delete
        """
        self.ec2.delete_volume(volume.id)
        self.debug( "Sent delete for volume: " +  volume.id  )
        poll_count = 10
        volume.update()
        while ( volume.status != "deleted") and (poll_count > 0):
            poll_count -= 1
            volume.update()
            self.debug( str(volume) + " in " + volume.status + " sleeping 10s")
            self.sleep(10)

        if poll_count == 0:
            self.fail(str(volume) + " left in " +  volume.status)
            return False
        return True
    
    def delete_all_volumes(self):
        """
        Deletes all volumes on the cloud
        """
        volumes = self.ec2.get_all_volumes()
        for volume in volumes:
            self.delete_volume(volume.id)
    
    def attach_volume(self, instance, volume, device_path, pause=10, timeout=60):
        """
        Attach a volume to an instance
        instance    instance object to attach volume to
        volume      volume object to attach
        device_path device name to request on guest
        """
        self.debug("Sending attach for " + str(volume) + " to be attached to " + str(instance) + " at device node " + device_path)
        volume.attach(instance.id,device_path )
        start = time.time()
        elapsed = 0  
        volume.update()
        while (elapsed < timeout):
            volume.update()
            if (volume.attach_data is not None) and (volume.attach_data.status is not None) :
                if re.search("attached",volume.attach_data.status):
                    return True
            self.debug( str(volume) + " state:" + volume.status + " pause:"+str(pause)+" elapsed:"+str(elapsed))
            self.sleep(pause)
            elapsed = int(time.time()-start)

        self.fail(str(volume) + " left in " +  volume.status)
        return False
      
    
    def detach_volume(self, volume, pause = 10, timeout=60):
        """
        Detach a volume
        volume   volume to detach
        """
        if volume == None:
            self.fail("Volume does not exist")
            return False
        volume.detach()
        self.debug( "Sent detach for volume: " + volume.id + " which is currently in state: " + volume.status)
        start = time.time()
        elapsed = 0  
        while (elapsed < timeout):
            volume.update()
            if ( volume.status != "in-use"):
                self.debug(str(volume) + " left in " +  volume.status)
                return True
            self.debug( str(volume) + " state:" + volume.status + " pause:"+str(pause)+" elapsed:"+str(elapsed))
            self.sleep(pause)
            elapsed = int(time.time() - start)
        self.fail(str(volume) + " left in " +  volume.status)
        return False
    
    def create_snapshot(self, volume_id, description="", waitOnProgress=0, poll_interval=10, timeout=0):
        """
        Create a new EBS snapshot from an existing volume then wait for it to go to the created state. By default will poll for poll_count.
        If waitOnProgress is specified than will wait on "waitOnProgress" # of poll_interval periods w/o progress before failing
        An overall timeout can be given for both methods, by default the timeout is not used.    
        volume_id        (mandatory string) Volume id of the volume to create snapshot from
        description      (optional string) string used to describe the snapshot
        waitOnProgress   (optional integer) # of poll intervals to wait while 0 progress is made before exiting, overrides "poll_count" when used
        poll_interval    (optional integer) time to sleep between polling snapshot status
        timeout          (optional integer) over all time to wait before exiting as failure
        returns snapshot 
        """
        if (waitOnProgress > 0 ):
            poll_count = waitOnProgress
        else:
            poll_count = self.poll_count
        curr_progress = 0 
        last_progress = 0
        elapsed = 0
        polls = 0
        snap_start = time.time()

        snapshot = self.ec2.create_snapshot( volume_id )
        self.debug("Waiting for snapshot (" + snapshot.id + ") creation to complete")
        while ( (poll_count > 0) and ((timeout == 0) or (elapsed <= timeout)) ):
            time.sleep(poll_interval)
            polls += 1
            snapshot.update()
            if ( snapshot.status == 'failed'):
                self.fail(str(snapshot) + " failed after Polling("+str(polls)+") ,Waited("+str(elapsed)+" sec), last reported (status:" + snapshot.status+" progress:"+snapshot.progress+")")
                return None
            curr_progress = int(snapshot.progress.replace('%',''))
            #if progress was made, then reset timer 
            if ((waitOnProgress > 0) and (curr_progress > last_progress)):
                poll_count = waitOnProgress
            else: 
                poll_count -= 1
            elapsed = int(time.time()-snap_start)
            self.debug("Snapshot:"+snapshot.id+" Status:"+snapshot.status+" Progress:"+snapshot.progress+" Polls:"+str(polls)+" Time Elapsed:"+str(elapsed))    
            if (snapshot.status == 'completed'):
                self.debug("Snapshot created after " + str(elapsed) + " seconds. " + str(polls) + " X ("+str(poll_interval)+" second) polling invervals. Status:"+snapshot.status+", Progress:"+snapshot.progress)
                self.test_resources["snapshots"].append(snapshot)
                return snapshot
        #At least one of our timers has been exceeded, fail and exit 
        self.fail(str(snapshot) + " failed after Polling("+str(polls)+") ,Waited("+str(elapsed)+" sec), last reported (status:" + snapshot.status+" progress:"+snapshot.progress+")")
        self.debug("Deleting snapshot("+snapshot.id+"), never progressed to 'created' state")
        snapshot.delete()
        return None
        
    
    def delete_snapshot(self,snapshot):
        """Delete the snapshot object"""
        snapshot.delete()
        self.debug( "Sent snapshot delete request for snapshot: " + snapshot.id)
        poll_count = 5
        while ( len(self.ec2.get_all_snapshots(snapshot_ids=[snapshot.id])) > 0) and (poll_count > 0):
            poll_count -= 1
            self.sleep(10)
        if poll_count == 0:
            self.fail(str(snapshot) + " left in " +  snapshot.status + " with " + str(snapshot.progress) + "% progress")
        return snapshot
    
    def register_snapshot(self, snapshot, rdn="/dev/sda1", description="bfebs", windows=False, bdmdev=None, name=None, ramdisk=None, kernel=None, dot=True):
        '''Convience function for passing a snapshot instead of its id'''
        return self.register_snapshot_by_id( snapshot.id, rdn, description, windows, bdmdev, name, ramdisk, kernel, dot )
        
    def register_snapshot_by_id( self, snap_id, rdn="/dev/sda1", description="bfebs", windows=False, bdmdev=None, name=None, ramdisk=None, kernel=None, dot=True ):
        '''
        Register an image snapshot
        snap_id        (mandatory string) snapshot id
        name           (mandatory string) name of image to be registered
        description    (optional string) description of image to be registered
        bdmdev         (optional string) block-device-mapping device for image
        rdn            (optional string) root-device-name for image
        dot            (optional boolean) Delete On Terminate boolean
        windows        (optional boolean) Is windows image boolean
        kernel         (optional string) kernal (note for windows this name should be "windows"
        '''
        
        if (bdmdev is None):
            bdmdev=rdn
        if (name is None):
            name="bfebs_"+ snap_id
        if ( windows is True ) and ( kernel is not None):
            kernel="windows"     
            
        bdmap = BlockDeviceMapping()
        block_dev_type = BlockDeviceType()
        block_dev_type.snapshot_id = snap_id
        block_dev_type.delete_on_termination = dot
        bdmap[bdmdev] = block_dev_type
            
        self.debug("Register image with: snap_id:"+str(snap_id)+", rdn:"+str(rdn)+", desc:"+str(description)+", windows:"+str(windows)+", bdname:"+str(bdmdev)+", name:"+str(name)+", ramdisk:"+str(ramdisk)+", kernel:"+str(kernel))
        image_id = self.ec2.register_image(name=name, description=description, kernel_id=kernel, ramdisk_id=ramdisk, block_device_map=bdmap, root_device_name=rdn)
        self.debug("Image now registered as " + image_id)
        return image_id
        
    def register_image( self, snap_id, rdn=None, description=None, image_location=None, windows=False, bdmdev=None, name=None, ramdisk=None, kernel=None ):
        '''
        Register an image snapshot
        snap_id        (optional string) snapshot id
        name           (optional string) name of image to be registered
        description    (optional string) description of image to be registered
        bdm            (optional block_device_mapping) block-device-mapping object for image
        rdn            (optional string) root-device-name for image
        kernel         (optional string) kernal (note for windows this name should be "windows"
        image_location (optional string) path to s3 stored manifest 
        '''

        image_id = self.ec2.register_image(name=name, description=description, kernel_id=kernel, image_location=image_location, ramdisk_id=ramdisk, block_device_map=bdmdev, root_device_name=rdn)
        self.test_resources["images"].append(image_id)
        return image_id
    
    def get_emi(self, emi=None, root_device_type=None, root_device_name=None, location=None, state="available", arch=None, owner_id=None):
        """
        Get an emi with name emi, or just grab any emi in the system. Additional 'optional' match criteria can be defined.
        emi              (mandatory) Partial ID of the emi to return, defaults to the 'emi-" prefix to grab any
        root_device_type (optional string)  example: 'instance-store' or 'ebs'
        root_device_name (optional string)  example: '/dev/sdb' 
        location         (optional string)  partial on location match example: 'centos'
        state            (optional string)  example: 'available'
        arch             (optional string)  example: 'x86_64'
        owner_id         (optional string) owners numeric id
        """
        if emi is None:
            emi = "mi-"
        self.debug("Looking for image prefix: " + str(emi) )
            
        images = self.ec2.get_all_images()
        for image in images:
            
            if not re.search(emi, image.id):      
                continue  
            if ((root_device_type is not None) and (image.root_device_type != root_device_type)):
                continue            
            if ((root_device_name is not None) and (image.root_device_name != root_device_name)):
                continue       
            if ((state is not None) and (image.state != state)):
                continue            
            if ((location is not None) and (not re.search( location, image.location))):
                continue           
            if ((arch is not None) and (image.architecture != arch)):
                continue                
            if ((owner_id is not None) and (image.owner_id != owner_id)):
                continue
            
            return image
        raise Exception("Unable to find an EMI")
        return None
    
    def allocate_address(self):
        """
        Allocate an address for the current user
        """
        try:
            self.debug("Allocating an address")
            address = self.ec2.allocate_address()
        except Exception, e:
            self.critical("Unable to allocate address")
            return False
        self.debug("Allocated " + str(address))
        return address
    
    def associate_address(self,instance, address):
        """ Associate an address object with an instance"""
        try:
            self.debug("Attemtping to associate " + str(address) + " from " + str(instance))
            address.associate(instance.id)
        except Exception as (errno, strerror):
            self.critical("Unable to associate address\n")
            self.critical( "Exception({0}): {1}".format(errno, strerror))
            return False
        self.debug("Associated IP successfully")
        return address
    
    def disassociate_address_from_instance(self, instance):
        """Disassociate address from instance and ensure that it no longer holds the IP
        instance     An instance that has an IP allocated"""
        address = self.ec2.get_all_addresses(addresses=[instance.public_dns_name])[0]
        try:
            address.disassociate()
        except Exception, e:
            self.critical("Unable to disassociate address\n" + str(e))
            return False
        self.sleep(15)
        address = self.ec2.get_all_addresses(addresses=[instance.public_dns_name])
        if address.instance_id is instance.id:
            self.critical("Address still associated with instance")
            return False
        return True
        
    
    def ping(self, address, poll_count = 10):
        '''
        Ping an IP and poll_count times (Default = 10)
        address      Hostname to ping
        poll_count   The amount of times to try to ping the hostname iwth 2 second gaps in between
        ''' 
        found = False
        if re.search("0.0.0.0", address): 
            self.critical("Address is all 0s and will not be able to ping it") 
            return False
        self.debug("Attempting to ping " + address)
        while (poll_count > 0):
            poll_count -= 1 
            if self.found("ping -c 1 " + address, "1 received"):
                self.debug("Was able to ping address")
                return True
            if poll_count == 0:
                self.critical("Was unable to ping address")
                return False
            self.debug("Ping unsuccessful retrying in 2 seconds")
            self.sleep(2)
            
    
    def check_device(self, device_path):
        """Used with instance connections. Checks if a device at a certain path exists"""
        return self.found("ls -1 " + device_path, device_path)
        
    def get_volume(self, volume_id="vol-", status=None, attached_instance=None, attached_dev=None, snapid=None, zone=None, minsize=1, maxsize=None):
        '''
        Return first volume that matches the criteria. Criteria options to be matched:
        volume_id         (optional string) string present within volume id
        status            (optional string) examples: 'in-use', 'creating', 'available'
        attached_instance (optional string) instance id example 'i-1234abcd'
        attached_dev      (optional string) example '/dev/sdf'
        snapid            (optional string) snapshot volume was created from example 'snap-1234abcd'
        zone              (optional string) zone of volume example 'PARTI00'
        minsize           (optional integer) minimum size of volume to be matched
        maxsize           (optional integer) maximum size of volume to be matched
        '''
        if (attached_instance is not None) or (attached_dev is not None):
            status='in-use'
    
        volumes = self.ec2.get_all_volumes()
        for volume in volumes:
            if not re.match(volume_id, volume.id):
                continue
            if (snapid is not None) and (volume.snapshot_id != snapid):
                continue
            if (zone is not None) and (volume.zone != zone):
                continue
            if (status is not None):
                if (volume.status != status):
                    continue
                else:
                    if (attached_instance is not None) and ( volume.attach_data.instance_id != attached_instance):
                        continue
                    if (attached_dev is not None) and (volume.attach_data.device != attached_dev):
                        continue
            if not (volume.size >= minsize) and ((maxsize is None) or (volume.size <= maxsize)):
                continue
            return volume
        raise Exception("Unable to find matching volume")
        return None


    def run_instance(self, image=None, keypair=None, group="default", type=None, zone=None, min=1, max=1, user_data=None,private_addressing=False, username="root", password=None, is_reachable=True):
        """
        Run instance/s and wait for them to go to the running state
        image      Image object to use, default is pick the first emi found in the system
        keypair    Keypair name to use for the instances, defaults to none
        group      Security group name to apply to this set of instnaces, defaults to none
        type       VM type to use for these instances, defaults to m1.small
        zone       Availability zone to run these instances
        min        Minimum instnaces to launch, default 1
        max        Maxiumum instances to launch, default 1
        private_addressing  Runs an instance with only private IP address
        """
        if image == None:
            images = self.ec2.get_all_images()
            for emi in images:
                if re.match("emi",emi.name):
                    image = emi      
        if image is None:
            raise Exception("emi is None. run_instance could not auto find an emi?")   

        if private_addressing is True:
            addressing_type = "private"
        else:
            addressing_type = None
            
        self.debug( "Attempting to run "+ str(image.root_device_type)  +" image " + str(image) + " in group " + str(group))
        reservation = image.run(key_name=keypair,security_groups=[group],instance_type=type, placement=zone, min_count=min, max_count=max, user_data=user_data, addressing_type=addressing_type)
        if ((len(reservation.instances) < min) or (len(reservation.instances) > max)):
            self.fail("Reservation:"+str(reservation.id)+" returned "+str(len(reservation.instances))+" instances, not within min("+str(min)+") and max("+str(max)+" ")
        
        try:
            self.wait_for_reservation(reservation)
        except Exception, e:
            self.critical("An instance did not enter proper state in " + str(reservation) )
            self.critical("Terminatng instances in " + str(reservation))
            self.terminate_instances(reservation)
            raise Exception("Instances in " + str(reservation) + " did not enter proper state")
        
        for instance in reservation.instances:
            if instance.state != "running":
                self.critical("Instance " + instance.id + " now in " + instance.state  + " state")
            else:
                self.debug( "Instance " + instance.id + " now in " + instance.state  + " state")
        #    
        # check to see if public and private DNS names and IP addresses are the same
        #
            if (instance.ip_address is instance.private_ip_address) and (instance.public_dns_name is instance.private_dns_name) and ( private_addressing is False ):
                self.debug(str(instance) + " got Public IP: " + str(instance.ip_address)  + " Private IP: " + str(instance.private_ip_address) + " Public DNS Name: " + str(instance.public_dns_name) + " Private DNS Name: " + str(instance.private_dns_name))
                self.critical("Instance " + instance.id + " has he same public and private IPs of " + str(instance.ip_address))
            else:
                self.debug(str(instance) + " got Public IP: " + str(instance.ip_address)  + " Private IP: " + str(instance.private_ip_address) + " Public DNS Name: " + str(instance.public_dns_name) + " Private DNS Name: " + str(instance.private_dns_name))
                self.test_resources["reservations"].append(reservation)
            self.wait_for_valid_ip(instance)
        #if we can establish an SSH session convert the instances to the test class euinstance for access to instance specific test methods
        if(is_reachable) and ((keypair is not None) or (user is not None and password is not None)):
            return self.convert_reservation_to_euinstance(reservation, username=username, password=password, keyname=keypair)
        else:
            return reservation

    def wait_for_valid_ip(self, instance, timeout = 60):
        elapsed = 0
        zeros = re.compile("0.0.0.0")
        while elapsed <= timeout:
            if zeros.search(instance.public_dns_name):
                self.sleep(1)
                instance.update()
                elapsed = elapsed + 1
            else:
                return True
        raise Exception("Timed out waiting for a valid IP (ie anything other than 0.0.0.0.)")
                
            

    def convert_reservation_to_euinstance(self, reservation, username="root", password=None, keyname=None):
        euinstance_list = []
        for instance in reservation.instances:
            keypair = self.get_keypair(keyname)
            try:
                euinstance_list.append( EuInstance.make_euinstance_from_instance( instance, self, keypair=keypair, username = username, password=password ))
            except Exception, e:
                self.critical("Unable to create Euinstance from " + str(instance))
                euinstance_list.append(instance)
                
        reservation.instances = euinstance_list
        return reservation
   
    def get_keypair(self, name):
        return self.ec2.get_all_key_pairs([name])[0]
 
    def get_instances(self, 
                      state=None, 
                      idstring=None, 
                      reservation=None, 
                      rootdevtype=None, 
                      zone=None,
                      key=None,
                      pubip=None,
                      privip=None,
                      ramdisk=None,
                      kernel=None,
                      image_id=None
                      ):
        """
        Returns a list of boto instance objects filtered by the provided search criteria
        Options: 
        state, idstring , reservation , rootdevtype , zone ,key ,
        pubip ,privip ,ramdisk ,kernel , image_id
        
        example: instance = self.get_instances(state='running')[0]
        """
        ilist = []
        reservations = self.ec2.get_all_instances()
        for res in reservations:
            if ( reservation is None ) or (re.search(reservation, res.id)):
                for i in res.instances:
                    if (idstring is not None) and (not re.search(idstring, i.id)) :
                        continue
                    if (state is not None) and (i.state != state):
                        continue
                    if (rootdevtype is not None) and (i.root_device_type != rootdevtype):
                        continue
                    if (zone is not None) and (i.placement != zone ):
                        continue
                    if (key is not None) and (i.key_name != key):
                        continue
                    if (pubip is not None) and (i.ip_address != pubip):
                        continue
                    if (privip is not None) and (i.private_ip_address != privip):
                        continue
                    if (ramdisk is not None) and (i.ramdisk != ramdisk):
                        continue
                    if (kernel is not None) and (i.kernel != kernel):
                        continue
                    if (image_id is not None) and (i.image_id != image_id):
                        continue
                    ilist.append(i)
        return ilist
    
    
    def get_connectable_euinstances(self,path=None,connect=True):
        '''
        convenience method returns a list of all running instances, for the current creduser
        for which there are local keys at 'path'
        '''
        try:
            instances = []  
            euinstances = []
            keys = self.get_all_current_local_keys(path=path)
            if keys != []:
                for keypair in keys:
                    self.debug('looking for instances using keypair:'+keypair.name)
                    instances = self.get_instances(state='running',key=keypair.name)
                    if instances != []:
                        for instance in instances:
                            if not connect:
                                keypair=None
                            euinstances.append(EuInstance.make_euinstance_from_instance( instance, self, keypair=keypair))
                      
            return euinstances
        except Exception, e:
            self.debug("Failed to find a pre-existing isntance we can connect to:"+str(e))
            pass
    
    
    def get_all_attributes(self, obj, buf="", verbose=True):   
        '''
        Get a formatted list of all the key pair values pertaining to the object 'obj'
        '''   
        buf=""
        list = sorted(obj.__dict__)
        for item in list:
            if verbose:
                print str(item)+" = "+str(obj.__dict__[item])
            buf += str(item)+" = "+str(obj.__dict__[item])+"\n"
        return buf
              
    
    
    
    

    def release_address(self, ip=None):
        """
        Release all addresses or a particular IP
        ip        IP to release
        """   
        ## Clear out all addresses found
        self.debug( "Releasing all unassociated and allocated addresses")
        addresses = self.ec2.get_all_addresses()
        for address in addresses:
            ## IF i am searching for a particular IP and this is not it skip it
            #if (ip is not None) and (address.public_ip is not ip):
            #    continue
            if address.allocation_id != None:
                try:
                    self.debug("Releasing address: " + str(address))
                    address.release()
                except Exception, e:
                    self.critical("Failed to release the address: " + str(address) + ": " +  str(e))
                    return False
        return True
            
    def terminate_instances(self, reservation=None):
        """
        Terminate instances in the system
        reservation        Reservation object to terminate all instances in, default is to terminate all instances
        """
        ### If a reservation is not passed then kill all instances
        aggregate_result = True
        if reservation==None:
            reservations = self.ec2.get_all_instances()
            for res in reservations:
                for instance in res.instances:
                    self.debug( "Sending terminate for " + str(instance) )
                    instance.terminate()
                if self.wait_for_reservation(res, state="terminated") is False:
                    aggregate_result = False
        ### Otherwise just kill this reservation
        else:
            for instance in reservation.instances:
                    self.debug( "Sending terminate for " + str(instance) )
                    instance.terminate()
            if self.wait_for_reservation(reservation, state="terminated") is False:
                aggregate_result = False
        return aggregate_result
    
    def stop_instances(self,reservation):
        for instance in reservation.instances:
            self.debug( "Sending stop for " + str(instance) )
            instance.stop()
        if self.wait_for_reservation(reservation, state="stopped") is False:
            return False
        return True
    
    def start_instances(self,reservation):
        for instance in reservation.instances:
            self.debug( "Sending start for " + str(instance) )
            instance.start()
        if self.wait_for_reservation(reservation, state="running") is False:
            return False
        return True
    